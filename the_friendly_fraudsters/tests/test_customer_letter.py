

import pytest

import utils.customer_letter as cl
from utils.customer_letter import Letter, check_letter, resolve_outcome, template_letter, write_customer_letter

TX = {"transaction_id": "TX-5006", "merchant": "PixelGames Store", "amount": 89.99, "currency": "GBP",
      "timestamp": "2026-11-10T21:45"}


def make_state(**overrides):
    state = {
        "complaint_id": "CMP-004",
        "complaint": {"text": "This PixelGames charge isn't me, I never bought anything.", "customer_id": "CUST-102"},
        "customer": {"customer_id": "CUST-102", "name": "Tom Hughes", "vulnerable": False},
        "transaction": TX,
        "reason_code": "fraud_card_not_present",
        "route": "friendly_fraud",
        "vulnerable_signals": [],
        "recommendation": "decline_claim",
        "decision": "approve",
        "reviewer_notes": "",
    }
    state.update(overrides)
    return state


class FakeWriter:

    def __init__(self, drafts):
        self.drafts, self.prompts = list(drafts), []

    def with_structured_output(self, schema, **kwargs):
        return self

    def invoke(self, prompt):
        self.prompts.append(prompt)
        draft = self.drafts.pop(0)
        if isinstance(draft, Exception):
            raise draft
        return draft


@pytest.fixture
def fake_llm(monkeypatch):
    def install(*drafts):
        writer = FakeWriter(drafts)
        monkeypatch.setattr(cl, "init_chat_model", lambda _model: writer)
        return writer
    return install


GOOD_DECLINE = Letter(subject="About your PixelGames Store payment", body=(
    "Dear Tom,\n\nThank you for asking us about the £89.99 payment to PixelGames Store. Our records show it was made "
    "in the usual way from a device we recognise, so we are not able to refund it. Sometimes someone you know "
    "may have used the card without you realising. If you have anything we haven't "
    "seen, please send it within 14 days. If you're unhappy, you can ask the Financial Ombudsman Service to review "
    "this for free.\n\nYours sincerely,\nCard Disputes Team\nFriendly Bank"))
ACCUSING_DECLINE = Letter(subject="Your claim", body=GOOD_DECLINE.body.replace(
    "Our records show", "We believe a family member made this purchase. Our records show"))


@pytest.mark.parametrize("decision, recommendation, expected", [
    ("approve", "decline_claim", "decline_claim"),
    ("Approved", "file_chargeback", "file_chargeback"),
    ("override:refund_customer", "decline_claim", "refund_customer"),
    ("override: file_chargeback", "decline_claim", "file_chargeback"),
    ("override:make_it_up", "decline_claim", "manual_review"),
    ("", None, "manual_review"),
])
def test_resolve_outcome(decision, recommendation, expected):
    assert resolve_outcome(make_state(decision=decision, recommendation=recommendation)) == expected


def test_vulnerability_from_profile_signals_or_level():
    assert cl.is_vulnerable(make_state(customer={"name": "A B", "vulnerable": True}))
    assert cl.is_vulnerable(make_state(vulnerable_signals=["I'm really struggling"]))
    assert cl.is_vulnerable(make_state(vulnerability_level="medium"))
    assert not cl.is_vulnerable(make_state(vulnerability_level="none"))


@pytest.mark.parametrize("action", ["refund_customer", "file_chargeback", "decline_claim", "manual_review"])
@pytest.mark.parametrize("vulnerable", [False, True])
def test_template_letter_passes_checks(action, vulnerable):
    state = make_state()
    letter = template_letter(action, state, vulnerable)
    assert check_letter(letter.body, action, state, vulnerable, non_accusatory=True) == []


def test_decline_without_ombudsman_fails():
    body = GOOD_DECLINE.body.replace("you can ask the Financial Ombudsman Service to review this for free", "contact us")
    assert any("Ombudsman" in p for p in check_letter(body, "decline_claim", make_state(), False, True))


def test_accusation_fails():
    assert any("accuses" in p for p in check_letter(ACCUSING_DECLINE.body, "decline_claim", make_state(), False, True))


def test_refund_promise_in_decline_fails():
    body = GOOD_DECLINE.body + "\nWe have refunded you as a goodwill gesture."
    assert any("refund" in p for p in check_letter(body, "decline_claim", make_state(), False, True))


def test_jargon_fails():
    body = GOOD_DECLINE.body + "\nThe payment passed 3-D Secure."
    assert any("jargon" in p for p in check_letter(body, "decline_claim", make_state(), False, True))


def test_vulnerable_needs_support_line():
    problems = check_letter(GOOD_DECLINE.body, "decline_claim", make_state(), vulnerable=True, non_accusatory=True)
    assert any(cl.SUPPORT_LINE in p for p in problems)


def test_amount_accepted_without_pence():
    state = make_state(transaction={**TX, "amount": 820.0, "merchant": "HomeStyle Furniture"})
    body = "Dear Tom, we have asked HomeStyle Furniture to return the £820."
    assert not any("amount" in p for p in check_letter(body, "file_chargeback", state, False, False))


def test_good_letter_first_time(fake_llm):
    writer = fake_llm(GOOD_DECLINE)
    out = write_customer_letter(make_state())
    assert out["letter_quality"] == {"outcome": "decline_claim", "letter_type": "friendly_fraud_decline",
                                     "vulnerable": False, "non_accusatory": True, "upset": False,
                                     "attempts": 1, "source": "llm", "last_problems": []}
    assert out["customer_letter"].startswith("Subject: About your PixelGames Store payment")
    assert "Never suggest the customer is lying" in writer.prompts[0]
    assert "Financial Ombudsman Service" in writer.prompts[0]


def test_bad_letter_is_rewritten_with_feedback(fake_llm):
    writer = fake_llm(ACCUSING_DECLINE, GOOD_DECLINE)
    out = write_customer_letter(make_state())
    assert out["letter_quality"]["attempts"] == 2 and out["letter_quality"]["source"] == "llm"
    assert "previous draft had these problems" in writer.prompts[1]
    assert "family member" not in out["customer_letter"]


def test_falls_back_to_template_after_two_failures(fake_llm):
    fake_llm(ACCUSING_DECLINE, ACCUSING_DECLINE)
    out = write_customer_letter(make_state())
    assert out["letter_quality"]["source"] == "template_fallback"
    assert out["letter_quality"]["last_problems"]
    assert "Financial Ombudsman Service" in out["customer_letter"]


def test_model_error_falls_back_to_template(fake_llm):
    fake_llm(RuntimeError("gateway timeout"), RuntimeError("gateway timeout"))
    out = write_customer_letter(make_state())
    assert out["letter_quality"]["source"] == "template_fallback"
    assert "Dear Tom Hughes" in out["customer_letter"]


def test_vulnerable_customer_prompt_and_steps(fake_llm):
    state = make_state(customer={"name": "Amara Okafor", "vulnerable": True}, route="merchant",
                       reason_code="goods_not_received", recommendation="file_chargeback",
                       transaction={**TX, "merchant": "HomeStyle Furniture", "amount": 820.0})
    writer = fake_llm(RuntimeError("x"), RuntimeError("x"))
    out = write_customer_letter(state)
    assert "especially gentle" in writer.prompts[0]
    assert cl.SUPPORT_LINE in out["customer_letter"] and "28 days" not in out["customer_letter"]
    assert out["letter_quality"]["vulnerable"] is True


@pytest.mark.parametrize("ending", [
    "Yours sincerely,\nCard Disputes Team,\nFriendly Bank",
    "Yours sincerely, Card Disputes Team, Friendly Bank.",
    "Yours sincerely,\nCard Disputes Team\nFriendly Bank\n\n",
])
def test_sign_off_is_made_consistent(fake_llm, ending):
    draft = Letter(subject=GOOD_DECLINE.subject,
                   body=GOOD_DECLINE.body.replace("Yours sincerely,\nCard Disputes Team\nFriendly Bank", ending))
    writer = fake_llm(draft)
    out = write_customer_letter(make_state())
    assert out["letter_quality"]["source"] == "llm"
    assert out["customer_letter"].endswith("\n\nYours sincerely,\nCard Disputes Team\nFriendly Bank")
    assert "never 'I'" in writer.prompts[0]
    assert "sign-off on three lines" in writer.prompts[0]
