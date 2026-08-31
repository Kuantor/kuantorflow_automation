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
# The table an ALTER names, then every clause it adds. Read as two steps rather
# than one pattern per kind, because a single ALTER may add several things and
# only the first clause repeats the table name: `users.blocked_at` adds two
# columns and so does `topics.section_id` (kuantorflow#215). Matching only the
# first left the fake believing a two-column ALTER added one column.
ALTER_TABLE = re.compile(r"ALTER\s+TABLE\s+(\w+)\s", re.I)
# `UNIQUE KEY` is how a unique index is added to an existing table, and it
# leaves behind exactly what `ADD INDEX` does (kuantorflow#382).
ADD_CLAUSE = re.compile(
    r"ADD\s+(COLUMN|INDEX|CONSTRAINT|UNIQUE\s+KEY)\s+(\w+)", re.I)
ADDS = {"COLUMN": Column, "INDEX": Index, "CONSTRAINT": Constraint,
        "UNIQUE KEY": Index}

# Statements that move data rather than creating anything (kuantorflow#207's
# backfill). Recognised explicitly, so an unknown statement is still a loud
# failure rather than being waved through as "probably harmless".
MOVES_DATA = re.compile(r"(INSERT|UPDATE)\s+", re.I)

# Lines inside a CREATE TABLE body that continue the previous definition
# rather than starting a column of their own.
NOT_A_COLUMN = {"PRIMARY", "UNIQUE", "KEY", "FOREIGN", "REFERENCES", "ON", "CHECK"}

# A named unique key declared inside a CREATE TABLE body. It is an object a
# migration can target -- kuantorflow#382 swaps one for another — and the fake
# was skipping the line as "not a column" without recording the index, so a
# fresh database looked as though it lacked a key schema.sql had just made.
UNIQUE_KEY = re.compile(r"UNIQUE\s+KEY\s+(\w+)\s*\(", re.I)

# Dropping an index: creates nothing, and takes one away.
DROP_INDEX = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+DROP\s+INDEX\s+(\w+)", re.I)

# Which table a probe reads, and the columns it names. Enough to tell a probe
# that cannot run yet from one that simply finds nothing left to do.
PROBE_TABLE = re.compile(r"FROM\s+(\w+)", re.I)
PROBE_COLUMN = re.compile(r"(\w+)\s+(?:IS\s+(?:NOT\s+)?NULL|<>|=)", re.I)

# What a data statement fills in: the table it writes to, and the column it sets
# if it sets one. Together these are how the fake knows which *probe* a
# statement has just answered — see FakeDatabase._data_key. One flag for "has
# any data been migrated" was enough while #207's backfill was the only data
# step; with #215 there are three, and running one must not report the others
# as done.
WRITES_TO = re.compile(r"(?:INSERT\s+INTO|UPDATE)\s+(\w+)", re.I)
SETS_COLUMN = re.compile(r"SET\s+(?:\w+\.)?(\w+)\s*=", re.I)


def objects_created_by(sql):
    """Read out of a statement what it leaves behind in the database."""
    match = CREATE_TABLE.match(sql)
    if match:
        table = match.group(1)
        created = {Table(table)}
        body = sql[sql.index("(") + 1:sql.rindex(")")]
        for line in body.splitlines():
            parts = line.strip().rstrip(",").split()
            if not parts:
                continue
            if parts[0].upper() in NOT_A_COLUMN:
                key = UNIQUE_KEY.match(line.strip())
                if key:
                    created.add(Index(table, key.group(1)))
                continue
            if parts[0].upper() == "INDEX":
                created.add(Index(table, parts[1]))
            elif parts[0].upper() == "CONSTRAINT":
                created.add(Constraint(table, parts[1]))
            else:
                created.add(Column(table, parts[0]))
        return created
    match = ALTER_TABLE.match(sql)
    if match:
        table = match.group(1)
        added = {ADDS[" ".join(kind.upper().split())](table, name)
                 for kind, name in ADD_CLAUSE.findall(sql)}
        if added:
            return added
    if MOVES_DATA.match(sql):
        return set()
    if DROP_INDEX.match(sql):
        return set()
    raise AssertionError(f"the fake database does not understand: {sql}")


def objects_removed_by(sql):
    """What a statement takes away. Only DROP INDEX so far (kuantorflow#382).

    Kept beside `objects_created_by()` rather than folded into it: a step is
    reported and skipped by what it *leaves behind*, so a statement that
    removes something has to be a separate question or the fake would report
    the drop as a creation.
    """
    match = DROP_INDEX.match(sql)
    return {Index(match.group(1), match.group(2))} if match else set()


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
        # Which data work has been done, keyed the way _data_key describes.
        # `unmigrated` says the database starts with work outstanding
        # everywhere; this records what each statement has since settled, so
        # three data steps stay independent of one another.
        self._settled = set()

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
        self.objects -= objects_removed_by(sql)
        if MOVES_DATA.match(sql):
            self._settled.add(self._data_key(sql))

    @staticmethod
    def _data_key(sql):
        """What a data statement has filled in.

        `(table, column)` when it sets a column, so #207's UPDATE settles
        `flashcards.topic_id` and #215's settles `topics.section_id` without
        either touching the other. A bare table name when it only inserts rows,
        which is what #215's two starting sections are — and which deliberately
        does *not* collide with the `(topics, section_id)` key, so #207's
        `INSERT INTO topics` cannot be mistaken for the section backfill.
        """
        table = WRITES_TO.match(sql).group(1)
        column = SETS_COLUMN.search(sql)
        return (table, column.group(1)) if column else table

    def _probe(self, sql):
        """Answer a data step's probe, or refuse it as MySQL would.

        A probe names the table and column an earlier step creates, so on a
        database that has not had that step applied — every `--dry-run` — the
        real database rejects it. Reproduced here rather than smoothed over: the
        tolerance for that is the behaviour worth pinning down.
        """
        table = PROBE_TABLE.search(sql).group(1)
        if Table(table) not in self.objects:
            raise RuntimeError(f"Table '{table}' doesn't exist")
        columns = PROBE_COLUMN.findall(sql)
        for name in columns:
            if Column(table, name) not in self.objects:
                raise RuntimeError(f"Unknown column '{name}' in '{table}'")
        if not self.unmigrated:
            return []
        # The keys this probe is asking about — the columns it tests, or the
        # table itself when it only counts rows.
        asked = {(table, name) for name in columns} or {table}
        return [] if asked & self._settled else [(1,)]

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
    # users and topics before flashcards, and topic_sections before topics
    # (#215): every foreign key needs its target to exist first, and the file is
    # applied in the order it is written.
    #
    # text_generation_usage (#237) sits with anonymous_usage at the top and has
    # no foreign key at all — deliberately, since it holds day-scoped counters
    # rather than attribution — so its position is only tidiness.
    #
    # confirmed_words (kuantorflow#258) is the same case: no foreign key -- a
    # deleted account must not un-confirm English -- so it sits with them.
    assert [s.name for s in steps] == [
        "anonymous_usage", "text_generation_usage", "confirmed_words", "users",
        "topic_sections", "topics", "flashcards"]
    assert [s.target for s in steps] == [
        Table("anonymous_usage"), Table("text_generation_usage"),
        Table("confirmed_words"), Table("users"), Table("topic_sections"),
        Table("topics"), Table("flashcards")]


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


def test_the_section_chain_runs_column_then_rows_then_data_then_key():
    """#215's order, and every link in it is load-bearing.

    The column has to exist before a topic can point anywhere; the section rows
    have to exist before a topic can be pointed at one; and the data has to be
    right before a foreign key can describe it.
    """
    names = [step.name for step in apply_schema.MIGRATIONS]
    assert (names.index("topics.section_id")
            < names.index("topic_sections rows")
            < names.index("topics.section_id backfill")
            < names.index("topics.idx_topics_section")
            < names.index("topics.fk_topics_section"))


def test_sections_are_migrated_after_the_topics_they_group():
    """#207 has to have finished before #215 can start: the backfill files
    topics into a section, and #207's backfill is what creates those topics."""
    names = [step.name for step in apply_schema.MIGRATIONS]
    assert names.index("flashcards.topic_id backfill") \
        < names.index("topics.section_id backfill")


def test_both_section_columns_arrive_in_one_statement():
    """section_id and position are one feature, so there is no half-applied
    state for the idempotency check to miss — the users.blocked_at precedent."""
    statements = _step("topics.section_id").statements
    assert len(statements) == 1
    created = objects_created_by(statements[0])
    assert Column("topics", "section_id") in created
    assert Column("topics", "position") in created


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


def test_the_section_probe_describes_topics_left_without_one():
    """#215's backfill asks which topics are unfiled, not whether 'Other' has
    any members — a topic created after the last deploy is outstanding work."""
    probe = " ".join(_section_backfill().target.probe.split())
    assert "section_id IS NULL" in probe
    assert "FROM topics" in probe, "asked of the topics, which is where the work is"


def test_the_section_rows_probe_is_not_satisfied_by_one_of_the_two():
    """A run interrupted between the two inserts still has work left.

    The probe counts what it found rather than testing for existence, so
    'Other' alone does not report the pair as complete.
    """
    probe = " ".join(_step("topic_sections rows").target.probe.split())
    assert "FROM topic_sections" in probe
    assert "COUNT(*) < 2" in probe, "one row is not both sections"
    assert "Other" in probe and "Conversational Topics" in probe


def test_the_section_rows_step_only_inserts():
    """It creates no object, which is why it needs a probe at all — and it must
    not quietly alter the two rows if they are already there."""
    statements = _step("topic_sections rows").statements
    assert all(s.lstrip().upper().startswith("INSERT") for s in statements)
    assert all("ON DUPLICATE KEY UPDATE id = id" in s for s in statements), \
        "a re-run leaves an existing section exactly as it is"


def test_a_section_probe_reads_as_pending_before_its_table_exists():
    """The --dry-run case for #215, one table further out than #207's.

    #207's probe names a *column* that dry-run has not added; this one names a
    whole *table* that dry-run has not created. Both rejections have to read as
    'nothing done yet' rather than crashing the look-before-you-leap run.
    """
    db = FakeDatabase(_pre_215_objects(), unmigrated=True)
    with pytest.raises(RuntimeError):
        db.execute(_step("topic_sections rows").target.probe)
    assert apply_schema.Schema(db).exists(
        _step("topic_sections rows").target) is False


def test_a_dry_run_on_a_pre_215_database_reports_both_section_data_steps(
        schema_sql, capsys):
    db = FakeDatabase(_pre_215_objects(), unmigrated=True)
    steps = apply_schema.schema_steps(schema_sql) + list(apply_schema.MIGRATIONS)
    apply_schema.run(steps, apply_schema.Schema(db), db, dry_run=True)
    out = capsys.readouterr().out
    assert "~ topic_sections rows" in out
    assert "~ topics.section_id backfill" in out
    assert db.executed == [], "a dry run touches nothing"


def test_filling_one_data_step_leaves_the_others_outstanding():
    """The three data steps are independent (#207's cards, #215's rows and its
    backfill). Running one must not report the rest as done, which is what a
    single 'has anything been migrated' flag used to do."""
    db = FakeDatabase(_migrated_objects(), unmigrated=True)
    assert sorted(_outstanding(db)) == sorted(s.name for s in _data_steps())

    for statement in _backfill().statements:
        db.execute(statement)
    assert _backfill().name not in _outstanding(db)
    assert _section_backfill().name in _outstanding(db)
    assert "topic_sections rows" in _outstanding(db)


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
    # topics (#207), topic_sections (#215), text_generation_usage (#237) and
    # confirmed_words (kuantorflow#258) did not exist before, so all four are
    # created; the three tables that were already there are left alone.
    assert (created, present) == (4, 3)
    assert Table("topics") in db.objects
    assert Table("topic_sections") in db.objects
    assert Table("text_generation_usage") in db.objects
    assert Table("confirmed_words") in db.objects

    # The steps that alter `topics` are skipped, because the pass above just
    # created that table complete — columns, index and foreign key included.
    # That is the two halves of the schema agreeing, seen on one table: the same
    # property test_a_fresh_database_gets_its_tables_and_needs_no_migrations
    # states for all of them. Counted rather than written as a literal, so
    # #215's three do not become a stale number later.
    on_a_table_just_created = [
        s for s in apply_schema.MIGRATIONS
        if getattr(s.target, "table", None) == "topics"]
    applied, skipped = apply_schema.run(
        apply_schema.MIGRATIONS, apply_schema.Schema(db), db)
    assert (applied, skipped) == (
        len(apply_schema.MIGRATIONS) - len(on_a_table_just_created),
        len(on_a_table_just_created))
    assert Column("flashcards", "added_by_user_id") in db.objects
    assert Index("flashcards", "idx_added_by") in db.objects
    assert Constraint("flashcards", "fk_flashcards_user") in db.objects
    assert Column("flashcards", "topic_id") in db.objects
    assert Constraint("flashcards", "fk_flashcards_topic") in db.objects
    assert Column("topics", "section_id") in db.objects
    assert Column("topics", "position") in db.objects
    assert Index("topics", "idx_topics_section") in db.objects
    assert Constraint("topics", "fk_topics_section") in db.objects
    assert not _outstanding(db), "every data step ran"


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

    Counted from the data steps rather than from a literal, because #215 added
    two more of them and a hard-coded 1 would have gone quietly stale.
    """
    db = FakeDatabase(_migrated_objects(), unmigrated=True)
    applied, _ = apply_schema.run(
        apply_schema.MIGRATIONS, apply_schema.Schema(db), db)
    assert applied == len(_data_steps()), \
        "every object existed, so only the data steps were outstanding"
    assert db.executed, "and they actually ran"
    assert not _outstanding(db)


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


def _outstanding(db):
    """The data steps whose probes still report work left to do in `db`."""
    schema = apply_schema.Schema(db)
    return [s.name for s in _data_steps() if not schema.exists(s.target)]


def _data_steps():
    """Every step that moves data rather than creating an object."""
    steps = [s for s in apply_schema.MIGRATIONS if isinstance(s.target, Pending)]
    assert steps, "no data step to test"
    return steps


def _step(name):
    """One migration by name. Named rather than indexed since #215 added two
    more data steps and `the first Pending one` stopped meaning anything."""
    for step in apply_schema.MIGRATIONS:
        if step.name == name:
            return step
    raise AssertionError(f"no migration called {name!r}")


def _backfill():
    """#207's data step: the cards still waiting for a topic_id."""
    return _step("flashcards.topic_id backfill")


def _section_backfill():
    """#215's: the topics still waiting for a section."""
    return _step("topics.section_id backfill")


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


def _pre_215_objects():
    """As it stood after #207 and before sections: topics exist, ungrouped."""
    return _pre_207_objects() | {
        Table("topics"),
        Column("topics", "id"),
        Column("topics", "name"),
        Column("flashcards", "topic_id"),
        Index("flashcards", "idx_topic_id"),
        Constraint("flashcards", "fk_flashcards_topic"),
    }


def _migrated_objects():
    """Everything #207, #215, #382 and #390 create, so only the *data* can be
    outstanding."""
    return _pre_215_objects() | {
        Table("topic_sections"),
        Column("topics", "section_id"),
        Column("topics", "position"),
        Index("topics", "idx_topics_section"),
        Constraint("topics", "fk_topics_section"),
        # kuantorflow#382. The key is the *new* one: a database that has been
        # through this migration no longer holds uq_topics_name, and saying so
        # is what keeps "only the data can be outstanding" true.
        Column("topics", "is_public"),
        Column("topics", "namespace"),
        Index("topics", "uq_topics_namespace"),
        # kuantorflow#390. A column and nothing else: the credit a card carries
        # for its explanation has no data step, because NULL is the right
        # answer for every row that predates it.
        Column("flashcards", "explanation_source"),
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
