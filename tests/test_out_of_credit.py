"""What the app says when the Claude credit runs out (kuantorflow#99).

The failure being guarded is **silence**, and it is a specific kind. Every paid
path catches its own exception and shows one calm sentence, which is the right
answer for a network blip and the wrong one for an exhausted balance: *please
try again* will not work until somebody pays, and nothing else on the site
looks broken while it is happening. The feature simply stops, politely.

So there are two assertions worth making and they pull against each other --
that the money case is named and reaches the person who can fix it, and that
**every other failure keeps the old sentence**, because a site that blamed
billing for a timeout would be worse than one that said nothing.

Detection is by message rather than by exception class, because Anthropic
reports an exhausted balance as an ordinary BadRequestError whose text names
the balance. The strings below are the real wording, not invented ones.
"""

import pytest

import billing
import textgen


# The message Anthropic actually returns, and the one ai_agent has matched on
# since long before billing.py existed.
REAL = ("Error code: 400 - {'type': 'error', 'error': {'type': "
        "'invalid_request_error', 'message': 'Your credit balance is too low "
        "to access the Anthropic API. Please go to Plans & Billing to upgrade "
        "or purchase credits.'}}")


@pytest.mark.parametrize("message", [
    REAL,
    "your credit balance is too low",
    "Insufficient credits for this request",
])
def test_the_money_is_recognised(message):
    assert billing.out_of_credit(Exception(message)) is True


@pytest.mark.parametrize("message", [
    "Connection error.",
    "Request timed out",
    "overloaded_error: the model is temporarily overloaded",
    "the model returned nothing",
])
def test_everything_else_is_not_the_money(message):
    """The assertion that keeps this honest. Blaming billing for a timeout
    would send the owner to top up an account that is already funded."""
    assert billing.out_of_credit(Exception(message)) is False


def test_no_error_at_all_is_not_the_money():
    assert billing.out_of_credit(None) is False


def test_the_notice_says_who_to_tell():
    """The person reading the screen cannot fix this; the sentence is only
    useful if it reaches the person who can."""
    notice = billing.credit_notice()
    assert billing.SUPPORT_EMAIL in notice
    assert "@" in billing.SUPPORT_EMAIL


def test_the_notice_says_that_waiting_will_not_help():
    assert "try again" not in billing.credit_notice().casefold().replace(
        "trying again will not help", "")


def test_a_caller_keeps_its_own_wording_for_everything_else():
    """`failure_notice()` names which feature failed by taking the caller's
    sentence; one sentence here could not say 'the text' and 'the topic'."""
    assert billing.failure_notice(Exception("Connection error."),
                                  "The text could not be written.") == \
        "The text could not be written."


# --- through the feature that actually calls it ----------------------------


def _generated(message):
    """A real `generate()` run whose one model call fails with `message`."""
    def explode(*args, **kwargs):
        raise Exception(message)

    return textgen.generate(["resign"], "", 60, ask=explode)


def test_a_text_that_failed_for_money_says_so(monkeypatch):
    result = _generated(REAL)
    assert billing.SUPPORT_EMAIL in result["error"]


def test_a_text_that_failed_for_anything_else_keeps_the_old_sentence():
    result = _generated("Connection error.")
    assert result["error"] == ("The text could not be written just now. "
                               "Please try again.")


def test_a_text_that_worked_has_no_error():
    result = textgen.generate(["resign"], "", 60,
                              ask=lambda *a, **k: "A short passage. He resigned.")
    assert result["error"] is None
