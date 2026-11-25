
import pytest

import utils.customer_letter as cl
from evals.test_sets import check_letter as asia_check_letter, letter_cases
from tests.letter_cases import state_for_case
from tests.test_customer_letter import FakeWriter, make_state

CASES = letter_cases()
EXPECTED = {
    "LTR-01": ("file_chargeback", "chargeback"),
    "LTR-02": ("file_chargeback", "chargeback"),
    "LTR-03": ("decline_claim", "friendly_fraud_decline"),
    "LTR-04": ("decline_claim", "friendly_fraud_decline"),
    "LTR-05": ("file_chargeback", "chargeback"),
    "LTR-06": ("needs_more_info", "needs_more_info"),
    "LTR-07": ("file_chargeback", "chargeback"),
    "LTR-08": ("fast_lane_holding", "fast_lane_holding"),
}


def test_all_eight_cases_are_covered():
    assert sorted(c["letter_id"] for c in CASES) == sorted(EXPECTED)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["letter_id"])
def test_case_gets_the_right_letter_type(case):
    state = state_for_case(case)
    action = cl.resolve_outcome(state)
    assert (action, cl.letter_type(action, cl.letter_tone(state))) == EXPECTED[case["letter_id"]]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["letter_id"])
def test_fixed_letter_passes_asias_rules_and_ours(case):
    state = state_for_case(case)
    action, tone = cl.resolve_outcome(state), cl.letter_tone(state)
    letter = cl.template_letter(action, state, tone["vulnerable"])
    assert asia_check_letter(letter.body, case) == []
    assert cl.check_letter(letter.body, action, state, tone["vulnerable"], tone["non_accusatory"], tone["upset"]) == []


@pytest.mark.parametrize("overrides, expected", [
    ({"vulnerability": {"level": "high"}, "decision": "approve"}, "fast_lane_holding"),
    ({"route": "fast_lane", "decision": "", "recommendation": None}, "fast_lane_holding"),
    ({"decision": "needs_more_info"}, "needs_more_info"),
    ({"decision": "request_more_info"}, "needs_more_info"),
    ({"decision": "override:needs_more_info"}, "needs_more_info"),
    ({"vulnerability": {"level": "medium"}, "decision": "approve"}, "decline_claim"),
])
def test_resolve_outcome_new_types(overrides, expected):
    assert cl.resolve_outcome(make_state(**overrides)) == expected


def test_fast_lane_never_calls_the_llm(monkeypatch):
    writer = FakeWriter([])
    monkeypatch.setattr(cl, "init_chat_model", lambda _m: writer)
    out = cl.write_customer_letter(make_state(vulnerability={"level": "high"}))
    assert writer.prompts == []
    assert out["letter_quality"]["source"] == "fixed_template"
    assert out["letter_quality"]["letter_type"] == "fast_lane_holding"
    letter = out["customer_letter"]
    assert cl.SAMARITANS in letter and "999" in letter and cl.SUPPORT_LINE in letter
    assert "declined" not in letter.lower() and "refund" not in letter.lower()


GENTLE = ("Dear Tom, about the £89.99 payment to PixelGames Store. Our records show earlier payments to PixelGames "
          "Store from a device used with your card before. Someone you know may have used it. We are not able to "
          "refund it. You can ask the Financial Ombudsman Service to review this.")


def test_gentle_possibility_is_allowed():
    assert cl.check_letter(GENTLE, "decline_claim", make_state(), False, True) == []


@pytest.mark.parametrize("phrase", ["A family member made this payment.", "Your son used your card.",
                                    "We don't believe you."])
def test_stating_or_naming_someone_fails(phrase):
    problems = cl.check_letter(GENTLE + " " + phrase, "decline_claim", make_state(), False, True)
    assert any("accuses" in p for p in problems)


def test_friendly_fraud_decline_needs_the_possibility():
    body = GENTLE.replace(" Someone you know may have used it.", "")
    assert any("household" in p for p in cl.check_letter(body, "decline_claim", make_state(), False, True))


def test_more_info_letter_must_not_say_declined():
    state = make_state(reason_code="cancelled_recurring", route="merchant", decision="needs_more_info")
    body = "Dear Tom, your £89.99 PixelGames Store claim is declined. Please send your email within 14 days."
    assert any("declined" in p for p in cl.check_letter(body, "needs_more_info", state, False, False))


def test_fraud_letter_needs_the_scam_reminder():
    state = make_state(route="fraud", recommendation="file_chargeback")
    body = "Dear Tom, we have asked PixelGames Store to return the £89.99. They have up to 45 days."
    assert any("scam" in p for p in cl.check_letter(body, "file_chargeback", state, False, True))
    assert not any("scam" in p for p in cl.check_letter(body + " We will never ask for your PIN.",
                                                        "file_chargeback", state, False, True))


def test_upset_customer_gets_acknowledged():
    state = make_state(complaint={"text": "I'm absolutely furious! Sort this out."}, route="merchant",
                       reason_code="cancelled_recurring")
    assert cl.letter_tone(state)["upset"] is True
    body = "Dear Tom, we have asked PixelGames Store to return the £89.99."
    assert any("upset" in p for p in cl.check_letter(body, "file_chargeback", state, False, False, upset=True))
    assert not any("upset" in p for p in cl.check_letter("We understand how frustrating this is. " + body,
                                                         "file_chargeback", state, False, False, upset=True))


def test_anger_alone_is_not_vulnerability():
    state = make_state(complaint={"text": "I'm absolutely furious!"})
    assert cl.letter_tone(state) == {"vulnerable": False, "non_accusatory": True, "upset": True}
