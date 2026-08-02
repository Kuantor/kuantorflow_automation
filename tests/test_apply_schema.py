"""
apply_schema.py — the deploy step that applies schema changes (kuantorflow#180).

These run fully offline against a fake database that remembers only which
objects exist. The fake learns what a statement created **from the statement
itself**, never from the step that ran it, so a migration whose SQL does not
build the object its target names shows up here as a step that keeps
re-applying — which is exactly the failure the idempotency check has to catch.

The end-to-end run against a real MySQL is test_apply_schema_db.py (marker db).
"""

import re

import pytest

import apply_schema
from apply_schema import Column, Constraint, Index, Table

CREATE_TABLE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.I)
ADD_COLUMN = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", re.I)
ADD_INDEX = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+INDEX\s+(\w+)", re.I)
ADD_CONSTRAINT = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+CONSTRAINT\s+(\w+)", re.I)

# Lines inside a CREATE TABLE body that continue the previous definition
# rather than starting a column of their own.
NOT_A_COLUMN = {"PRIMARY", "UNIQUE", "KEY", "FOREIGN", "REFERENCES", "ON", "CHECK"}


def objects_created_by(sql):
    """Read out of a statement what it leaves behind in the database."""
    match = CREATE_TABLE.match(sql)
    if match:
        table = match.group(1)
        created = {Table(table)}
        body = sql[sql.index("(") + 1:sql.rindex(")")]
        for line in body.splitlines():
            parts = line.strip().rstrip(",").split()
            if not parts or parts[0].upper() in NOT_A_COLUMN:
                continue
            if parts[0].upper() == "INDEX":
                created.add(Index(table, parts[1]))
            elif parts[0].upper() == "CONSTRAINT":
                created.add(Constraint(table, parts[1]))
            else:
                created.add(Column(table, parts[0]))
        return created
    for pattern, kind in ((ADD_COLUMN, Column), (ADD_INDEX, Index),
                          (ADD_CONSTRAINT, Constraint)):
        match = pattern.match(sql)
        if match:
            return {kind(match.group(1), match.group(2))}
    raise AssertionError(f"the fake database does not understand: {sql}")


class FakeDatabase:
    """Stands in for both the connection and the objects it holds.

    Answers apply_schema.Schema's information_schema lookups from a set of
    objects, and updates that set as DDL runs through it.
    """

    def __init__(self, objects=(), failing=None):
        self.objects = set(objects)
        self.executed = []      # DDL only, in order
        self.commits = 0
        self.closed = False
        self.failing = failing  # substring of a statement that must blow up

    # -- connection ------------------------------------------------------
    def cursor(self):
        return self

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True

    # -- cursor ----------------------------------------------------------
    def execute(self, sql, params=None):
        if sql.lstrip().upper().startswith("SELECT"):
            self._rows = [(1,)] if self._target(sql, params) in self.objects else []
            return
        if self.failing and self.failing in sql:
            raise RuntimeError("mysql said no")
        self.executed.append(sql)
        self.objects.update(objects_created_by(sql))

    def fetchall(self):
        return self._rows

    @staticmethod
    def _target(sql, params):
        kind = {
            "information_schema.TABLES": lambda p: Table(p[0]),
            "information_schema.COLUMNS": lambda p: Column(*p),
            "information_schema.STATISTICS": lambda p: Index(*p),
            "information_schema.TABLE_CONSTRAINTS": lambda p: Constraint(*p),
        }
        for name, build in kind.items():
            if name in sql:
                return build(params)
        raise AssertionError(f"unexpected lookup: {sql}")


@pytest.fixture()
def schema_sql():
    return apply_schema.SCHEMA_PATH.read_text(encoding="utf-8")


# --- schema.sql is only ever CREATE TABLE ------------------------------


def test_a_commented_out_alter_is_not_a_statement():
    """The #180 bug itself: an ALTER in a comment is not applied by anything."""
    statements = apply_schema.parse_statements(
        "CREATE TABLE IF NOT EXISTS t (id INT);\n"
        "-- If the table already exists, run:\n"
        "-- ALTER TABLE t ADD COLUMN pos VARCHAR(20);\n"
    )
    assert statements == ["CREATE TABLE IF NOT EXISTS t (id INT)"]
    assert not any("ALTER" in s for s in statements)


def test_parse_statements_splits_and_drops_trailing_noise():
    statements = apply_schema.parse_statements(
        "CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);\n\n-- done\n")
    assert statements == ["CREATE TABLE a (id INT)", "CREATE TABLE b (id INT)"]


def test_schema_sql_is_the_three_tables_in_file_order(schema_sql):
    steps = apply_schema.schema_steps(schema_sql)
    # users before flashcards: flashcards' foreign key needs it to exist first.
    assert [s.name for s in steps] == ["anonymous_usage", "users", "flashcards"]
    assert [s.target for s in steps] == [
        Table("anonymous_usage"), Table("users"), Table("flashcards")]


def test_an_alter_left_in_schema_sql_is_rejected():
    """The trap cannot come back: a bare ALTER in the file is a loud error."""
    with pytest.raises(apply_schema.SchemaError) as excinfo:
        apply_schema.schema_steps(
            "CREATE TABLE t (id INT);\nALTER TABLE t ADD COLUMN pos VARCHAR(20);")
    assert "MIGRATIONS" in str(excinfo.value)


# --- the migration list -------------------------------------------------


def test_migrations_are_ordered_column_then_index_then_constraint():
    names = [step.name for step in apply_schema.MIGRATIONS]
    assert names.index("flashcards.added_by_user_id") < names.index("flashcards.idx_added_by")
    assert names.index("flashcards.idx_added_by") < names.index("flashcards.fk_flashcards_user")


def test_every_migration_names_the_object_its_sql_creates():
    """Otherwise the step is never seen as done and re-runs on every deploy."""
    for step in apply_schema.MIGRATIONS:
        created = set()
        for statement in step.statements:
            created |= objects_created_by(statement)
        assert step.target in created, f"{step.name} does not create {step.target}"


# --- running ------------------------------------------------------------


def test_a_fresh_database_gets_its_tables_and_needs_no_migrations(schema_sql):
    db = FakeDatabase()
    created, present = apply_schema.run(
        apply_schema.schema_steps(schema_sql), apply_schema.Schema(db), db)
    assert (created, present) == (3, 0)

    # Every migration is already satisfied by the CREATE TABLE statements —
    # the two halves of the schema describe the same database. Counted from
    # MIGRATIONS rather than a literal, so adding one does not fail this.
    applied, skipped = apply_schema.run(
        apply_schema.MIGRATIONS, apply_schema.Schema(db), db)
    assert (applied, skipped) == (0, len(apply_schema.MIGRATIONS))


def test_a_pre_89_database_gets_the_column_index_and_key(schema_sql):
    db = FakeDatabase(_pre_89_objects())
    created, present = apply_schema.run(
        apply_schema.schema_steps(schema_sql), apply_schema.Schema(db), db)
    assert (created, present) == (0, 3), "existing tables are left alone"

    applied, skipped = apply_schema.run(
        apply_schema.MIGRATIONS, apply_schema.Schema(db), db)
    assert (applied, skipped) == (len(apply_schema.MIGRATIONS), 0)
    assert Column("flashcards", "added_by_user_id") in db.objects
    assert Index("flashcards", "idx_added_by") in db.objects
    assert Constraint("flashcards", "fk_flashcards_user") in db.objects


def test_a_second_run_changes_nothing(schema_sql):
    db = FakeDatabase(_pre_89_objects())
    steps = apply_schema.schema_steps(schema_sql) + list(apply_schema.MIGRATIONS)
    apply_schema.run(steps, apply_schema.Schema(db), db)
    after_first = list(db.executed)

    changed, skipped = apply_schema.run(steps, apply_schema.Schema(db), db)
    assert changed == 0
    assert skipped == len(steps)
    assert db.executed == after_first, "a re-run must not touch the database"


def test_a_half_applied_database_finishes_the_rest():
    """Production had the ALTERs run by hand; the run must not choke on them."""
    objects = _pre_89_objects() | {Column("flashcards", "added_by_user_id")}
    db = FakeDatabase(objects)
    applied, skipped = apply_schema.run(
        apply_schema.MIGRATIONS, apply_schema.Schema(db), db)
    assert (applied, skipped) == (len(apply_schema.MIGRATIONS) - 1, 1)


def test_dry_run_reports_without_touching_anything(schema_sql, capsys):
    db = FakeDatabase(_pre_89_objects())
    changed, skipped = apply_schema.run(
        apply_schema.MIGRATIONS, apply_schema.Schema(db), db, dry_run=True)
    assert (changed, skipped) == (len(apply_schema.MIGRATIONS), 0)
    assert db.executed == []
    assert db.commits == 0
    assert "would be applied" in capsys.readouterr().out


def test_a_failing_statement_names_the_step_that_failed():
    db = FakeDatabase(_pre_89_objects(), failing="ADD INDEX")
    with pytest.raises(apply_schema.StepFailed) as excinfo:
        apply_schema.run(apply_schema.MIGRATIONS, apply_schema.Schema(db), db)
    assert excinfo.value.step == "flashcards.idx_added_by"
    assert "ADD INDEX" in str(excinfo.value)


def test_each_step_is_reported_either_way(schema_sql, capsys):
    db = FakeDatabase(_pre_89_objects())
    apply_schema.run(apply_schema.schema_steps(schema_sql), apply_schema.Schema(db), db)
    apply_schema.run(apply_schema.MIGRATIONS, apply_schema.Schema(db), db)
    out = capsys.readouterr().out
    # A deploy that changed nothing must not look like one that did.
    assert "= anonymous_usage" in out and "already present" in out
    assert "+ flashcards.added_by_user_id" in out and "applied" in out


# --- the command line ---------------------------------------------------


def test_main_on_a_current_database_says_nothing_to_do(monkeypatch, capsys):
    db = _current_database()
    monkeypatch.setattr(apply_schema, "get_db_connection", lambda: db)
    assert apply_schema.main([]) == 0
    assert "nothing to do" in capsys.readouterr().out
    assert db.executed == []
    assert db.closed, "the connection is closed even when there is nothing to do"


def test_main_applies_then_becomes_a_no_op(monkeypatch, capsys):
    db = FakeDatabase()
    monkeypatch.setattr(apply_schema, "get_db_connection", lambda: db)

    assert apply_schema.main([]) == 0
    assert "change(s) applied" in capsys.readouterr().out

    db.closed = False
    assert apply_schema.main([]) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_main_exits_non_zero_when_a_migration_fails(monkeypatch, capsys):
    db = FakeDatabase(_pre_89_objects(), failing="ADD COLUMN added_by_user_id")
    monkeypatch.setattr(apply_schema, "get_db_connection", lambda: db)

    assert apply_schema.main([]) == 1
    captured = capsys.readouterr()
    assert "flashcards.added_by_user_id failed" in captured.err
    assert db.closed, "the connection is closed even when a step fails"


def test_main_dry_run_leaves_the_database_alone(monkeypatch, capsys):
    db = FakeDatabase(_pre_89_objects())
    monkeypatch.setattr(apply_schema, "get_db_connection", lambda: db)
    assert apply_schema.main(["--dry-run"]) == 0
    assert "pending" in capsys.readouterr().out
    assert db.executed == []


# --- helpers ------------------------------------------------------------


def _pre_89_objects():
    """The database as it stood before #89: no pos, no owner column."""
    return {
        Table("anonymous_usage"),
        Table("users"),
        Table("flashcards"),
        Column("flashcards", "id"),
        Column("flashcards", "word"),
        Column("flashcards", "topic"),
        Index("flashcards", "idx_topic"),
        Index("flashcards", "idx_word"),
    }


def _current_database():
    """A database with everything schema.sql and MIGRATIONS describe."""
    db = FakeDatabase()
    steps = (apply_schema.schema_steps(
        apply_schema.SCHEMA_PATH.read_text(encoding="utf-8"))
        + list(apply_schema.MIGRATIONS))
    apply_schema.run(steps, apply_schema.Schema(db), db)
    db.executed.clear()
    db.commits = 0
    return db
