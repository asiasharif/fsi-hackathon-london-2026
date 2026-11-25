"""Nodes for the card dispute graph.

Flow: load_case -> vulnerability_check -+-> high risk: FAST LANE straight to human_approval
                                        +-> classify_dispute -> triage -> [fraud | merchant | friendly_fraud] specialist
      -> draft_evidence_pack <-> quality_review (max 2 rewrites) -> human_approval -> write_customer_letter -> finalise

write_customer_letter lives in utils/customer_letter.py.
"""

import re
from datetime import date, timedelta
from typing import Literal

from langchain.chat_models import init_chat_model
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from tools.cases import get_complaint, get_customer, get_dispute_history, get_merchant_history, get_transaction
from tools.memory import memory_summary, recall_disputes, record_dispute
from utils.models import model
from utils.state import FRAUD_CODES, MyAgentContext, MyAgentState, ReasonCode, SendBackTo, VulnerabilityLevel, VulnerabilityType


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


# ---------------------------------------------------------------- 1b. vulnerability check (AI + rules)
LEVELS = ["none", "low", "medium", "high"]

# Safety net: any of these phrases means high risk, whatever the AI says. Missing a high-risk customer is the worst
# mistake the agent can make, so the rules can only raise the level, never lower it.
CRISIS_PATTERNS = [
    r"can'?t cope", r"cannot cope", r"no way out", r"(don'?t|do not) see the point", r"no point in (anything|living)",
    r"end it all", r"kill myself", r"suicid", r"self[- ]harm", r"hurt myself", r"not worth living",
    r"better off without me", r"(can'?t|cannot) go on",
]
RECENT_DISPUTES_DAYS, RECENT_DISPUTES_LIMIT = 90, 3  # many disputes in a short time is a vulnerability signal


class VulnerabilityAssessment(BaseModel):
    level: VulnerabilityLevel = Field(description="none, low, medium or high (see the guide)")
    types: list[VulnerabilityType] = Field(description="FCA drivers of vulnerability that apply. Empty if none.")
    reasons: list[str] = Field(description="Short quotes or facts that justify the level. Empty if none.")


def vulnerability_rules(case: dict) -> tuple[str, list[str], list[str]]:
    """Deterministic signals: crisis phrases, the customer's profile and recent dispute history."""
    text = case["complaint"]["text"].lower()
    level, types, reasons = "none", [], []
    crisis = [p for p in CRISIS_PATTERNS if re.search(p, text)]
    if crisis:
        level, types = "high", ["health"]
        reasons.append("Crisis language in the complaint (rule)")
    if case["customer"].get("vulnerable"):
        level = max(level, "low", key=LEVELS.index)
        reasons.append("Customer is already marked vulnerable on their profile")
    cutoff = (date.today() - timedelta(days=RECENT_DISPUTES_DAYS)).isoformat()
    recent = [d for d in case["dispute_history"] if d.get("opened", "") >= cutoff]
    if len(recent) >= RECENT_DISPUTES_LIMIT:
        level = max(level, "low", key=LEVELS.index)
        reasons.append(f"{len(recent)} disputes in the last {RECENT_DISPUTES_DAYS} days")
    return level, types, reasons


def vulnerability_check(state: MyAgentState) -> dict:
    prompt = f"""You check whether a UK bank customer raising a card dispute may be vulnerable, following the FCA's
guidance on the fair treatment of vulnerable customers (Consumer Duty).

Types (FCA drivers): health (physical or mental illness, distress), life_event (bereavement, new baby, moving house,
job loss, relationship breakdown), low_resilience (struggling with money, can't afford the loss),
low_capability (age, confusion about payments or technology, being scammed, poor English).

Level guide:
- high: crisis. Hopelessness, can't cope, self-harm or suicidal thoughts, severe distress. Needs a human now.
- medium: clear, serious vulnerability, e.g. "I'm really struggling", elderly and confused, scam victim.
- low: a milder signal, e.g. "money's a bit tight", just moved house, new baby and no sleep.
- none: no signal. Anger or frustration alone ("I'm furious!", "sort this out") is NOT vulnerability.
  Disputing a payment is NOT vulnerability either: "wasn't me", "someone used my card", "I don't recognise this
  payment" or "I don't understand this charge" are normal dispute wording. Being tricked by a scammer (e.g. a caller
  pretending to fix their computer) IS vulnerability (low_capability). Only flag what the customer says about
  themselves or their situation.

Complaint: {state["complaint"]["text"]}
Customer profile: {state["customer"]}
Number of past disputes: {len(state["dispute_history"])}"""
    ai = llm().with_structured_output(VulnerabilityAssessment, method="json_schema").invoke(prompt)
    rule_level, rule_types, rule_reasons = vulnerability_rules(state)
    level = max(ai.level, rule_level, key=LEVELS.index)
    vulnerability = {
        "vulnerable": level != "none",
        "level": level,
        "types": list(dict.fromkeys(ai.types + rule_types)),
        "reasons": ai.reasons + rule_reasons,
    }
    update = {"vulnerability": vulnerability}
    if level == "high":
        update |= {"route": "fast_lane", "route_reasons": ["High-risk vulnerable customer: fast lane to a human"]}
    return update


def route_after_vulnerability(state: MyAgentState) -> Literal["classify_dispute", "human_approval"]:
    return "human_approval" if state["vulnerability"]["level"] == "high" else "classify_dispute"


def _vulnerability_text(state: MyAgentState) -> str:
    v = state.get("vulnerability") or {}
    if not v.get("vulnerable"):
        return "None found"
    return f"{v['level']} ({', '.join(v['types']) or 'unspecified'}): {'; '.join(v['reasons'])}"


# ---------------------------------------------------------------- 2. classify (owner: graph; scored by evals)
class Classification(BaseModel):
    reason_code: ReasonCode = Field(description="The card scheme reason code that best fits the complaint")
    vulnerable_signals: list[str] = Field(description="Quotes suggesting the customer may be vulnerable (distress, financial hardship, illness). Empty if none.")


def classify_dispute(state: MyAgentState) -> dict:
    prompt = f"""Classify this card dispute complaint.

Complaint: {state["complaint"]["text"]}
Transaction: {state["transaction"]}{_review_feedback_for(state, "classify_dispute")}"""
    result = llm().with_structured_output(Classification, method="json_schema").invoke(prompt)
    return result.model_dump()


# ---------------------------------------------------------------- 3. triage (deterministic, so it is easy to test)
def triage(state: MyAgentState) -> dict:
    if state["reason_code"] not in FRAUD_CODES:
        return {"route": "merchant", "route_reasons": [f"Reason code {state['reason_code']} is a merchant dispute"]}

    tx = state["transaction"]
    reasons = []
    # An earlier purchase only suggests the customer shops there if they never disputed it.
    disputed = {d.get("transaction_id") for d in state["dispute_history"]}
    undisputed = [t for t in state["merchant_history"] if t["transaction_id"] not in disputed]
    if undisputed:
        ids = ", ".join(t["transaction_id"] for t in undisputed)
        reasons.append(f"{len(undisputed)} earlier purchase(s) at {tx['merchant']} ({ids}), "
                       "none of them in the customer's dispute history")
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
Customer vulnerability: {_vulnerability_text(state)}

Vulnerability changes how carefully we treat the customer, not whether they are right. Assess the claim and recommend an action. Use only the facts above.{_review_feedback_for(state, "specialist")}"""
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
    rewrite = ""
    if state.get("review_result") == "fail":
        rewrite = f"""
A quality reviewer rejected your previous draft. Fix every issue below and rewrite the whole pack.
Reviewer feedback: {state["review_feedback"]}
Previous draft:
{state["evidence_pack"]}
"""
    prompt = f"""Draft a chargeback evidence pack in markdown with these sections:
Summary, Reason code, Transaction details, Evidence, Customer history, Vulnerability, Recommendation,
Points for the reviewer (anything uncertain or missing that the human approving this should check).
{rewrite}
Customer: {state["customer"]}
Complaint: {state["complaint"]["text"]}
Reason code: {state["reason_code"]}
Transaction: {state["transaction"]}
Route: {state["route"]} ({state["route_reasons"]})
Specialist assessment: {state["assessment"]}
Recommendation: {state["recommendation"]}
Vulnerability check: {_vulnerability_text(state)}
Classifier's vulnerability signals: {state["vulnerable_signals"] or "None"}

Use only these facts."""
    return {"evidence_pack": llm().invoke(prompt).content}


# ---------------------------------------------------------------- 5b. quality review (owner: Pradeep)
MAX_REVIEW_RETRIES = 2  # send-backs allowed; after that the case goes to the human either way


class QualityReview(BaseModel):
    issues: list[str] = Field(description="Each checklist failure, quoting the problem text. Empty if it passes.")
    verdict: Literal["pass", "fail"] = Field(description="pass only if every checklist item passes")
    send_back_to: SendBackTo = Field(description="Where the case must go next (see the routing rules)")
    feedback: str = Field(description="Concrete instructions for whoever fixes it. Empty if it passes.")


def review_pack(case: dict, evidence_pack: str) -> QualityReview:
    """Check an evidence pack against the raw case data. `case` is the output of load_case."""
    prompt = f"""You are the quality reviewer for a UK bank's card disputes team. Check this evidence pack
before a member of staff uses it to approve or override the recommendation. Judge it only against the source data.

Checklist (the pack fails if ANY item fails):
1. Grounded: every fact (amounts, dates, merchant, device, 3-D Secure, history) matches the source data.
2. Nothing invented: no evidence, events, confirmations or documents that are not in the source data.
3. Reason code fits: the reason code matches what the customer actually complains about.
4. Recommendation matches the evidence: e.g. a "not me" claim with several signs that the customer made the payment
   (earlier purchases there, known device + 3-D Secure, lost fraud claims) should not be a chargeback.
5. Complete: it has Summary, Reason code, Transaction details, Evidence, Customer history, Vulnerability and
   Recommendation sections, each with real content.
6. Vulnerability handled: if the complaint or profile shows vulnerability (age, illness, distress, hardship, scam,
   confusion), the Vulnerability section says so and the case is handled with care, not marked "none".
7. No accusing tone: never says or implies the customer is lying; friendly fraud is often a household member.
8. Decision-ready: a human could approve or override from this pack alone.
Only fail a pack for problems that could mislead the human or harm the customer. These are NOT failures:
style or wording (e.g. "File a chargeback" vs file_chargeback), reasonable judgements drawn from the data
(e.g. rating a vulnerable customer's level as medium), and leaving out data that is empty or irrelevant.

Routing rules for send_back_to:
- pass -> human_approval
- wrong reason code (item 3) -> classify_dispute
- recommendation does not follow from the evidence (item 4) -> specialist
- write-up problems: wrong or invented facts, missing sections, vulnerability ignored, accusing tone -> draft_evidence_pack
- evidence the bank does not have and a rewrite cannot fix -> human_approval

Source data:
Customer: {case["customer"]}
Complaint: {case["complaint"]["text"]}
Transaction: {case["transaction"]}
Earlier purchases at this merchant: {case["merchant_history"] or "None"}
Customer's past disputes: {case["dispute_history"] or "None"}

The agent's own findings. The pack may quote or refer to these; that is not invented. Still fail the pack if a
finding is stated as fact but contradicts the source data above:
Vulnerability check: {_vulnerability_text(case) if case.get("vulnerability") else "Not provided"}
Classifier's reason code: {case.get("reason_code", "Not provided")}
Classifier's vulnerability signals: {case.get("vulnerable_signals", "Not provided") or "None"}
Triage route and signals: {case.get("route", "Not provided")} {case.get("route_reasons", "")}
Specialist assessment: {case.get("assessment", "Not provided")}
Specialist recommendation: {case.get("recommendation", "Not provided")}

Evidence pack:
{evidence_pack}"""
    return llm().with_structured_output(QualityReview, method="json_schema").invoke(prompt)


def quality_review(state: MyAgentState) -> dict:
    result = review_pack(state, state["evidence_pack"])
    retries = state.get("retry_count", 0)
    target, feedback = result.send_back_to, result.feedback
    if result.verdict == "pass":
        target = "human_approval"
    elif target != "human_approval" and retries >= MAX_REVIEW_RETRIES:
        target = "human_approval"
        feedback += f" (Still failing after {MAX_REVIEW_RETRIES} retries: the human must check this.)"
    if result.verdict == "fail" and result.issues:
        feedback = "Issues: " + "; ".join(result.issues) + ". " + feedback
    return {
        "review_result": result.verdict,
        "review_feedback": feedback,
        "send_back_to": target,
        "retry_count": retries + (target != "human_approval"),
    }


def route_after_review(state: MyAgentState) -> Literal[
    "human_approval", "draft_evidence_pack", "classify_dispute",
    "fraud_specialist", "merchant_specialist", "friendly_fraud_specialist",
]:
    if state["send_back_to"] == "specialist":
        return route_to_specialist(state)
    return state["send_back_to"]


def _review_feedback_for(state: MyAgentState, step: str) -> str:
    """The reviewer's feedback, if the reviewer sent the case back to this step."""
    if state.get("review_result") == "fail" and state.get("send_back_to") == step:
        return f"\n\nA quality reviewer sent this back to you. Take this into account: {state['review_feedback']}"
    return ""


# ---------------------------------------------------------------- 6. human approval + memory (owner: memory/HITL)
def human_approval(state: MyAgentState, runtime: Runtime[MyAgentContext]) -> dict:
    vulnerability = state.get("vulnerability") or {}
    memory = memory_summary(state.get("dispute_history") or [],
                            recall_disputes(runtime.store, state["complaint"]["customer_id"]))
    if state.get("route") == "fast_lane":
        tx = state["transaction"]
        answer = interrupt({
            "FAST_LANE": "High-risk vulnerable customer. Contact them now; the investigation is on hold.",
            "vulnerability": vulnerability,
            "memory": memory,
            "complaint_id": state["complaint_id"],
            "customer": state["customer"].get("name"),
            "summary": f"Disputes {tx.get('currency', '')} {tx.get('amount')} to {tx.get('merchant')} on "
                       f"{tx.get('timestamp', '')}. Customer wrote: \"{state['complaint']['text']}\"",
            "question": "Reply with {'decision': 'contacted' | 'escalated', 'notes': ...}",
        })
        return {"decision": answer["decision"], "reviewer_notes": answer.get("notes", "")}

    answer = interrupt({
        "vulnerability": vulnerability,
        "memory": memory,
        "complaint_id": state["complaint_id"],
        "recommendation": state["recommendation"],
        "vulnerable_customer": bool(vulnerability.get("vulnerable") or state["vulnerable_signals"]
                                    or state["customer"].get("vulnerable")),
        "evidence_pack": state["evidence_pack"],
        "quality_review": {
            "result": state.get("review_result"),
            "retries": state.get("retry_count", 0),
            "outstanding_issues": state.get("review_feedback", "") if state.get("review_result") == "fail" else "",
        },
        "question": "Approve the recommendation? Reply with {'decision': 'approve' | 'override:<action>', 'notes': ...}",
    })
    return {"decision": answer["decision"], "reviewer_notes": answer.get("notes", "")}


def finalise(state: MyAgentState, runtime: Runtime[MyAgentContext]) -> dict:
    record_dispute(
        runtime.store,
        customer_id=state["complaint"]["customer_id"],
        complaint_id=state["complaint_id"],
        transaction_id=state["transaction"]["transaction_id"],
        merchant=state["transaction"]["merchant"],
        reason_code=state.get("reason_code", "unclassified"),  # the fast lane skips classification
        outcome="pending",
        decision=state["decision"],
        notes=f"{state.get('recommendation') or 'fast_lane'}. {state['reviewer_notes']}".strip(),
    )
    return {}
