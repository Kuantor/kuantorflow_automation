"""Index page UI, banners, and link-preview meta tags."""

import re


def _meta(body, prop, attr="property"):
    m = re.search(rf'{attr}="{prop}" content="([^"]+)"', body)
    return m.group(1) if m else None


def test_topic_chips(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_topics",
                        lambda: [("basics", 12), ("it-vocab", 5)])
    body = client.get("/").get_data(as_text=True)
    assert "/flashcards/basics" in body and "(12)" in body
    assert "/flashcards/it-vocab" in body


def test_no_topics_hint(client):
    body = client.get("/").get_data(as_text=True)
    assert "No topics yet" in body


def test_page_survives_db_failure(client, app_module, monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(app_module, "get_topics", boom)
    r = client.get("/")
    assert r.status_code == 200
    assert "No topics yet" in r.get_data(as_text=True)


def test_submit_buttons_have_loading_feedback(client):
    body = client.get("/").get_data(as_text=True)
    assert "Looking up…" in body and "btn.disabled = true" in body


def test_about_modal_markup(client):
    body = client.get("/").get_data(as_text=True)
    assert 'id="about-link"' in body
    assert "img/main_image.png" in body
    assert 'id="about-modal"' in body and "modal-close" in body


def test_db_success_banner_is_green(client, app_module, monkeypatch):
    class FakeConn:
        def close(self):
            pass
    monkeypatch.setattr(app_module, "get_db_connection", FakeConn)
    r = client.post("/", data={"action": "test_db"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert re.search(
        r'<div class="banner confirmation">\s*Database connection successful!', body
    ), "success message not in the green confirmation banner"


def test_db_failure_banner_is_red(client, app_module, monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(app_module, "get_db_connection", boom)
    body = client.post("/", data={"action": "test_db"}).get_data(as_text=True)
    assert re.search(r'<div class="banner error"><strong>Error: db down', body)


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
    monkeypatch.setattr(app_module, "get_flashcards_by_topic", lambda topic: [])
    body = client.get("/flashcards/basics").get_data(as_text=True)
    assert "basics" in _meta(body, "og:title")


def test_favicon_and_preview_image_served(client):
    for path in ("/static/img/icon.png", "/static/img/preview.jpg"):
        assert client.get(path).status_code == 200, f"{path} not served"
