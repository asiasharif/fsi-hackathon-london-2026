"""Customer communication agent: writes the outcome letter after human_approval.

Code decides the facts, the LLM writes the wording, check_letter enforces the rules (1 retry, then a template).
"""

import re
from typing import Literal

from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field

from utils.models import model
from utils.state import FRAUD_CODES, MyAgentState

Action = Literal["file_chargeback", "refund_customer", "decline_claim", "needs_more_info", "fast_lane_holding",
                 "manual_review"]
ACTIONS = {"file_chargeback", "refund_customer", "decline_claim", "needs_more_info"}
MORE_INFO_DECISIONS = {"needs_more_info", "request_more_info", "more_info"}

BANK_NAME = "Friendly Bank"
DISPUTES_TEAM = "Card Disputes Team"
SUPPORT_LINE = "0800 000 0000"
SUPPORT_HOURS = "8am to 8pm, 7 days a week"
SAMARITANS = "116 123"
REPLY_DAYS = {"standard": 14, "vulnerable": 28}

ACCUSATORY_PATTERNS = [
    r"\bfraudulent claim\b", r"\bfalse claim\b", r"\byou lied\b", r"\blied\b", r"\blying\b", r"\bdishonest\b",
    r"\bfraudster\b", r"\bdefraud", r"\bwe don'?t believe you\b", r"\bwe do not believe you\b",
    r"\bfriendly fraud\b", r"\bfirst[- ]party fraud\b", r"\byou made (this|the) (payment|purchase)\b",
    r"\b(family member|someone in your (household|family)|someone you know|a relative) (made|used|bought|has used)\b",
    r"\byour (child|son|daughter|partner|grandson|granddaughter)\b", r"\bmisuse\b", r"\babuse\b",
]
TONE_PATTERNS = [r"\bcalm down\b", r"\bunfortunately you\b", r"\bfailure to respond\b", r"\bimmediately or\b"]
JARGON_PATTERNS = [r"\breason code\b", r"\b3-?d secure\b", r"\btriage\b", r"\bfraud_card", r"\bcancelled_recurring\b",
                   r"\bgoods_not_received\b", r"\bevidence pack\b", r"\bspecialist\b", r"\bcnp\b",
                   r"\bfast[- ]lane\b"]
REFUND_PROMISE_PATTERNS = [r"\bwe(?:'ve| have) refunded\b", r"\bwe(?:'ll| will) refund\b", r"\bwe are refunding\b",
                           r"\byou(?:'ll| will) (?:get|receive) (?:a refund|your money back)\b", r"\bhas been credited\b"]
OMBUDSMAN_PATTERN = r"financial ombudsman"
UPSET_PATTERN = r"\b(furious|angry|livid|fuming|ridiculous|disgusted|disgusting|unacceptable|outrageous|fed up|sort this out)\b"
ACKNOWLEDGE_PATTERN = r"\b(understand|sorry|frustrat)"
POSSIBILITY_PATTERN = r"\b(household|someone you know|family)\b"
EVIDENCE_PATTERN = r"\b(device|earlier|previous)\b"
NOT_A_DECISION_PATTERNS = [r"\bdeclined\b", r"\brejected\b"]

MORE_INFO_NEEDED = {
    "cancelled_recurring": "a copy of your cancellation confirmation, such as the email {merchant} sent you",
    "goods_not_received": "your order confirmation, and anything showing when it should have been delivered",
    "not_as_described": "photos of what you received, and the description from your order",
    "incorrect_amount": "your receipt or bill showing the amount you agreed to pay",
    "duplicate_charge": "any receipt or confirmation showing you paid {merchant} only once",
}
MORE_INFO_DEFAULT = "anything that could help us understand what happened, such as receipts, emails or messages"


class Letter(BaseModel):
    subject: str = Field(description="Short, plain subject line, for example 'Update on the payment you asked us about'")
    body: str = Field(description="The full letter body, starting 'Dear <name>,' and ending with the sign-off")


# ---------------------------------------------------------------- facts
def vulnerability_level(state: MyAgentState) -> str | None:
    level = (state.get("vulnerability") or {}).get("level") or state.get("vulnerability_level")
    return level if level in ("none", "low", "medium", "high") else None


def is_high_risk(state: MyAgentState) -> bool:
    return vulnerability_level(state) == "high" or state.get("route") == "fast_lane"


def resolve_outcome(state: MyAgentState) -> Action:
    """High risk -> holding message. Otherwise the human's decision wins; anything unclear -> manual_review."""
    if is_high_risk(state):
        return "fast_lane_holding"
    decision = (state.get("decision") or "").strip().lower()
    if decision in MORE_INFO_DECISIONS:
        return "needs_more_info"
    if decision.startswith("override"):
        action = decision.split(":", 1)[1].strip() if ":" in decision else ""
        action = "needs_more_info" if action in MORE_INFO_DECISIONS else action
        return action if action in ACTIONS else "manual_review"
    if decision in ("approve", "approved") and state.get("recommendation") in ACTIONS:
        return state["recommendation"]
    return "manual_review"


def is_vulnerable(state: MyAgentState) -> bool:
    if vulnerability_level(state) in ("low", "medium", "high"):
        return True
    return bool(state.get("vulnerable_signals") or (state.get("customer") or {}).get("vulnerable"))


def letter_tone(state: MyAgentState) -> dict:
    return {
        "vulnerable": is_vulnerable(state),
        "non_accusatory": state.get("route") == "friendly_fraud" or state.get("reason_code") in FRAUD_CODES,
        "upset": bool(re.search(UPSET_PATTERN, ((state.get("complaint") or {}).get("text") or "").lower())),
    }


def letter_type(action: Action, tone: dict) -> str:
    if action == "decline_claim" and tone["non_accusatory"]:
        return "friendly_fraud_decline"
    return {"refund_customer": "refund", "file_chargeback": "chargeback", "decline_claim": "decline"}.get(action, action)


def _money(tx: dict) -> str:
    amount = tx.get("amount")
    if amount is None:
        return "the payment"
    symbol = "£" if tx.get("currency", "GBP") == "GBP" else f"{tx.get('currency')} "
    return f"{symbol}{amount:,.2f}"


def _amount_forms(amount: float) -> set[str]:
    forms = {f"{amount:,.2f}", f"{amount:.2f}"}
    if float(amount).is_integer():
        forms |= {f"{int(amount):,}", str(int(amount))}
    return forms


def _is_fraud_case(state: MyAgentState) -> bool:
    return state.get("reason_code") in FRAUD_CODES and state.get("route") != "friendly_fraud"


def explanation(action: Action, state: MyAgentState, tone: dict) -> list[str]:
    """Friendly-fraud declines only: what our records show, plus a non-accusing possibility."""
    if letter_type(action, tone) != "friendly_fraud_decline":
        return []
    tx = state.get("transaction") or {}
    merchant = tx.get("merchant", "the merchant")
    lines = []
    if state.get("merchant_history"):
        lines.append(f"Our records show earlier payments from your card to {merchant}.")
    if tx.get("device_known") and tx.get("3ds_passed"):
        lines.append("This payment was made from a device that has been used with your card before, "
                     "and it passed our extra security check.")
    lines.append("Sometimes a payment like this is made by someone in the same household or someone you know, "
                 "without the cardholder realising. If that might have happened, it may help to ask them.")
    lines.append("This doesn't mean we think you have done anything wrong.")
    return lines


def next_steps(action: Action, state: MyAgentState, vulnerable: bool) -> list[str]:
    tx = state.get("transaction") or {}
    money, merchant = _money(tx), tx.get("merchant", "the merchant")
    reply_days = REPLY_DAYS["vulnerable" if vulnerable else "standard"]
    needed = MORE_INFO_NEEDED.get(state.get("reason_code"), MORE_INFO_DEFAULT).format(merchant=merchant)
    steps = {
        "refund_customer": [
            f"We have refunded {money} to your account. It should appear within 2 working days.",
            "We have cancelled your card and sent you a new one, which should arrive within 5 working days."
            if (state.get("reason_code") in FRAUD_CODES) else "You don't need to do anything else.",
        ],
        "file_chargeback": [
            f"We have asked {merchant} to return the {money}. They have up to 45 days to respond.",
            "We will write to you again as soon as we hear back, or within 45 days at the latest.",
        ],
        "decline_claim": [
            f"We are not able to refund the {money} payment to {merchant}.",
            f"If you have any information we haven't seen, please send it to us within {reply_days} days and we will look again.",
            "If you're unhappy with our decision, you can ask the Financial Ombudsman Service to look at it. "
            "This is free, and you have 6 months from the date of this letter to contact them (financial-ombudsman.org.uk).",
        ],
        "needs_more_info": [
            f"To help us look into the {money} payment to {merchant}, please send us {needed}.",
            f"Please send it within {reply_days} days, by replying to this letter.",
            "Once we have it, we will carry on looking into this and write to you within 10 working days.",
        ],
        "manual_review": [
            "A member of our team is looking at your case personally.",
            "They will contact you within 2 working days.",
        ],
        "fast_lane_holding": [],
    }[action]
    if action in ("refund_customer", "file_chargeback") and _is_fraud_case(state):
        steps.append("We will never phone, text or email you to ask for your PIN or passwords, or to move money. "
                     "If anyone does, it's a scam: hang up and call the number on the back of your card.")
    if vulnerable:
        steps.append(f"If you'd like to talk this through, call our support team free on {SUPPORT_LINE} ({SUPPORT_HOURS}). "
                     "You can ask for more time, or for someone to help you, at any point.")
    return steps


# ---------------------------------------------------------------- guardrails
def check_letter(text: str, action: Action, state: MyAgentState, vulnerable: bool, non_accusatory: bool,
                 upset: bool = False) -> list[str]:
    """Return the problems with the letter. Empty list = passed."""
    lower = text.lower()
    problems = []
    tx = state.get("transaction") or {}
    name = (state.get("customer") or {}).get("name", "")
    tone = {"non_accusatory": non_accusatory}

    if name and name.split()[0].lower() not in lower:
        problems.append("The letter does not address the customer by name.")
    if tx.get("merchant") and tx["merchant"].lower() not in lower:
        problems.append(f"The letter does not name the merchant ({tx['merchant']}).")
    if tx.get("amount") is not None and not any(form in text for form in _amount_forms(tx["amount"])):
        problems.append(f"The letter does not state the amount ({_money(tx)}).")
    if any(re.search(p, lower) for p in JARGON_PATTERNS):
        problems.append("The letter uses internal jargon (reason codes, 3-D Secure, specialist, evidence pack...).")
    if any(re.search(p, lower) for p in TONE_PATTERNS):
        problems.append("The letter sounds defensive or pressuring (for example 'calm down', 'unfortunately you').")
    if non_accusatory or action == "decline_claim":
        if any(re.search(p, lower) for p in ACCUSATORY_PATTERNS):
            problems.append("The letter accuses or blames the customer or someone else. Explain neutrally instead, "
                            "and only as a possibility.")
    if action in ("decline_claim", "needs_more_info", "manual_review", "fast_lane_holding") and \
            any(re.search(p, lower) for p in REFUND_PROMISE_PATTERNS):
        problems.append("The letter promises or implies a refund, but the outcome is not a refund.")
    if action == "decline_claim" and not re.search(OMBUDSMAN_PATTERN, lower):
        problems.append("A decline must tell the customer they can go to the Financial Ombudsman Service.")
    if letter_type(action, tone) == "friendly_fraud_decline":
        if not re.search(POSSIBILITY_PATTERN, lower):
            problems.append("A friendly-fraud decline must gently mention that someone in the household or someone "
                            "the customer knows may have made the payment.")
        if explanation(action, state, tone)[:-2] and not re.search(EVIDENCE_PATTERN, lower):
            problems.append("A friendly-fraud decline must say neutrally what our records show (the device, or "
                            "earlier payments to the merchant).")
    if action in ("needs_more_info", "manual_review", "fast_lane_holding") and \
            any(re.search(p, lower) for p in NOT_A_DECISION_PATTERNS):
        problems.append("No decision has been made, so the letter must not say the claim is declined or rejected.")
    if action == "needs_more_info" and not (re.search(r"\b(within|by)\b", lower) and
                                            re.search(r"\b\d+ (working )?days\b", lower)):
        problems.append("The letter must say what we need and give a deadline ('within N days').")
    if action in ("refund_customer", "file_chargeback") and _is_fraud_case(state) and \
            not re.search(r"\b(scam|will never)\b", lower):
        problems.append("A fraud letter must remind the customer we will never ask for their PIN, passwords or to "
                        "move money (and that anyone who does is a scammer).")
    if upset and not re.search(ACKNOWLEDGE_PATTERN, lower):
        problems.append("The customer is upset. Acknowledge how they feel (for example 'we understand how "
                        "frustrating this is'), calmly and without being defensive.")
    if vulnerable and SUPPORT_LINE not in text:
        problems.append(f"A vulnerable customer must be given the support line ({SUPPORT_LINE}).")
    if vulnerable:
        sentences = [s for s in re.split(r"[.!?]\s", text) if s.strip()]
        longest = max((len(s.split()) for s in sentences), default=0)
        if longest > 35:
            problems.append("Some sentences are too long for a vulnerable customer. Keep each under 25 words.")
    if len(text.split()) > 350:
        problems.append("The letter is too long. Keep it under 250 words.")
    return problems


# ---------------------------------------------------------------- fixed letters
SIGN_OFF = f"Yours sincerely,\n{DISPUTES_TEAM}\n{BANK_NAME}"
_SIGN_OFF_PATTERN = re.compile(
    rf"Yours sincerely,?\s*{re.escape(DISPUTES_TEAM)}[,.]?\s*{re.escape(BANK_NAME)}[,.]?\s*$", re.IGNORECASE)


def tidy_sign_off(body: str) -> str:
    return _SIGN_OFF_PATTERN.sub(SIGN_OFF, body.rstrip())


def fast_lane_letter(state: MyAgentState) -> Letter:
    """High risk: fixed holding message with support options. No decision, no LLM."""
    tx = state.get("transaction") or {}
    name = (state.get("customer") or {}).get("name", "Customer")
    body = (f"Dear {name},\n\n"
            f"Thank you for getting in touch about the {_money(tx)} payment to {tx.get('merchant', 'the merchant')}. "
            "We're sorry you're going through this.\n\n"
            "A member of our team will contact you personally within 24 hours. "
            "You don't need to do anything before then.\n\n"
            f"If you need to talk to someone now, Samaritans are free to call, day or night, on {SAMARITANS}. "
            "If you feel you are in danger, please call 999.\n\n"
            f"You can also call our support team free on {SUPPORT_LINE} ({SUPPORT_HOURS}).\n\n"
            f"{SIGN_OFF}")
    return Letter(subject="We're here to help", body=body)


def template_letter(action: Action, state: MyAgentState, vulnerable: bool) -> Letter:
    """Fallback letter that always passes the checks."""
    if action == "fast_lane_holding":
        return fast_lane_letter(state)
    tx = state.get("transaction") or {}
    name = (state.get("customer") or {}).get("name", "Customer")
    tone = {**letter_tone(state), "vulnerable": vulnerable}
    about = f"the {_money(tx)} payment to {tx.get('merchant', 'the merchant')}"
    opening = {
        "refund_customer": f"Thank you for telling us about {about}. We have looked into it and agree you should not "
                           "have been charged.",
        "file_chargeback": f"Thank you for telling us about {about}. We have looked into it and we are now taking it "
                           "up with them on your behalf.",
        "decline_claim": f"Thank you for telling us about {about}. We have looked carefully at the payment and the "
                         "information we hold.",
        "needs_more_info": f"Thank you for telling us about {about}. We need a little more information before we can "
                           "decide.",
        "manual_review": f"Thank you for telling us about {about}.",
    }[action]
    if tone["upset"]:
        opening = "We understand how frustrating this is. " + opening
    why = " ".join(explanation(action, state, tone))
    steps = "\n".join(f"- {s}" for s in next_steps(action, state, vulnerable))
    body = (f"Dear {name},\n\n{opening}" + (f"\n\n{why}" if why else "") +
            f"\n\nWhat happens next:\n{steps}\n\n{SIGN_OFF}")
    return Letter(subject="An update on the payment you asked us about", body=body)


# ---------------------------------------------------------------- the node
def _prompt(state: MyAgentState, action: Action, tone: dict, why: list[str], steps: list[str],
            feedback: list[str]) -> str:
    tx = state.get("transaction") or {}
    outcome_text = {
        "refund_customer": "We agree with the customer and are refunding them.",
        "file_chargeback": "We are taking the payment up with the merchant (a chargeback) on the customer's behalf.",
        "decline_claim": "We are not able to refund this payment.",
        "needs_more_info": "No decision yet: we need more information from the customer before we can decide.",
        "manual_review": "No decision yet: a person will contact the customer personally.",
    }[action]
    rules = [
        "Write in plain English, as if speaking to a friend. Short sentences, no jargon, no legal language.",
        "Write as the bank: always 'we' and 'you', never 'I'. Be warm, clear and honest. "
        "Do not apologise for things the bank did not do wrong.",
        "Include EVERY 'what happens next' point below, in your own words but with the same facts, dates and numbers.",
        "Do not promise anything that is not in the 'what happens next' points.",
        "Never mention internal terms: reason codes, 3-D Secure, specialists, triage, evidence packs, chargeback codes.",
        "Never mention the customer's past disputes or claims.",
        f"Address the customer as 'Dear {(state.get('customer') or {}).get('name', 'Customer')},' and end with the "
        f"sign-off on three lines: 'Yours sincerely,' then '{DISPUTES_TEAM}' then '{BANK_NAME}'.",
        f"Mention the merchant ({tx.get('merchant')}) and the amount ({_money(tx)}).",
        "Keep the letter under 250 words.",
    ]
    if tone["non_accusatory"] or action == "decline_claim":
        rules.append("Never suggest the customer is lying or committing fraud. Never say as a fact that someone else "
                     "made the payment, and never name a particular person (a son, partner...): only a gentle "
                     "possibility, as in the 'why' points.")
    if why:
        rules.append("Include EVERY 'why' point below, in your own words, calmly and neutrally, before the next steps.")
    if action == "needs_more_info":
        rules.append("Say clearly that no decision has been made yet. Never say the claim is declined or rejected.")
    if tone["upset"]:
        rules.append("The customer is upset. Start by acknowledging how frustrating this is, in one short sentence. "
                     "Stay calm and kind, never defensive.")
    if tone["vulnerable"]:
        rules.append("This customer may be going through a difficult time. Be especially gentle and reassuring, use "
                     "simple everyday words, keep every sentence under 20 words, give the support line, and make "
                     "clear there is no pressure or rush.")
    if action == "decline_claim":
        rules.append("Tell them clearly they can ask the Financial Ombudsman Service to review the decision, free of charge.")

    why_block = ("\n\nWhy (must all be included):\n" + "\n".join("- " + w for w in why)) if why else ""
    prompt = f"""You are the customer communications writer for {BANK_NAME}'s card disputes team, writing in line with the
FCA's Consumer Duty (clear, fair, not misleading, supporting customers to make good decisions).

Write the letter telling the customer the outcome of their dispute.

What the customer told us: {(state.get("complaint") or {}).get("text", "")}
Payment: {_money(tx)} to {tx.get("merchant")} on {str(tx.get("timestamp", ""))[:10]}
Outcome: {outcome_text}
Reviewer notes (internal, use only if they help explain the outcome, never quote them): {state.get("reviewer_notes") or "None"}{why_block}

What happens next (must all be included):
{chr(10).join("- " + s for s in steps)}

Rules:
{chr(10).join("- " + r for r in rules)}"""
    if feedback:
        prompt += "\n\nYour previous draft had these problems. Fix all of them:\n" + "\n".join("- " + f for f in feedback)
    return prompt


def write_customer_letter(state: MyAgentState, max_attempts: int = 2) -> dict:
    """Graph node: write, check and (if needed) rewrite the customer letter."""
    action = resolve_outcome(state)
    tone = letter_tone(state)
    quality = {"outcome": action, "letter_type": letter_type(action, tone), "vulnerable": tone["vulnerable"],
               "non_accusatory": tone["non_accusatory"], "upset": tone["upset"]}

    if action == "fast_lane_holding":
        letter = fast_lane_letter(state)
        return {"customer_letter": f"Subject: {letter.subject}\n\n{letter.body}",
                "letter_quality": {**quality, "attempts": 0, "source": "fixed_template", "last_problems": []}}

    why = explanation(action, state, tone)
    steps = next_steps(action, state, tone["vulnerable"])
    feedback: list[str] = []
    attempts = 0
    letter = None
    writer = init_chat_model(model).with_structured_output(Letter, method="json_schema")
    for attempts in range(1, max_attempts + 1):
        try:
            draft = writer.invoke(_prompt(state, action, tone, why, steps, feedback))
        except Exception as error:
            feedback = [f"Model error: {error}"]
            continue
        feedback = check_letter(draft.body, action, state, tone["vulnerable"], tone["non_accusatory"], tone["upset"])
        if not feedback:
            letter = Letter(subject=draft.subject, body=tidy_sign_off(draft.body))
            break

    source = "llm"
    if letter is None:
        letter, source = template_letter(action, state, tone["vulnerable"]), "template_fallback"

    return {
        "customer_letter": f"Subject: {letter.subject}\n\n{letter.body}",
        "letter_quality": {**quality, "attempts": attempts, "source": source,
                           "last_problems": feedback if source == "template_fallback" else []},
    }
