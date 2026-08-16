"""The destination topic in the review popup (kuantorflow#294).

The popup carried every fact about a card except where it was going. The topic
was chosen two panels away, before a lookup that takes a few seconds, and by
the time the cards are on screen there was nothing saying which topic they
would be filed under.

Two things are worth pinning beyond "the line is there":

* **it is the resolved topic**, not the raw field. An empty Topic box becomes
  `general` in `app.py` before the popup renders, and since kuantorflow#292
  took the old `general` placeholder for the chooser's wording, this line is
  the only place that default is now visible;
* **it cannot disagree with what will be written.** Every card carries a hidden
  `topic`, and a heading that named something else would be worse than no
  heading at all — so the line is checked against those inputs rather than
  against the string that was posted.

Both flows the popup opens in are covered: a word lookup, and the review of a
parsed notes file. They render from the same template block but through
different paths, and only the second needs an account (#125).
"""

import io
import re

import pytest

TOPIC_LINE = re.compile(r'<p class="proposal-topic">Topic: <strong>([^<]*)</strong></p>')


def _stub_lookup(app_module, monkeypatch):
    monkeypatch.setattr(
        app_module, "lookup_word",
        lambda word, topic=None, **providers: [
            {"word": word, "pos": "noun", "translation_ukr": "імовірність",
             "explanation_en": "how likely something is", "topic": topic},
            {"word": word, "pos": "adjective", "translation_ukr": "імовірний",
             "topic": topic},
        ])


def _lookup(client, topic):
    return client.post("/", data={"action": "parse_word", "word": "probability",
                                  "topic": topic}).get_data(as_text=True)


def _upload(client, topic):
    return client.post(
        "/",
        data={"action": "upload_notes", "topic": topic,
              "notes_file": (io.BytesIO("probability - імовірність\n".encode()),
                             "notes.txt")},
        content_type="multipart/form-data",
        follow_redirects=True).get_data(as_text=True)


# --- the line -----------------------------------------------------------


def test_the_popup_names_the_topic(client, app_module, monkeypatch, saved):
    _stub_lookup(app_module, monkeypatch)
    body = _lookup(client, "Work and careers")

    assert 'id="proposal-modal"' in body
    assert TOPIC_LINE.findall(body) == ["Work and careers"]
    assert saved == [], "nothing is saved by rendering the popup"


def test_the_file_review_names_it_too(user_client, saved):
    """The other flow the same block renders in. An upload needs an account
    (#125), which is the only difference that matters here."""
    body = _upload(user_client, "Work and careers")

    assert "Review the cards parsed from your file" in body
    assert TOPIC_LINE.findall(body) == ["Work and careers"]
    assert saved == []


def test_an_empty_topic_field_shows_where_the_cards_really_go(
        client, app_module, monkeypatch, saved):
    """`general` is a real destination, not a placeholder: `app.py` resolves an
    empty box to it twice over. Since #292 gave the chooser the move dialog's
    wording, this line is the only place that default is now visible."""
    _stub_lookup(app_module, monkeypatch)
    assert TOPIC_LINE.findall(_lookup(client, "")) == ["general"]


def test_the_line_agrees_with_what_the_cards_will_write(client, app_module,
                                                        monkeypatch, saved):
    """The heading and the hidden inputs are two statements about the same
    thing, and a heading that named a different topic would be worse than
    none."""
    _stub_lookup(app_module, monkeypatch)
    body = _lookup(client, "Health and medicine")

    named = TOPIC_LINE.findall(body)
    written = sorted(set(re.findall(r'name="topic" value="([^"]*)"', body)))
    assert named == ["Health and medicine"]
    assert written == named


def test_it_is_said_once_however_many_cards_there_are(client, app_module,
                                                      monkeypatch, saved):
    """Once for the popup, not once per card: the stub returns two cards, a
    parsed file can return a dozen, and the answer is the same every time."""
    _stub_lookup(app_module, monkeypatch)
    body = _lookup(client, "vocab")

    assert body.count('class="proposal-card"') == 2
    assert body.count('class="proposal-topic"') == 1


def test_a_topic_name_is_text_not_markup(client, app_module, monkeypatch, saved):
    """The name is whatever somebody typed into a free-text box (#292), so it
    reaches the popup escaped or it reaches it as markup."""
    _stub_lookup(app_module, monkeypatch)
    body = _lookup(client, 'Ann & "co" <b>')

    assert 'Topic: <strong>Ann &amp; &#34;co&#34; &lt;b&gt;</strong>' in body
    assert "<b></strong>" not in body


# --- and nothing else moved --------------------------------------------


def test_the_popup_still_asks_its_question(client, app_module, monkeypatch,
                                           saved):
    """The line is an addition, not a replacement: the title is what tells the
    learner they are being asked rather than told."""
    _stub_lookup(app_module, monkeypatch)
    body = _lookup(client, "vocab")

    assert "Do you want to add the card(s) to the database?" in body
    assert body.index("proposal-title") < body.index("proposal-topic") \
        < body.index("proposal-card")


def test_no_topic_line_without_a_popup(client, app_module, monkeypatch):
    """It belongs to the popup, not to the page — the index renders the same
    template every time, popup or not."""
    monkeypatch.setattr(app_module, "flashcard_word_exists", lambda w: True)
    body = client.get("/").get_data(as_text=True)
    assert "proposal-topic" not in body
