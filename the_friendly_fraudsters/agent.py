from langgraph.graph import END, START, StateGraph

from utils.nodes import (
    classify_dispute, draft_evidence_pack, finalise, fraud_specialist, friendly_fraud_specialist,
    human_approval, load_case, merchant_specialist, route_to_specialist, triage,
)
from utils.customer_letter import write_customer_letter
from utils.state import MyAgentContext, MyAgentInput, MyAgentState


def build_agent(**kwargs):
    builder = StateGraph(state_schema=MyAgentState, context_schema=MyAgentContext, input_schema=MyAgentInput)

    builder.add_node("load_case", load_case)
    builder.add_node("classify_dispute", classify_dispute)
    builder.add_node("triage", triage)
    builder.add_node("fraud_specialist", fraud_specialist)
    builder.add_node("merchant_specialist", merchant_specialist)
    builder.add_node("friendly_fraud_specialist", friendly_fraud_specialist)
    builder.add_node("draft_evidence_pack", draft_evidence_pack)
    builder.add_node("human_approval", human_approval)
    builder.add_node("write_customer_letter", write_customer_letter)
    builder.add_node("finalise", finalise)

    builder.add_edge(START, "load_case")
    builder.add_edge("load_case", "classify_dispute")
    builder.add_edge("classify_dispute", "triage")
    builder.add_conditional_edges("triage", route_to_specialist)
    for specialist in ("fraud_specialist", "merchant_specialist", "friendly_fraud_specialist"):
        builder.add_edge(specialist, "draft_evidence_pack")
    builder.add_edge("draft_evidence_pack", "human_approval")
    builder.add_edge("human_approval", "write_customer_letter")
    builder.add_edge("write_customer_letter", "finalise")
    builder.add_edge("finalise", END)

    return builder.compile(**kwargs)


agent = build_agent()

# Example (the human_approval step needs a checkpointer to pause and resume):
#   from langgraph.checkpoint.memory import InMemorySaver
#   from langgraph.types import Command
#   app = build_agent(checkpointer=InMemorySaver())
#   cfg = {"configurable": {"thread_id": "1"}}
#   app.invoke({"complaint_id": "CMP-001"}, cfg)                      # stops at human_approval
#   app.invoke(Command(resume={"decision": "approve", "notes": ""}), cfg)
