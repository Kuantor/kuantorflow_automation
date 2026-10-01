"""A styled file picker on *Upload notes* (kuantorflow#502, item 6).

The browser's raw "Choose File" button was the one control on the home page
left in the operating system's own style. It is styled through
`::file-selector-button` rather than replaced, so the native input keeps its
keyboard handling, its label and the chosen file's name beside the button --
the things a hidden input behind a fake button has to rebuild by hand.
"""

import re


def _css(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _declarations(css, selector):
    found = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in [s.strip() for s in selectors.split(",")]:
            found.update((k.strip(), v.strip()) for k, v in
                         re.findall(r"([\w-]+)\s*:\s*([^;]+)", body))
    return found


def test_choose_file_is_the_sites_outlined_button(client):
    button = _declarations(_css(client), 'input[type="file"]::file-selector-button')
    assert "var(--blue)" in button.get("border", ""), button
    assert button.get("background") == "#fff" and "border-radius" in button, button


def test_keyboard_focus_shows_on_the_picker(client):
    assert "outline" in _declarations(_css(client), 'input[type="file"]:focus-visible')


def test_the_native_input_is_still_the_control(client):
    """Not hidden behind a fake button: no rule may take the real input out
    of sight, and it keeps its label and its file types."""
    css = _css(client)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if 'input[type="file"]' in selectors and "::" not in selectors:
            assert not re.search(r"display\s*:\s*none|opacity\s*:\s*0\b|visibility\s*:\s*hidden", body), selectors
    body = client.get("/").get_data(as_text=True)
    assert re.search(r'<label for="notes-file">', body)
    assert re.search(r'<input type="file" id="notes-file"[^>]*accept="\.txt,\.docx,\.mht,\.mhtml"[^>]*required', body)
