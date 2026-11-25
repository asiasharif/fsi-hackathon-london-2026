"""The state schema: the fields passed between steps. Agree this as a team in the first hour."""

from typing import Literal

from typing_extensions import TypedDict

ReasonCode = Literal[
    "fraud_card_not_present",   # "I didn't make this online payment"
    "fraud_card_present",       # "my card was stolen and used in a shop"
    "goods_not_received",
    "not_as_described",
    "duplicate_charge",
    "cancelled_recurring",      # charged after cancelling a subscription
    "incorrect_amount",
]
FRAUD_CODES = {"fraud_card_not_present", "fraud_card_present"}

Route = Literal["fraud", "merchant", "friendly_fraud"]


class MyAgentContext(TypedDict):
    agent_model: str


class MyAgentInput(TypedDict):
    complaint_id: str           # for example "CMP-001"


class MyAgentState(MyAgentInput):
    # set by load_case
    complaint: dict
    customer: dict
    transaction: dict
    merchant_history: list[dict]
    dispute_history: list[dict]
    # set by classify_dispute
    reason_code: ReasonCode
    vulnerable_signals: list[str]
    # set by triage
    route: Route
    route_reasons: list[str]
    # set by the specialist
    assessment: str
    recommendation: Literal["file_chargeback", "refund_customer", "decline_claim"]
    # set by draft_evidence_pack
    evidence_pack: str
    # set by human_approval
    decision: str
    reviewer_notes: str
    # set by write_customer_letter (owner: customer communication)
    customer_letter: str        # "Subject: ...\n\n<letter body>", ready to send
    letter_quality: dict        # outcome, tone flags, attempts, "llm" or "template_fallback", any unresolved problems
