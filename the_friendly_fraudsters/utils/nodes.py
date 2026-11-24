"""Nodes for the card dispute graph.

Flow: load_case -> classify_dispute -> triage -> [fraud | merchant | friendly_fraud] specialist
      -> draft_evidence_pack -> human_approval -> finalise
"""

from typing import Literal

from langchain.chat_models import init_chat_model
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from tools.cases import get_complaint, get_customer, get_dispute_history, get_merchant_history, get_transaction
from tools.memory import record_dispute
from utils.models import model
from utils.state import FRAUD_CODES, MyAgentState, ReasonCode


def llm():
    return init_chat_model(model)


# ---------------------------------------------------------------- 1. load the case (owner: graph)
def load_case(state: MyAgentState) -> dict:
    complaint = get_complaint(state["complaint_id"])
    tx = get_transaction(complaint["transaction_id"])
    return {
        "complaint": complaint,
        "customer": get_customer(complaint["customer_id"]),
        "transaction": tx,
        "merchant_history": get_merchant_history(complaint["customer_id"], tx.get("merchant", ""), tx.get("transaction_id", "")),
        "dispute_history": get_dispute_history(complaint["customer_id"]),
    }


# ---------------------------------------------------------------- 2. classify (owner: graph; scored by evals)
class Classification(BaseModel):
    reason_code: ReasonCode = Field(description="The card scheme reason code that best fits the complaint")
    vulnerable_signals: list[str] = Field(description="Quotes suggesting the customer may be vulnerable (distress, financial hardship, illness). Empty if none.")


def classify_dispute(state: MyAgentState) -> dict:
    prompt = f"""Classify this card dispute complaint.

Complaint: {state["complaint"]["text"]}
Transaction: {state["transaction"]}"""
    result = llm().with_structured_output(Classification, method="json_schema").invoke(prompt)
    return result.model_dump()


# ---------------------------------------------------------------- 3. triage (deterministic, so it is easy to test)
def triage(state: MyAgentState) -> dict:
    if state["reason_code"] not in FRAUD_CODES:
        return {"route": "merchant", "route_reasons": [f"Reason code {state['reason_code']} is a merchant dispute"]}

    tx = state["transaction"]
    reasons = []
    if state["merchant_history"]:
        reasons.append(f"{len(state['merchant_history'])} earlier undisputed purchase(s) at {tx['merchant']}")
    if tx.get("device_known") and tx.get("3ds_passed"):
        reasons.append("Made on the customer's known device and passed 3-D Secure")
    lost_fraud_claims = [d for d in state["dispute_history"] if d["reason_code"] in FRAUD_CODES and d["outcome"] == "lost"]
    if lost_fraud_claims:
        reasons.append(f"{len(lost_fraud_claims)} earlier fraud claim(s) lost")

    if len(reasons) >= 2:
        return {"route": "friendly_fraud", "route_reasons": reasons}
    return {"route": "fraud", "route_reasons": reasons or ["No signals that the customer made the payment"]}


def route_to_specialist(state: MyAgentState) -> Literal["fraud_specialist", "merchant_specialist", "friendly_fraud_specialist"]:
    return f"{state['route']}_specialist"


# ---------------------------------------------------------------- 4. specialists (owner: specialists)
class Assessment(BaseModel):
    assessment: str = Field(description="3-5 sentences of reasoning, citing the evidence")
    recommendation: Literal["file_chargeback", "refund_customer", "decline_claim"]


def _specialist(state: MyAgentState, role: str) -> dict:
    prompt = f"""You are a {role} at a UK bank's card disputes team.

Complaint: {state["complaint"]["text"]}
Reason code: {state["reason_code"]}
Transaction: {state["transaction"]}
Earlier purchases at this merchant: {state["merchant_history"] or "None"}
Customer's past disputes: {state["dispute_history"] or "None"}
Triage signals: {state["route_reasons"]}

Assess the claim and recommend an action. Use only the facts above."""
    return llm().with_structured_output(Assessment, method="json_schema").invoke(prompt).model_dump()


def fraud_specialist(state: MyAgentState) -> dict:
    # TODO: add fraud-specific checks (geo mismatch, unknown device, failed 3DS, odd hour)
    return _specialist(state, "fraud investigator")


def merchant_specialist(state: MyAgentState) -> dict:
    # TODO: check cancellation dates, delivery windows, duplicate amounts
    return _specialist(state, "merchant dispute specialist")


def friendly_fraud_specialist(state: MyAgentState) -> dict:
    # TODO: be careful and fair: friendly fraud is often a family member, not deliberate
    return _specialist(state, "first-party (friendly) fraud analyst")


# ---------------------------------------------------------------- 5. evidence pack (owner: specialists)
def draft_evidence_pack(state: MyAgentState) -> dict:
    prompt = f"""Draft a chargeback evidence pack in markdown with these sections:
Summary, Reason code, Transaction details, Evidence, Customer history, Recommendation.

Customer: {state["customer"]}
Complaint: {state["complaint"]["text"]}
Reason code: {state["reason_code"]}
Transaction: {state["transaction"]}
Route: {state["route"]} ({state["route_reasons"]})
Specialist assessment: {state["assessment"]}
Recommendation: {state["recommendation"]}
Vulnerability signals: {state["vulnerable_signals"] or "None"}

Use only these facts."""
    return {"evidence_pack": llm().invoke(prompt).content}


# ---------------------------------------------------------------- 6. human approval + memory (owner: memory/HITL)
def human_approval(state: MyAgentState) -> dict:
    answer = interrupt({
        "complaint_id": state["complaint_id"],
        "recommendation": state["recommendation"],
        "vulnerable_customer": bool(state["vulnerable_signals"] or state["customer"].get("vulnerable")),
        "evidence_pack": state["evidence_pack"],
        "question": "Approve the recommendation? Reply with {'decision': 'approve' | 'override:<action>', 'notes': ...}",
    })
    return {"decision": answer["decision"], "reviewer_notes": answer.get("notes", "")}


def finalise(state: MyAgentState) -> dict:
    record_dispute(
        customer_id=state["complaint"]["customer_id"],
        transaction_id=state["transaction"]["transaction_id"],
        merchant=state["transaction"]["merchant"],
        reason_code=state["reason_code"],
        outcome="pending",
        notes=f"{state['recommendation']} ({state['decision']}). {state['reviewer_notes']}".strip(),
    )
    return {}
