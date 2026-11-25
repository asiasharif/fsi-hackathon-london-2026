"""Customer memory. Case outcomes are saved in LangGraph's store (not the data files), so runs never change the
dataset, and the human sees the customer's history on the approval screen.

Without a store (tests, evals) nothing is saved.
"""

import uuid
from datetime import date

from langgraph.store.base import BaseStore

from utils.state import FRAUD_CODES

NAMESPACE = "dispute_outcomes"


def record_dispute(store: BaseStore | None, customer_id: str, complaint_id: str, transaction_id: str, merchant: str,
                   reason_code: str, outcome: str, decision: str, notes: str) -> dict | None:
    if store is None:
        return None
    row = {
        "dispute_id": f"RUN-{uuid.uuid4().hex[:8].upper()}",
        "customer_id": customer_id,
        "complaint_id": complaint_id,
        "transaction_id": transaction_id,
        "merchant": merchant,
        "reason_code": reason_code,
        "outcome": outcome,
        "decision": decision,
        "notes": notes,
        "opened": date.today().isoformat(),
    }
    store.put((NAMESPACE, customer_id), row["dispute_id"], row)
    return row


def recall_disputes(store: BaseStore | None, customer_id: str) -> list[dict]:
    if store is None:
        return []
    rows = [item.value for item in store.search((NAMESPACE, customer_id), limit=100)]
    return sorted(rows, key=lambda r: r.get("opened", ""))


def _when_where(rows: list[dict]) -> str:
    return "; ".join(f"{r.get('merchant', '?')}, {r.get('opened', '?')}" for r in rows)


def memory_summary(history: list[dict], recalled: list[dict]) -> list[str]:
    """Plain-English lines for the approval screen, e.g. 'This customer has lost 2 earlier fraud claims (...)'."""
    lost_fraud = [d for d in history if d.get("reason_code") in FRAUD_CODES and d.get("outcome") == "lost"]
    lost_other = [d for d in history if d.get("outcome") == "lost" and d not in lost_fraud]
    won = [d for d in history if d.get("outcome") == "won"]
    lines = []
    if lost_fraud:
        lines.append(f"This customer has lost {len(lost_fraud)} earlier fraud claim{'s' * (len(lost_fraud) > 1)} "
                     f"({_when_where(lost_fraud)}).")
    if lost_other:
        lines.append(f"Lost {len(lost_other)} other earlier dispute{'s' * (len(lost_other) > 1)} ({_when_where(lost_other)}).")
    if won:
        lines.append(f"Won {len(won)} earlier dispute{'s' * (len(won) > 1)} ({_when_where(won)}).")
    if recalled:
        cases = "; ".join(f"{r.get('complaint_id')} {r.get('merchant')}: {r.get('decision')} on {r.get('opened')}"
                          for r in recalled[-3:])
        lines.append(f"Handled by this agent before: {len(recalled)} case{'s' * (len(recalled) > 1)} ({cases}).")
    return lines or ["No earlier disputes."]
