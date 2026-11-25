"""Score the agent against the labelled complaints in LangSmith.

Owner: data/evals. Run from the_friendly_fraudsters/:  uv run python -m evals.run_evals

It runs the investigation part of the graph (load -> classify -> triage -> specialist), with no evidence pack,
review, human or letter, so it is quick and cheap. It scores:
- reason_code_correct: the classifier picked the right reason code
- route_correct: the case went to the right specialist (or the fast lane)
- vulnerability_flag_correct: the agent flagged vulnerability exactly when the label says so
- high_risk_caught: (high-risk cases only) the case went to the fast lane. Missing one is the worst mistake.
- recommendation_correct: the specialist recommended the right action (chargeback, refund or decline).
  Not scored on fast-lane cases, where a human decides.

Bump DATASET (v2, v3...) whenever data/complaints.jsonl changes, so LangSmith gets the new cases.
"""

import time

from langsmith import Client, evaluate

from utils import db
from utils.nodes import (classify_dispute, fraud_specialist, friendly_fraud_specialist, load_case,
                         merchant_specialist, triage, vulnerability_check)

SPECIALISTS = {"fraud": fraud_specialist, "merchant": merchant_specialist, "friendly_fraud": friendly_fraud_specialist}

DATASET = "friendly-fraudsters-disputes-v3"


def ensure_dataset(client: Client):
    if client.has_dataset(dataset_name=DATASET):
        return
    ds = client.create_dataset(DATASET, description="The Friendly Fraudsters: labelled card dispute complaints")
    rows = db.table("complaints")
    client.create_examples(
        dataset_id=ds.id,
        inputs=[{"complaint_id": r["complaint_id"], "text": r["text"]} for r in rows],
        outputs=[{"reason_code": r["expected_reason_code"], "route": r["expected_route"],
                  "vulnerability_level": r["expected_vulnerability"]["level"],
                  "recommendation": r["expected_recommendation"]} for r in rows],
    )


def target(inputs: dict) -> dict:
    """Run the graph up to the specialist (no evidence pack, review, human or letter), so evals are quick and cheap."""
    start = time.perf_counter()
    state = {"complaint_id": inputs["complaint_id"]}
    state |= load_case(state)
    state |= vulnerability_check(state)
    state |= classify_dispute(state)  # still scored for high-risk cases, even though the graph skips it for them
    state |= triage(state)
    level = state.get("vulnerability", {}).get("level")
    flagged = (level not in (None, "none")) if level else bool(state.get("vulnerable_signals"))
    route = state.get("route")
    if level == "high":
        route = "fast_lane"
    recommendation = None
    if route in SPECIALISTS:
        state |= SPECIALISTS[route](state)
        recommendation = state.get("recommendation")
    return {"reason_code": state["reason_code"], "route": route, "vulnerable": flagged, "recommendation": recommendation,
            "vulnerability_level": level or ("flagged" if flagged else "none"),
            "seconds": round(time.perf_counter() - start, 2)}


def reason_code_correct(outputs: dict, reference_outputs: dict) -> bool:
    return outputs["reason_code"] == reference_outputs["reason_code"]


def route_correct(outputs: dict, reference_outputs: dict) -> bool:
    return outputs["route"] == reference_outputs["route"]


def vulnerability_flag_correct(outputs: dict, reference_outputs: dict) -> bool:
    return outputs["vulnerable"] == (reference_outputs["vulnerability_level"] != "none")


def high_risk_caught(outputs: dict, reference_outputs: dict):
    if reference_outputs["vulnerability_level"] != "high":
        return {"key": "high_risk_caught", "score": None, "comment": "not a high-risk case"}
    return {"key": "high_risk_caught", "score": outputs["route"] == "fast_lane"}


def recommendation_correct(outputs: dict, reference_outputs: dict):
    if reference_outputs.get("recommendation") is None:
        return {"key": "recommendation_correct", "score": None, "comment": "fast-lane case: a human decides"}
    return {"key": "recommendation_correct", "score": outputs["recommendation"] == reference_outputs["recommendation"]}


if __name__ == "__main__":
    ensure_dataset(Client())
    results = evaluate(target, data=DATASET, experiment_prefix="disputes-baseline",
                       evaluators=[reason_code_correct, route_correct, vulnerability_flag_correct, high_risk_caught,
                                           recommendation_correct])

    # Plain summary for the notebook and slides.
    totals, seconds, misses = {}, [], []
    for r in results:
        out, ref = r["run"].outputs or {}, r["example"].outputs
        seconds.append(out.get("seconds", 0))
        for e in r["evaluation_results"]["results"]:
            if e.score is None:
                continue
            ok, n = totals.get(e.key, (0, 0))
            totals[e.key] = (ok + int(bool(e.score)), n + 1)
            if not e.score:
                misses.append(f"{r['example'].inputs['complaint_id']}: {e.key} failed. Agent said route={out.get('route')}, "
                              f"reason={out.get('reason_code')}, vulnerable={out.get('vulnerable')}, "
                              f"recommendation={out.get('recommendation')}. Expected {ref}")
    print("\nRESULTS")
    for key, (ok, n) in totals.items():
        print(f"  {key}: {ok}/{n}")
    if seconds:
        print(f"  median seconds per case: {sorted(seconds)[len(seconds) // 2]}")
    print("MISSES" if misses else "No misses.")
    for m in misses:
        print("  " + m)
