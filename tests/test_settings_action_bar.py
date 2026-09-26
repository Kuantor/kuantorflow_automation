"""The Settings dialog pins its two ways out (kuantorflow#431, closing #120).

Save was below the fold: the dialog scrolled, every button sat at the bottom
of the scrolling content, and on a short window the primary action of the
whole dialog was off screen when it opened. The scroll moved to an inner
wrapper, which pins the footer below it and the close cross above.

**What this file can and cannot settle.** That the footer holds still is a
rendered fact, and this suite does not render — it was measured in a browser
(375x812, scrolled 1815px: cross and footer both moved 0px; 1280x500, scrolled
1257px: footer on screen, scroll region 306px) and that measurement lives in
the PR rather than in an assertion pretending to be one.

What is pinned here is the **structure that makes it possible**, and every one
of these fails silently — the dialog renders, opens, saves and closes with any
of them broken:

**The scroll is on the inner wrapper, not the dialog.** Put `overflow-y` back
on `.settings-dialog` and the cross rides away again, which is #120 returning
with no error anywhere.

**`min-height: 0` appears twice.** A flex item defaults to `min-height: auto`
and will not shrink below its content, so without it on the *form* the footer
is pushed past the dialog's 90vh — the dialog scrolls again by another route,
and the symptom being fixed comes back looking like a different bug.

**The 65vh cap is overridden.** `.modal-scroll` was written for card lists;
this dialog is 90vh, so inheriting that number makes the panel *shorter* than
it was. Nothing errors; the panel is just smaller than it should be, which
nobody measures.

**The right things are in the right containers.** `#settings-error` in the
footer, because pinned buttons with a message left in the scroll means Save
fails silently. Reset Auth and Delete account *out* of the footer, because a
button pressed once in a lifetime should not be a permanent neighbour of Save.
"""

import re

import pytest


@pytest.fixture()
def dialog(client):
    """The Settings dialog markup as an anonymous visitor gets it."""
    return _dialog(client.get("/").get_data(as_text=True))


@pytest.fixture()
def signed_in_dialog(user_client):
    """And as a signed-in one does — the variant a browser check cannot reach
    without an OAuth round trip, and the only one with Delete account in it."""
    return _dialog(user_client.get("/").get_data(as_text=True))


def _dialog(html):
    at = html.index('id="settings-modal"')
    return html[at:html.index('id="delete-account-modal"', at)]


def _css(client):
    return client.get("/static/css/style.css").get_data(as_text=True)


def _rule(css, selector):
    """The declarations of the first rule whose selector list contains this
    exact selector.

    Comments are stripped first, and that is not a detail: this stylesheet
    documents nearly every rule, so without it the text of the comment above a
    rule is swallowed into its selector and no exact match ever succeeds.
    Written the obvious way first, where it returned None for every selector
    and six tests failed on an AttributeError rather than on the thing they
    were about.

    Matched on the selector rather than on a slice of the file, so re-ordering
    the stylesheet does not break the test.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        heads = [h.strip() for h in match.group(1).split(",")]
        if selector in heads:
            return match.group(2)
    return None


# --- the scroll is on the wrapper, not the dialog ---------------------------

def test_the_dialog_holds_a_scrolling_wrapper(dialog):
    assert "settings-scroll" in dialog


def test_the_wrapper_reuses_the_shared_scroll_class(dialog):
    """`.modal-scroll` carries #370's two measured paddings. A bespoke class
    would have to re-derive them, and the one that matters — the left 2px for
    a focus ring — is invisible until somebody tabs through the panel."""
    at = dialog.index("settings-scroll")
    tag = dialog[dialog.rindex("<div", 0, at):dialog.index(">", at)]

    assert "modal-scroll" in tag, tag


def test_the_dialog_itself_no_longer_scrolls(client):
    """The #120 half. `.modal-close` is absolute against `.modal`; it only
    ever rode away because this box was the one scrolling."""
    declarations = _rule(_css(client), ".settings-dialog")

    assert declarations is not None, ".settings-dialog has no rule at all"
    assert "overflow-y: auto" not in declarations, (
        "the dialog scrolls again, so the close cross scrolls away with it")


def test_the_dialog_is_a_flex_column(client):
    declarations = _rule(_css(client), ".settings-dialog")

    assert "display: flex" in declarations
    assert "flex-direction: column" in declarations


# --- the two min-heights, and the cap ---------------------------------------

def test_the_form_can_shrink_below_its_content(client):
    """The one that is easy to miss. Without it the footer is pushed past the
    dialog's 90vh and the dialog scrolls again — the symptom #431 fixes,
    arriving by a different route and looking like a new bug."""
    declarations = _rule(_css(client), "#settings-form")

    assert declarations is not None, "the form has no rule, so it cannot flex"
    assert "min-height: 0" in declarations
    assert "flex-direction: column" in declarations


def test_the_scroller_can_shrink_below_its_content(client):
    declarations = _rule(_css(client), ".settings-scroll")

    assert declarations is not None
    assert "min-height: 0" in declarations


def test_the_scroller_does_not_inherit_the_card_lists_cap(client):
    """`.modal-scroll` is a fixed `max-height: 65vh` written for card lists.
    This dialog is 90vh, so inheriting it renders the panel **shorter** than
    it was before the change — no error, just quietly smaller."""
    shared = _rule(_css(client), ".modal-scroll")
    mine = _rule(_css(client), ".settings-scroll")

    assert "65vh" in shared, "the cap moved; this test's premise needs checking"
    assert "max-height: none" in mine, (
        "the settings scroller inherits 65vh and the panel shrinks")


# --- the right things in the right containers -------------------------------

def _footer(dialog):
    at = dialog.index('class="settings-footer"')
    depth, i = 0, dialog.index(">", at)
    start = i
    while True:
        nxt = min((x for x in (dialog.find("<div", i + 1), dialog.find("</div", i + 1))
                   if x != -1), default=-1)
        if nxt == -1:
            return dialog[start:]
        depth += 1 if dialog.startswith("<div", nxt) else -1
        i = nxt
        if depth < 0:
            return dialog[start:nxt]


def test_the_footer_holds_cancel_and_save(dialog):
    footer = _footer(dialog)

    assert 'id="settings-cancel"' in footer
    assert 'id="settings-save"' in footer


def test_the_footer_holds_only_those_two(dialog):
    """"Pin two buttons, not four." Reset Auth and Delete account in a pinned
    bar would make them permanent neighbours of Save, which is the arrangement
    #431 exists to undo."""
    footer = _footer(dialog)

    assert 'id="reset-auth-btn"' not in footer
    assert 'id="delete-account-btn"' not in footer


def test_the_error_message_is_in_the_footer(dialog):
    """Otherwise the failure path breaks in the quietest possible way: press
    Save, the save fails, the message renders up in the scrolled-away region,
    and the button appears to do nothing."""
    assert 'id="settings-error"' in _footer(dialog)


def test_the_account_actions_are_in_the_scrolling_region(dialog):
    """And below the caption that names the account they act on."""
    scroll_at = dialog.index("settings-scroll")
    footer_at = dialog.index('class="settings-footer"')
    reset_at = dialog.index('id="reset-auth-btn"')

    assert scroll_at < reset_at < footer_at, (
        "Reset Auth is not inside the scrolling region")


def test_reset_auth_sits_under_the_account_caption(dialog):
    """Under it, not beside it: these are actions *on* the identity that
    caption names, and grouping them below says so."""
    caption_at = dialog.index('class="settings-scope"')
    reset_at = dialog.index('id="reset-auth-btn"')

    assert caption_at < reset_at
    assert "settings-account-actions" in dialog[caption_at:reset_at]


# --- both variants render ---------------------------------------------------

def test_the_read_only_bar_has_close_and_a_disabled_save(dialog):
    """The ticket expected one button here; the markup has always rendered
    two, the second disabled. Recorded rather than corrected — a bar that
    loses its disabled Save would change what an anonymous visitor sees."""
    footer = _footer(dialog)
    save_at = footer.index('id="settings-save"')
    save_tag = footer[footer.rindex("<button", 0, save_at):footer.index(">", save_at)]

    assert ">Close<" in footer
    assert "disabled" in save_tag, save_tag


def test_the_signed_in_bar_offers_cancel_and_an_enabled_save(signed_in_dialog):
    footer = _footer(signed_in_dialog)
    save_at = footer.index('id="settings-save"')
    save_tag = footer[footer.rindex("<button", 0, save_at):footer.index(">", save_at)]

    assert ">Cancel<" in footer
    assert "disabled" not in save_tag, save_tag


def test_delete_account_is_out_of_the_bar_for_a_signed_in_visitor(
        signed_in_dialog):
    """The variant that actually has the button — an anonymous visitor never
    renders it, so the anonymous case cannot prove this one."""
    assert 'id="delete-account-btn"' in signed_in_dialog, (
        "the signed-in fixture is not rendering the button at all")
    assert 'id="delete-account-btn"' not in _footer(signed_in_dialog)


# --- what #238 left behind ---------------------------------------------------

def test_the_four_button_phone_grid_is_gone(client):
    """#238 placed four buttons in a two-by-two grid because they did not fit
    across 360px. The bar holds two now, so the grid solves nothing — and it
    assigned `grid-row` to a `.settings-reset` that is no longer inside
    `.modal-actions`, which is a rule matching nothing."""
    css = _css(client)

    assert "#settings-modal .settings-reset" not in css, (
        "a rule still places Reset Auth inside the settings action row")


def test_reset_auth_no_longer_pushes_anything_across_the_dialog(client):
    """Its `margin: 0 auto 0 0` right-aligned Cancel and Save in a shared row.
    They are in a different container now, so an auto margin here would only
    shove Delete account the width of the dialog."""
    declarations = _rule(_css(client), ".settings-reset")

    assert "auto" not in declarations.split("margin:")[1].split(";")[0], (
        "the auto margin outlived the row it was pushing against")


# --- no horizontal scroll bar -----------------------------------------------
#
# The panel grew one along its bottom edge the moment the inner scroller was
# added. Both causes were older than #431 -- the 0.4rem of padding on each
# side of the scroller is exactly the slack the content had been getting away
# with -- and both are invisible to this suite, so what is pinned is the two
# rules, with the measurements in the docstrings.
#
# Verified at 320, 375, 480, 700 and 1280: horizontal overflow 0 at every one.


def test_the_fieldsets_may_shrink_below_their_content(client):
    """A `<fieldset>` carries `min-width: min-content` from the UA stylesheet,
    which no other element does, and will not shrink below it however narrow
    its grid track is.

    The remedy that looks right is `minmax(0, 1fr)` on the grid, and it is
    **not** this one: it corrects the track and not the fieldset inside it.
    Measured at 700 -- `min-width: 0` alone gives 0 overflow, `minmax` alone
    gives 16, both give 0. Written here so the next person does not swap one
    for the other and check only the width it happens to work at.
    """
    declarations = _rule(_css(client), ".settings-group")

    assert declarations is not None
    assert "min-width: 0" in declarations, (
        "the fieldsets can refuse their track again, and the panel scrolls "
        "sideways")


def test_the_long_key_names_can_break(client):
    """`GOOGLE_TRANSLATE_API_KEY` is 170px in a 274px column on a 375pt phone,
    so it sets the min-content width of everything above it.

    **`anywhere`, not `break-word`.** Both let a long word break; only
    `anywhere` counts that when min-content is computed, which is what a grid
    track sizes against. Measured at 375: `break-word` left all 22px of
    overflow, `anywhere` took it to zero. The two are one word apart in the
    source and a world apart in effect.
    """
    declarations = _rule(_css(client), ".settings-inline-hint code")

    assert declarations is not None, (
        "nothing lets the environment-variable names wrap")
    assert "anywhere" in declarations, (
        "break-word does not reduce min-content; only anywhere does")
