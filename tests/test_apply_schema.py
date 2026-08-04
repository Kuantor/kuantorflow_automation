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
from apply_schema import Column, Constraint, Index, Pending, Table

CREATE_TABLE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.I)
ADD_COLUMN = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", re.I)
ADD_INDEX = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+INDEX\s+(\w+)", re.I)
ADD_CONSTRAINT = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+CONSTRAINT\s+(\w+)", re.I)

# Statements that move data rather than creating anything (kuantorflow#207's
# backfill). Recognised explicitly, so an unknown statement is still a loud
# failure rather than being waved through as "probably harmless".
MOVES_DATA = re.compile(r"(INSERT|UPDATE)\s+", re.I)

# Lines inside a CREATE TABLE body that continue the previous definition
# rather than starting a column of their own.
NOT_A_COLUMN = {"PRIMARY", "UNIQUE", "KEY", "FOREIGN", "REFERENCES", "ON", "CHECK"}

# Which table a probe reads, and the columns it names. Enough to tell a probe
# that cannot run yet from one that simply finds nothing left to do.
PROBE_TABLE = re.compile(r"FROM\s+(\w+)", re.I)
PROBE_COLUMN = re.compile(r"(\w+)\s+(?:IS\s+(?:NOT\s+)?NULL|<>|=)", re.I)


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
    if MOVES_DATA.match(sql):
        return set()
    raise AssertionError(f"the fake database does not understand: {sql}")


class FakeDatabase:
    """Stands in for both the connection and the objects it holds.

    Answers apply_schema.Schema's information_schema lookups from a set of
    objects, and updates that set as DDL runs through it.
    """

    def __init__(self, objects=(), failing=None, unmigrated=False):
        self.objects = set(objects)
        self.executed = []      # statements, in order
        self.commits = 0
        self.closed = False
        self.failing = failing  # substring of a statement that must blow up
        # Whether rows are still waiting to be migrated. A data step has no
        # object to look up, so this is what its probe reports on — and running
        # the step is what clears it, the same way DDL updates `objects`.
        self.unmigrated = unmigrated

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
            if "information_schema" in sql:
                self._rows = [(1,)] if self._target(sql, params) in self.objects else []
            else:
                self._rows = self._probe(sql)
            return
        if self.failing and self.failing in sql:
            raise RuntimeError("mysql said no")
        self.executed.append(sql)
        self.objects.update(objects_created_by(sql))
        if MOVES_DATA.match(sql):
            self.unmigrated = False

    def _probe(self, sql):
        """Answer a data step's probe, or refuse it as MySQL would.

        A probe names the column an earlier step adds, so on a database that has
        not had that step applied — every `--dry-run` — the real database
        rejects it. Reproduced here rather than smoothed over: the tolerance for
        that is the behaviour worth pinning down.
        """
        table = PROBE_TABLE.search(sql).group(1)
        for name in PROBE_COLUMN.findall(sql):
            if Column(table, name) not in self.objects:
                raise RuntimeError(f"Unknown column '{name}' in '{table}'")
        return [(1,)] if self.unmigrated else []

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


def test_schema_sql_is_its_tables_in_dependency_order(schema_sql):
    steps = apply_schema.schema_steps(schema_sql)
    # users and topics before flashcards: its foreign keys need both to exist
    # first, and the file is applied in the order it is written.
    assert [s.name for s in steps] == [
        "anonymous_usage", "users", "topics", "flashcards"]
    assert [s.target for s in steps] == [
        Table("anonymous_usage"), Table("users"), Table("topics"),
        Table("flashcards")]


def test_every_foreign_key_target_is_created_before_the_table_needing_it(
        schema_sql):
    """The ordering above is load-bearing, so it is checked rather than trusted.

    A REFERENCES naming a table defined further down the file would apply
    cleanly to a database that already had it and fail on a fresh one — the
    worst kind of schema bug, because only new installations see it.
    """
    created = []
    for statement in apply_schema.parse_statements(schema_sql):
        table = CREATE_TABLE.match(statement).group(1)
        for referenced in re.findall(r"REFERENCES\s+(\w+)", statement, re.I):
            assert referenced in created or referenced == table, (
                f"{table} references {referenced}, which schema.sql "
                f"creates later")
        created.append(table)


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


def test_the_topic_backfill_runs_after_its_column_and_before_its_key():
    """#207's chain: the column has to exist for the data to go anywhere, and
    the data has to be right before a foreign key can describe it."""
    names = [step.name for step in apply_schema.MIGRATIONS]
    assert (names.index("flashcards.topic_id")
            < names.index("flashcards.topic_id backfill")
            < names.index("flashcards.idx_topic_id")
            < names.index("flashcards.fk_flashcards_topic"))


def test_every_migration_names_the_object_its_sql_creates():
    """Otherwise the step is never seen as done and re-runs on every deploy."""
    for step in apply_schema.MIGRATIONS:
        if isinstance(step.target, Pending):
            continue        # nothing to name — see the data-step tests below
        created = set()
        for statement in step.statements:
            created |= objects_created_by(statement)
        assert step.target in created, f"{step.name} does not create {step.target}"


# --- data steps ---------------------------------------------------------
#
# A step that moves data creates no object, so it cannot be checked by name.
# It carries a probe instead: SQL that still returns rows while there is work
# left. These pin down that the probe describes the *work* and not the shape of
# the schema — a probe that asked "does the topics table have rows?" would call
# a half-finished backfill done.


def test_a_data_step_creates_nothing_and_carries_a_probe():
    for step in apply_schema.MIGRATIONS:
        if not isinstance(step.target, Pending):
            continue
        assert step.target.probe.strip(), f"{step.name} has an empty probe"
        for statement in step.statements:
            assert objects_created_by(statement) == set(), (
                f"{step.name} creates an object, so it should name it "
                f"rather than probe for it")


def test_the_backfill_probe_describes_rows_left_to_migrate():
    step = _backfill()
    probe = " ".join(step.target.probe.split())
    assert "topic_id IS NULL" in probe, \
        "the question is which cards are still unlinked"
    assert "FROM flashcards" in probe, \
        "asked of the cards, which is where the work is"


def test_a_data_step_is_done_when_its_probe_finds_nothing():
    db = FakeDatabase(_migrated_objects(), unmigrated=False)
    assert apply_schema.Schema(db).exists(_backfill().target) is True


def test_a_data_step_is_pending_while_its_probe_finds_rows():
    db = FakeDatabase(_migrated_objects(), unmigrated=True)
    assert apply_schema.Schema(db).exists(_backfill().target) is False


def test_a_probe_that_cannot_run_yet_reads_as_pending():
    """The --dry-run case, and the reason the probe is allowed to fail.

    Under --dry-run the column the probe names was only *reported*, never added,
    so the database rejects the query. That rejection is the answer: nothing has
    been backfilled. Without this, looking before you leap would crash.
    """
    db = FakeDatabase(_pre_207_objects(), unmigrated=True)
    with pytest.raises(RuntimeError):
        db.execute(_backfill().target.probe)     # the fake refuses it, as MySQL would
    assert apply_schema.Schema(db).exists(_backfill().target) is False


def test_a_dry_run_on_a_pre_207_database_reports_the_backfill_instead_of_failing(
        schema_sql, capsys):
    db = FakeDatabase(_pre_207_objects(), unmigrated=True)
    steps = apply_schema.schema_steps(schema_sql) + list(apply_schema.MIGRATIONS)
    changed, _ = apply_schema.run(steps, apply_schema.Schema(db), db, dry_run=True)
    out = capsys.readouterr().out
    assert "~ flashcards.topic_id backfill" in out
    assert db.executed == [], "a dry run touches nothing"
    assert changed


def test_the_backfill_is_skipped_once_the_rows_are_linked(schema_sql, capsys):
    db = FakeDatabase(_migrated_objects(), unmigrated=False)
    apply_schema.run(list(apply_schema.MIGRATIONS), apply_schema.Schema(db), db)
    assert "= flashcards.topic_id backfill" in capsys.readouterr().out
    assert db.executed == []


# --- running ------------------------------------------------------------


def test_a_fresh_database_gets_its_tables_and_needs_no_migrations(schema_sql):
    db = FakeDatabase()
    created, present = apply_schema.run(
        apply_schema.schema_steps(schema_sql), apply_schema.Schema(db), db)
    assert (created, present) == (len(apply_schema.parse_statements(schema_sql)), 0)

    # Every migration is already satisfied by the CREATE TABLE statements —
    # the two halves of the schema describe the same database. Counted from
    # MIGRATIONS rather than a literal, so adding one does not fail this.
    applied, skipped = apply_schema.run(
        apply_schema.MIGRATIONS, apply_schema.Schema(db), db)
    assert (applied, skipped) == (0, len(apply_schema.MIGRATIONS))


def test_a_pre_89_database_gets_the_column_index_and_key(schema_sql):
    db = FakeDatabase(_pre_89_objects(), unmigrated=True)
    created, present = apply_schema.run(
        apply_schema.schema_steps(schema_sql), apply_schema.Schema(db), db)
    # topics did not exist before #207, so it is created; the three tables that
    # were already there are left alone.
    assert (created, present) == (1, 3)
    assert Table("topics") in db.objects

    applied, skipped = apply_schema.run(
        apply_schema.MIGRATIONS, apply_schema.Schema(db), db)
    assert (applied, skipped) == (len(apply_schema.MIGRATIONS), 0)
    assert Column("flashcards", "added_by_user_id") in db.objects
    assert Index("flashcards", "idx_added_by") in db.objects
    assert Constraint("flashcards", "fk_flashcards_user") in db.objects
    assert Column("flashcards", "topic_id") in db.objects
    assert Constraint("flashcards", "fk_flashcards_topic") in db.objects
    assert not db.unmigrated, "the backfill ran, so no card is left unlinked"


def test_a_second_run_changes_nothing(schema_sql):
    db = FakeDatabase(_pre_89_objects(), unmigrated=True)
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
    db = FakeDatabase(objects, unmigrated=True)
    applied, skipped = apply_schema.run(
        apply_schema.MIGRATIONS, apply_schema.Schema(db), db)
    assert (applied, skipped) == (len(apply_schema.MIGRATIONS) - 1, 1)


def test_an_interrupted_backfill_is_finished_by_the_next_run():
    """The probe describes the work, so a partial run reads as unfinished.

    This is the property that makes a 300-card migration safe to interrupt:
    the fix for a run that died halfway is to run it again.
    """
    db = FakeDatabase(_migrated_objects(), unmigrated=True)
    applied, _ = apply_schema.run(
        apply_schema.MIGRATIONS, apply_schema.Schema(db), db)
    assert applied == 1, "only the backfill was outstanding"
    assert db.executed, "and it actually ran"
    assert not db.unmigrated


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


def _backfill():
    """#207's data step, found by its target rather than by its name."""
    steps = [s for s in apply_schema.MIGRATIONS if isinstance(s.target, Pending)]
    assert steps, "no data step to test"
    return steps[0]


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


def _pre_207_objects():
    """As it stood before #207: cards have a topic string and no topic_id."""
    return _pre_89_objects() | {
        Column("flashcards", "pos"),
        Column("flashcards", "added_by_user_id"),
        Index("flashcards", "idx_added_by"),
        Constraint("flashcards", "fk_flashcards_user"),
        Column("users", "blocked_at"),
    }


def _migrated_objects():
    """Everything #207 creates, so only the *data* can still be outstanding."""
    return _pre_207_objects() | {
        Table("topics"),
        Column("flashcards", "topic_id"),
        Index("flashcards", "idx_topic_id"),
        Constraint("flashcards", "fk_flashcards_topic"),
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
