"""Score the classifier and triage against the labelled complaints in LangSmith.

Owner: data/evals. Run from this folder:  python -m evals.run_evals
"""

from langsmith import Client, evaluate

from utils import db
from utils.nodes import classify_dispute, load_case, triage

DATASET = "card-disputes"


def ensure_dataset(client: Client):
    if client.has_dataset(dataset_name=DATASET):
        return
    ds = client.create_dataset(DATASET)
    rows = db.table("complaints")
    client.create_examples(
        dataset_id=ds.id,
        inputs=[{"complaint_id": r["complaint_id"]} for r in rows],
        outputs=[{"reason_code": r["expected_reason_code"], "route": r["expected_route"]} for r in rows],
    )


def target(inputs: dict) -> dict:
    """Run the graph up to triage (no specialists or human step), so evals are quick and cheap."""
    state = {"complaint_id": inputs["complaint_id"]}
    state |= load_case(state)
    state |= classify_dispute(state)
    state |= triage(state)
    return {"reason_code": state["reason_code"], "route": state["route"]}


def reason_code_correct(outputs: dict, reference_outputs: dict) -> bool:
    return outputs["reason_code"] == reference_outputs["reason_code"]


def route_correct(outputs: dict, reference_outputs: dict) -> bool:
    return outputs["route"] == reference_outputs["route"]


if __name__ == "__main__":
    ensure_dataset(Client())
    evaluate(target, data=DATASET, evaluators=[reason_code_correct, route_correct], experiment_prefix="disputes")
