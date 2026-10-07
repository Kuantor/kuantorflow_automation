"""What each paid model call used, logged (kuantorflow#562).

Every AI call the site makes was logged, but only Mykola's lines said what it
used. The four calls this repo makes itself -- the translator, the generated
text, the topic builder and the notes splitter -- now each write one
`MODEL-USAGE` line to `model_usage.log`, read off the response's `usage`, and
`scripts/model_usage_report.py` totals them with Mykola's lines.

The real `anthropic` package is not in this venv, so a fake module stands in,
recording nothing and answering with a response that carries `usage`.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

import applog
import parsers
import textgen
import topicgen

KUANTORFLOW = Path(parsers.__file__).parent


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Usage:
    input_tokens, output_tokens = 432, 43
    cache_creation_input_tokens, cache_read_input_tokens = 0, 0


class _Response:
    def __init__(self, text, usage=True, stop="end_turn"):
        self.content = [_Block(text)]
        self.stop_reason = stop
        if usage:
            self.usage = _Usage()


@pytest.fixture()
def fake_anthropic(monkeypatch):
    """A fake `anthropic` whose client answers with whatever is queued."""
    replies = []
    fake = types.ModuleType("anthropic")

    class _Messages:
        def create(self, **kwargs):
            return replies.pop(0)

    class Anthropic:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    fake.Anthropic = Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return replies


def _usage_lines(action_logs):
    path = action_logs / "model_usage.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _fields(line):
    import re
    return dict(re.findall(r"(\w+)=('(?:[^'\\]|\\.)*'|\S+)", line))


# --- the four calls -------------------------------------------------------

def test_the_translator_logs_what_it_used(fake_anthropic, action_logs):
    fake_anthropic.append(_Response(json.dumps(
        {"entries": [{"part_of_speech": "adjective",
                      "translations": ["стійкий"]}]})))

    parsers._claude_dictionary("resilient", "uk")

    (line,) = _usage_lines(action_logs)
    fields = _fields(line)
    assert " MODEL-USAGE " in line
    assert fields["feature"] == applog.USAGE_TRANSLATE
    assert fields["model"] == parsers.TRANSLATE_MODEL
    assert fields["in"] == "432" and fields["out"] == "43"
    assert fields["stop"] == "end_turn" and float(fields["ms"]) >= 0


def test_the_notes_splitter_logs_what_it_used(fake_anthropic, action_logs):
    fake_anthropic.append(_Response(json.dumps({"0": ["абв", "где"]})))

    parsers._split_glued_translations(["абвгде"])

    (line,) = _usage_lines(action_logs)
    assert _fields(line)["feature"] == applog.USAGE_SPLIT
    assert _fields(line)["model"] == parsers.SPLIT_MODEL


def test_the_generated_text_logs_what_it_used(fake_anthropic, action_logs):
    fake_anthropic.append(_Response("A Title\n\nOne sentence about work."))

    textgen._ask_claude("prompt", 100)

    (line,) = _usage_lines(action_logs)
    assert _fields(line)["feature"] == applog.USAGE_GENERATE
    assert _fields(line)["model"] == textgen.TEXT_MODEL


def test_a_text_cut_off_still_logs_what_it_spent(fake_anthropic, action_logs):
    """A reply stopped at max_tokens spent its tokens; those are exactly the
    calls worth seeing, so the line is written before the truncation check."""
    fake_anthropic.append(_Response("A Title\n\nOne whole sentence. And then",
                                    stop="max_tokens"))

    textgen._ask_claude("prompt", 100)

    (line,) = _usage_lines(action_logs)
    assert _fields(line)["stop"] == "max_tokens"


def test_the_topic_builder_logs_what_it_used(fake_anthropic, action_logs):
    fake_anthropic.append(_Response("Work\n- salary\n- deadline"))

    topicgen._ask_claude("prompt", 10)

    (line,) = _usage_lines(action_logs)
    assert _fields(line)["feature"] == applog.USAGE_TOPIC
    assert _fields(line)["model"] == topicgen.TOPIC_MODEL


def test_the_features_are_the_declared_four():
    assert set(applog.USAGE_FEATURES) == {"translate", "generate", "topic", "split"}


# --- never in the way -----------------------------------------------------

def test_a_response_without_usage_writes_nothing(fake_anthropic, action_logs):
    fake_anthropic.append(_Response("Work\n- salary", usage=False))

    assert topicgen._ask_claude("prompt", 10)
    assert _usage_lines(action_logs) == []


def test_a_broken_log_does_not_break_the_call(fake_anthropic, action_logs,
                                              monkeypatch):
    def broken(name):
        raise OSError("disk full")
    monkeypatch.setattr(applog, "_logger", broken)
    fake_anthropic.append(_Response("Work\n- salary"))

    assert topicgen._ask_claude("prompt", 10) == "Work\n- salary"


def test_a_strange_usage_object_does_not_break_the_call(fake_anthropic,
                                                        action_logs):
    """`model_usage()`'s own guard, which the test above cannot reach: a
    broken log file is already swallowed inside `_write()`. Found by
    prove_fails.py, which flagged the guard's removal as caught by nothing."""
    class _Unreadable:
        @property
        def input_tokens(self):
            raise RuntimeError("an SDK that changed shape")

    response = _Response("Work\n- salary")
    response.usage = _Unreadable()
    fake_anthropic.append(response)

    assert topicgen._ask_claude("prompt", 10) == "Work\n- salary"


def test_inside_a_request_the_line_carries_the_request_id(fake_anthropic,
                                                           action_logs):
    import web
    from flask import g
    fake_anthropic.append(_Response("Work\n- salary"))

    with web.app.test_request_context("/"):
        web.app.preprocess_request()
        rid = g.request_id
        topicgen._ask_claude("prompt", 10)

    assert _fields(_usage_lines(action_logs)[0])["rid"] == rid


# --- the report -----------------------------------------------------------

def _report():
    path = KUANTORFLOW / "scripts" / "model_usage_report.py"
    spec = importlib.util.spec_from_file_location("model_usage_report", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


USAGE_LOG = "\n".join([
    "2026-10-06 10:00:00 MODEL-USAGE feature=translate model=haiku in=400 out=40 "
    "cache_write=0 cache_read=0 stop=end_turn ms=1500 rid=aaaa1111",
    "2026-10-07 10:00:00 MODEL-USAGE feature=translate model=haiku in=432 out=43 "
    "cache_write=0 cache_read=0 stop=end_turn ms=2100",
    "2026-10-07 10:00:02 MODEL-USAGE feature=translate model=haiku in=432 out=44 "
    "cache_write=0 cache_read=0 stop=end_turn ms=1600",
    "2026-10-07 11:00:00 MODEL-USAGE feature=generate model=haiku in=300 out=500 "
    "cache_write=0 cache_read=0 stop=max_tokens ms=4000",
    "",
])
MYKOLA_LOG = "\n".join([
    "2026-10-07 12:00:00 in=2 out=122 cache_write=6348 cache_read=0 stop=end_turn "
    "first=1.61 total=2.62 fast=yes",
    "2026-10-07 12:00:05 tool=add_flashcard topic='music' word='loyal' status='saved'",
    "2026-10-07 12:00:06 AGENT-UNAVAILABLE error='nope'",
    "",
])


@pytest.fixture()
def logs(tmp_path):
    (tmp_path / "model_usage.log").write_text(USAGE_LOG, encoding="utf-8")
    (tmp_path / "mykola.log").write_text(MYKOLA_LOG, encoding="utf-8")
    return tmp_path


def test_the_report_totals_per_day_feature_and_model(logs):
    report = _report()
    totals = report.summarise(report.read_records(logs, "opus"))

    assert totals[("2026-10-07", "translate", "haiku")] == {
        "calls": 2, "in": 864, "out": 87, "cache_write": 0, "cache_read": 0}
    assert totals[("2026-10-07", "generate", "haiku")]["calls"] == 1
    assert totals[("2026-10-07", "mykola", "opus")] == {
        "calls": 1, "in": 2, "out": 122, "cache_write": 6348, "cache_read": 0}
    assert len(totals) == 4, "the tool line and the other mykola.log line are not usage"


def test_the_report_reads_rotated_files_too(logs):
    (logs / "model_usage.log.2026-09-07").write_text(
        "2026-09-07 10:00:00 MODEL-USAGE feature=split model=haiku in=10 out=5 "
        "cache_write=0 cache_read=0 stop=end_turn ms=900\n", encoding="utf-8")
    report = _report()

    assert ("2026-09-07", "split", "haiku") in report.summarise(report.read_records(logs))


def test_the_days_window_drops_older_lines(logs):
    report = _report()
    totals = report.summarise(report.read_records(logs), since="2026-10-07")

    assert all(day == "2026-10-07" for day, _, _ in totals)


def test_rates_turn_tokens_into_money_and_a_missing_rate_shows_a_dash(logs):
    report = _report()
    totals = report.summarise(report.read_records(logs, "opus"), since="2026-10-07")
    text = report.render(totals, {"haiku": {"in": 1.0, "out": 5.0}})

    translate = next(l for l in text.splitlines() if " translate " in l)
    assert translate.rstrip().endswith("0.0013")     # (864*1 + 87*5) / 1e6
    mykola = next(l for l in text.splitlines() if " mykola " in l)
    assert mykola.rstrip().endswith("-"), "no rate for opus: no guess"
    assert "rows without a rate not included" in text


def test_an_empty_log_says_so(tmp_path, capsys):
    _report().main(["--logs", str(tmp_path)])

    assert "no model usage logged" in capsys.readouterr().out
