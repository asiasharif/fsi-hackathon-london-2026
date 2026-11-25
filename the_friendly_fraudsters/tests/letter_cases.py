
from utils.nodes import load_case


def state_for_case(case: dict) -> dict:
    state = {"complaint_id": case["complaint_id"]}
    state.update(load_case(state))
    complaint = state["complaint"]
    state.update(
        reason_code=complaint["expected_reason_code"],
        route=complaint["expected_route"],
        vulnerability=complaint.get("expected_vulnerability") or {"level": "none", "types": []},
        vulnerable_signals=[],
        recommendation=complaint.get("expected_recommendation"),
        reviewer_notes="",
    )
    if case["decided_by"] == "agent_approved":
        state.update(recommendation=case["outcome"], decision="approve")
    elif case["decided_by"] == "human_override":
        state.update(decision=f"override:{case['outcome']}")
    else:
        state.update(recommendation=None, decision="")
    return state
