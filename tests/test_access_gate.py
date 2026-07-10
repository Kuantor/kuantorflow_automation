"""The keyword gate: every page is blocked until the keyword is entered."""


def test_pages_redirect_to_gate_when_unauthenticated(fresh_client):
    for path in ("/", "/flashcards/vocab", "/quiz/vocab"):
        r = fresh_client.get(path)
        assert r.status_code == 302, f"{path} not gated"
        assert r.headers["Location"].endswith("/enter")


def test_write_endpoints_are_gated(fresh_client):
    assert fresh_client.post("/cards/add", data={"word": "x"}).status_code == 302
    assert fresh_client.post("/flashcards/t/delete/1").status_code == 302


def test_gate_page_and_static_assets_reachable(fresh_client):
    r = fresh_client.get("/enter")
    assert r.status_code == 200
    assert b"Please enter the keyword to access my website." in r.data
    assert fresh_client.get("/static/css/style.css").status_code == 200


def test_wrong_keyword_shows_error(fresh_client):
    r = fresh_client.post("/enter", data={"keyword": "definitely-wrong"})
    assert r.status_code == 200
    assert b"Incorrect keyword" in r.data


def test_correct_keyword_opens_site(fresh_client, keyword):
    r = fresh_client.post("/enter", data={"keyword": keyword})
    assert r.status_code == 302
    assert fresh_client.get("/").status_code == 200


def test_fresh_session_is_gated_again(app_module, client):
    assert client.get("/").status_code == 200
    assert app_module.app.test_client().get("/").status_code == 302
