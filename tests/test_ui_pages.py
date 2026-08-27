"""Index page UI, banners, and link-preview meta tags."""

import re

from conftest import in_other


def _meta(body, prop, attr="property"):
    m = re.search(rf'{attr}="{prop}" content="([^"]+)"', body)
    return m.group(1) if m else None


def test_topic_tiles(client, app_module, monkeypatch):
    """Each topic is a tile linking to it, with its card count (#184)."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other(
                            [("basics", 12), ("it-vocab", 5)]))
    body = client.get("/").get_data(as_text=True)
    assert "/flashcards/basics" in body and "12 cards" in body
    assert "/flashcards/it-vocab" in body and "5 cards" in body


def test_no_topics_hint(client):
    body = client.get("/").get_data(as_text=True)
    assert "No topics yet" in body


def test_page_survives_db_failure(client, app_module, monkeypatch):
    def boom(owner_id=None):
        raise RuntimeError("db down")
    monkeypatch.setattr(app_module, "get_topics_by_section", boom)
    r = client.get("/")
    assert r.status_code == 200
    assert "No topics yet" in r.get_data(as_text=True)


def test_submit_buttons_have_loading_feedback(client):
    body = client.get("/").get_data(as_text=True)
    assert "Looking up…" in body and "btn.disabled = true" in body


def test_about_modal_markup(client):
    body = client.get("/").get_data(as_text=True)
    assert 'id="about-link"' in body
    assert "img/main_image.jpg" in body
    assert 'id="about-modal"' in body and "modal-close" in body


# The database check moved into the Settings popup (#184); its tests live in
# test_main_page_layout.py with the rest of that change.


def test_preview_meta_on_gate_page(fresh_client):
    """Crawlers get redirected to the gate — it must carry the OG tags."""
    body = fresh_client.get("/enter").get_data(as_text=True)
    assert _meta(body, "og:image").endswith("/static/img/preview.jpg")
    assert _meta(body, "og:title") == "KuantorFlow"
    assert "flashcards" in _meta(body, "og:description")


def test_preview_meta_on_index(client):
    body = client.get("/").get_data(as_text=True)
    for tag in ("og:title", "og:description", "og:url", "og:site_name", "og:type"):
        assert f'property="{tag}"' in body, f"{tag} missing"
    assert _meta(body, "og:image").startswith("http")
    assert 'name="twitter:card" content="summary_large_image"' in body


def test_proxyfix_makes_absolute_https_urls(client):
    r = client.get("/", headers={
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "kuantorflow.pythonanywhere.com",
        "X-Forwarded-For": "1.2.3.4",
    })
    body = r.get_data(as_text=True)
    assert _meta(body, "og:image") == \
        "https://kuantorflow.pythonanywhere.com/static/img/preview.jpg"


def test_page_specific_titles_in_og_title(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic", lambda topic, owner_id=None: [])
    body = client.get("/flashcards/basics").get_data(as_text=True)
    assert "basics" in _meta(body, "og:title")


def test_favicon_and_preview_image_served(client):
    for path in ("/static/img/icon.jpg", "/static/img/preview.jpg"):
        assert client.get(path).status_code == 200, f"{path} not served"
