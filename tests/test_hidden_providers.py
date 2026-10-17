"""Hidden providers: saving Settings, and where they are written down
(kuantorflow#459).

The panel now offers only the providers this deployment can use, and ticks
the one that answers. Two things that change could break quietly:

* **saving Settings must not rewrite a stored choice the panel cannot show.**
  The ticked radio is the provider that answers, so sending it on every save
  would replace an account's hidden choice the first time it saved anything.
  The page sends a provider only when the learner picked a different one;
  otherwise the field is left out and the server keeps what is stored;
* **a deployment with no translator renders no translator radio**, and the
  save must not read one that is not there.

The providers that are not offered are written down for whoever runs the site
in `docs/future-enhancements.md`, which Mykola must **not** read.
"""

import re
from pathlib import Path

from conftest import KUANTORFLOW_PATH

APP = Path(KUANTORFLOW_PATH)


def _save_script(body):
    found = re.search(r"body: JSON\.stringify\(\{(.*?)\}\),", body, re.S)
    assert found, "the Settings save request is missing"
    return found.group(1)


def test_the_save_sends_a_provider_only_when_the_learner_changed_it(client):
    save = _save_script(client.get("/").get_data(as_text=True))

    assert re.search(r'translator:\s*pickedProvider\("translator"\)', save)
    assert re.search(r'explanatory_dictionary:\s*pickedProvider\("explanatory_dictionary"\)', save)
    assert "settingsForm.translator.value" not in save
    assert "settingsForm.explanatory_dictionary.value" not in save


def test_the_helper_leaves_an_unchanged_or_missing_group_out(client):
    body = client.get("/").get_data(as_text=True)
    helper = body.split("function pickedProvider(")[1].split("\n            }")[0]

    assert ":checked" in helper
    assert "defaultChecked" in helper
    assert "undefined" in helper


def test_the_document_names_every_hidden_provider():
    text = (APP / "docs" / "future-enhancements.md").read_text(encoding="utf-8")

    for name in ("Microsoft Translator", "DeepL", "Google Cloud Translation",
                 "Merriam-Webster", "#110", "Bing"):
        assert name in text, name
    assert (APP / "docs" / "future-enhancements.pdf").exists()


def test_mykola_does_not_read_it():
    """He would offer a learner DeepL as if it could be picked."""
    import chat

    knowledge = chat.MYKOLA_KNOWLEDGE
    items = knowledge if isinstance(knowledge, (list, tuple)) else [knowledge]
    assert not any("future-enhancements" in str(k) for k in items)
    source = (APP / "chat.py").read_text(encoding="utf-8")
    assert "future-enhancements" in source, "say why it is left out, beside the list"


def test_the_readme_links_it():
    assert "docs/future-enhancements" in (APP / "README.md").read_text(encoding="utf-8")


def test_the_guide_no_longer_describes_greyed_providers():
    guide = (APP / "docs" / "user-guide.md").read_text(encoding="utf-8")

    assert "greyed out and say which key" not in guide
    assert "Merriam-Webster is greyed out" not in guide
