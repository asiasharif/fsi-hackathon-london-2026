"""Nodes for the card dispute graph.

Flow: load_case -> vulnerability_check -+-> high risk: FAST LANE straight to human_approval
                                        +-> classify_dispute -> triage -> [fraud | merchant | friendly_fraud] specialist
      -> draft_evidence_pack <-> quality_review (max 2 rewrites) -> human_approval -> write_customer_letter -> finalise

write_customer_letter lives in utils/customer_letter.py.
"""

import re
from datetime import date, datetime, timedelta
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
    prompt = f"""Classify this card dispute complaint with the reason code that fits the customer's main claim.

Reason codes:
- fraud_card_not_present: the customer says they did not make or authorise an online, phone or in-app payment.
- fraud_card_present: the customer says they did not make an in-person payment (card lost, stolen or cloned).
- goods_not_received: they paid, but the goods or service never arrived or never happened.
- not_as_described: they received it, but it was faulty, damaged, fake or not what was advertised.
- duplicate_charge: the same purchase was charged more than once.
- cancelled_recurring: they agree they had the subscription, but were charged after cancelling or stopping it.
- incorrect_amount: they made the purchase but were charged a different amount than agreed.

Deciding rule: if the customer says they did not make the payment ("I didn't make it", "wasn't me", "not me"), it is
a fraud code, even if they also mention a subscription they cancelled. cancelled_recurring is for customers who
accept the charge is from a subscription they had and say they stopped it.

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

    # Hard block: an unknown device or a failed 3-D Secure points to a third party, so other signals (earlier
    # purchases, lost claims) can never make this friendly fraud.
    blockers = []
    if not tx.get("device_known"):
        blockers.append("Made on a device the customer has not used before")
    if not tx.get("3ds_passed"):
        blockers.append("Failed 3-D Secure")
    if blockers:
        return {"route": "fraud", "route_reasons": blockers + [f"Friendly fraud ruled out despite: {r}" for r in reasons]}

    if len(reasons) >= 2:
        return {"route": "friendly_fraud", "route_reasons": reasons}
    return {"route": "fraud", "route_reasons": reasons or ["No signals that the customer made the payment"]}


def route_to_specialist(state: MyAgentState) -> Literal["fraud_specialist", "merchant_specialist", "friendly_fraud_specialist"]:
    return f"{state['route']}_specialist"


# ---------------------------------------------------------------- 4. specialists (owner: specialists)
#
# Each specialist gets:
#   - a list of FACTS worked out in plain Python first (country, device, 3-D Secure, duplicates...), so the
#     LLM reasons over checked facts instead of spotting them itself
#   - its own INSTRUCTIONS (what to look for, and when to pick each recommendation)
#   - a VULNERABILITY note, so a customer who may not cope with the loss is handled with care


class Assessment(BaseModel):
    assessment: str = Field(description="3-5 sentences of reasoning, citing the evidence")
    recommendation: Literal["file_chargeback", "refund_customer", "decline_claim"]


def _when(timestamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return None


def _vulnerability_note(state: MyAgentState) -> str:
    """The vulnerability check's result (see vulnerability_check), plus anything the classifier noticed."""
    note = _vulnerability_text(state)
    if state.get("vulnerable_signals"):
        note += f". The classifier also noticed: {'; '.join(state['vulnerable_signals'])}"
    if note == "None found":
        return "None found."
    return (
        note + ".\n"
        "Vulnerability changes how carefully we treat the customer, not whether they are right: base the "
        "recommendation on the evidence. But if they may not be able to afford the loss, say in your assessment "
        "that the bank should consider refunding them while the case is investigated, and keep the wording gentle."
    )


def _undisputed_purchases(state: MyAgentState) -> list[dict]:
    """Earlier purchases at this merchant that the customer never disputed (same rule as triage)."""
    disputed = {d.get("transaction_id") for d in state["dispute_history"]}
    return [t for t in state["merchant_history"] if t["transaction_id"] not in disputed]


def fraud_signals(state: MyAgentState) -> list[str]:
    """Signs that someone other than the customer made the payment (true fraud)."""
    tx, customer = state["transaction"], state["customer"]
    signs = []
    if tx.get("country") and customer.get("home_country") and tx["country"] != customer["home_country"]:
        signs.append(f"Made in {tx['country']}, but the customer lives in {customer['home_country']}")
    if tx.get("device_known") is False:
        signs.append("Made on a device the customer has not used before")
    if tx.get("3ds_passed") is False:
        signs.append("Failed the bank's 3-D Secure security check")
    when = _when(tx.get("timestamp"))
    if when and when.hour < 5:
        signs.append(f"Made at {when:%H:%M}, an unusual time")
    if not _undisputed_purchases(state):
        signs.append(f"No earlier undisputed purchases by this customer at {tx.get('merchant', 'this merchant')}")
    return signs


def customer_made_it_signals(state: MyAgentState) -> list[str]:
    """Signs that the customer (or someone in their household) made the payment."""
    tx = state["transaction"]
    signs = []
    if tx.get("device_known") and tx.get("3ds_passed"):
        signs.append("Made on the customer's own device and passed 3-D Secure")
    undisputed = _undisputed_purchases(state)
    if undisputed:
        signs.append(f"{len(undisputed)} earlier undisputed purchase(s) at {tx.get('merchant')}")
    return signs


def merchant_checks(state: MyAgentState) -> list[str]:
    """Facts about the payment that help judge a dispute with the shop."""
    tx = state["transaction"]
    checks = []
    when = _when(tx.get("timestamp"))
    same_amount = [t for t in state["merchant_history"] if abs(t.get("amount", 0) - tx.get("amount", 0)) < 0.01]
    for t in same_amount:
        other = _when(t.get("timestamp"))
        if when and other and abs((when - other).days) <= 3:
            checks.append(f"Possible duplicate: the same amount (£{tx['amount']:.2f}) was charged by {tx['merchant']} "
                          f"on {other:%d %b %Y at %H:%M}")
        elif other:
            checks.append(f"The same amount was also charged on {other:%d %b %Y}: this is a repeat (subscription-style) "
                          "payment, which fits a complaint about being charged after cancelling")
    says_twice = state.get("reason_code") == "duplicate_charge" or "twice" in state["complaint"]["text"].lower()
    if says_twice and not any("Possible duplicate" in c for c in checks):
        checks.append(f"The customer mentions being charged twice, but there is only one payment of this amount to "
                      f"{tx.get('merchant')} in the data, so a duplicate is not supported. Judge the claim on the "
                      "customer's other problem")
    if state["merchant_history"]:
        checks.append(f"{len(state['merchant_history'])} earlier payment(s) to {tx['merchant']} in the data")
    else:
        checks.append(f"No earlier payments to {tx.get('merchant')} in the data")
    if tx.get("device_known") and tx.get("3ds_passed"):
        checks.append("The customer made this payment themselves (own device, passed 3-D Secure), "
                      "so this is a dispute with the shop, not fraud")
    checks.append("The bank has no delivery, cancellation or usage records at this stage. That is normal and is NOT "
                  "a reason to decline: the merchant answers the chargeback with its own evidence")
    return checks


def _specialist(state: MyAgentState, role: str, instructions: str, facts_title: str, facts: list[str]) -> dict:
    facts_text = "\n".join(f"- {f}" for f in facts) or "- None found"
    prompt = f"""You are a {role} in a UK bank's card disputes team.

{instructions}

Complaint: {state["complaint"]["text"]}
Reason code: {state["reason_code"]}
Transaction: {state["transaction"]}
Customer: {state["customer"]}
Earlier purchases at this merchant: {state["merchant_history"] or "None"}
Customer's past disputes: {state["dispute_history"] or "None"}
Triage signals: {state["route_reasons"]}

{facts_title} (worked out from the data, so you can rely on them):
{facts_text}

Vulnerability: {_vulnerability_note(state)}

Write 3-5 sentences that cite the specific evidence above, then choose one recommendation.
Write for the bank's staff, about the customer in the third person ("the customer"), never addressed to the customer.
Use only the facts above. Never invent evidence, delivery records, cancellation proof or merchant responses.{_review_feedback_for(state, "specialist")}"""
    return llm().with_structured_output(Assessment, method="json_schema").invoke(prompt).model_dump()


FRAUD_INSTRUCTIONS = """The customer says they did not make this payment. Decide whether a criminal used their card.
Look for: a country different from the customer's home, a device they have not used, a failed 3-D Secure check,
an unusual hour, and no history with the merchant. Each one makes true fraud more likely.

How to choose:
- file_chargeback: the warning signs point to someone else using the card. The customer gets their money back
  and the bank claims it back from the merchant.
- decline_claim: only if the evidence clearly shows the customer made the payment. Say so neutrally.
- refund_customer: only if the bank itself made a mistake.
Remember the customer is legally entitled to a prompt refund for an unauthorised payment, so if in doubt,
favour the customer and flag the doubt for the human reviewer."""

MERCHANT_INSTRUCTIONS = """The customer made this payment but has a problem with the shop: for example the item never arrived,
the service was never provided, the item arrived damaged or not as described, they were charged after cancelling,
charged twice, or charged the wrong amount.

How to choose:
- file_chargeback: the complaint describes a believable problem with the merchant and nothing in the data
  contradicts it. This is the normal outcome for a genuine merchant dispute, even if the complaint is vague or
  hedged (for example "I never got to use it" or "I thought I'd cancelled that").
- decline_claim: only if the data actively contradicts the complaint. Missing proof is NOT a reason to decline:
  the bank never has delivery, cancellation or usage records at this stage, and the chargeback process is how the
  merchant gets to respond with its evidence.
- refund_customer: only if the bank itself made a mistake.
The customer's past disputes are background only. Earlier fraud claims, even lost ones, do not make a complaint
about a merchant less believable: judge this complaint on its own facts.
If the customer mentions more than one problem and the data rules one out (for example they think they were charged
twice but there is only one payment), say so, and base the recommendation on the problem that remains.
In the assessment, list what the customer should provide to support the claim (for example proof of cancellation,
photos of the damage, or the booking confirmation)."""


FRIENDLY_FRAUD_INSTRUCTIONS = """The customer says they did not make this payment, but triage found signs that the payment came from the
customer's own account activity. Be fair and careful: this is often a family member or someone in the household
using a saved card, or a purchase the customer has forgotten. It is rarely deliberate.

Never say or imply the customer is lying. Describe the evidence neutrally (for example "the payment was made from
a device the customer has used before"), and suggest the customer checks with people in their household and
with the merchant.

How to choose:
- decline_claim: two or more signs show the payment came from the customer's own device, account or history.
- file_chargeback: if signs point the other way (an unknown device, a failed 3-D Secure check, a different
  country), say the case looks like true fraud after all.
- refund_customer: only if the bank itself made a mistake."""


def fraud_specialist(state: MyAgentState) -> dict:
    return _specialist(state, "fraud investigator", FRAUD_INSTRUCTIONS,
                       "Warning signs of fraud", fraud_signals(state))


def merchant_specialist(state: MyAgentState) -> dict:
    return _specialist(state, "merchant dispute specialist", MERCHANT_INSTRUCTIONS,
                       "Checks on the payment", merchant_checks(state))


def friendly_fraud_specialist(state: MyAgentState) -> dict:
    facts = [f"Points to the customer or household: {s}" for s in customer_made_it_signals(state)]
    facts += [f"Points to someone else: {s}" for s in fraud_signals(state)]
    return _specialist(state, "first-party (friendly) fraud analyst", FRIENDLY_FRAUD_INSTRUCTIONS,
                       "Signals in both directions", facts)


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
Earlier purchases at this merchant: {state["merchant_history"] or "None"}
Customer's past disputes: {state["dispute_history"] or "None"}
Route: {state["route"]} ({state["route_reasons"]})
Specialist assessment: {state["assessment"]}
Recommendation: {state["recommendation"]}
Vulnerability check: {_vulnerability_text(state)}
Classifier's vulnerability signals: {state["vulnerable_signals"] or "None"}

Use only these facts. Quote the details you are given (IDs, dates, amounts, device, 3-D Secure, dispute notes)
instead of saying they were not provided, and present the recommendation as the specialist made it."""
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
3. Reason code fits: fail only if the code is clearly wrong for the complaint (e.g. fraud for a cancelled
   subscription). A vague complaint where the code is a reasonable reading is NOT a failure.
4. Recommendation matches the evidence: e.g. a "not me" claim with several signs that the customer made the payment
   (earlier purchases there, known device + 3-D Secure, lost fraud claims) should not be a chargeback.
5. Complete: it has Summary, Reason code, Transaction details, Evidence, Customer history, Vulnerability and
   Recommendation sections, each with real content.
6. Vulnerability handled: if the complaint or profile shows vulnerability (age, illness, distress, hardship, scam,
   confusion), the Vulnerability section says so and the case is handled with care, not marked "none".
   Anger, frustration or complaining again ("this is a joke", "third time I've written") alone is NOT vulnerability.
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
