
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import utils.customer_letter as cl
import utils.nodes as nodes


class FakeModel:

    def __init__(self):
        self.schema = None

    def with_structured_output(self, schema, **kwargs):
        clone = FakeModel()
        clone.schema = schema
        return clone

    def invoke(self, prompt):
        name = self.schema.__name__ if self.schema else None
        if name == "Classification":
            return nodes.Classification(reason_code="fraud_card_not_present", vulnerable_signals=[])
        if name == "Assessment":
            return nodes.Assessment(assessment="Known device, earlier purchases.", recommendation="decline_claim")
        if name == "Letter":
            return cl.Letter(subject="About your payment", body=(
                "Dear Tom,\n\nThank you for asking about the £89.99 payment to PixelGames Store. Our records show it was "
                "made in the usual way from a device used with your card before, so we are not able to refund it. "
                "Someone you know may have used it without you realising. You can ask the Financial Ombudsman Service "
                "to review this.\n\nYours sincerely,\nCard Disputes Team\nFriendly Bank"))
        return type("Msg", (), {"content": "# Evidence pack"})()


def test_full_run_writes_letter_after_approval(monkeypatch):
    monkeypatch.setattr(nodes, "llm", lambda: FakeModel())
    monkeypatch.setattr(cl, "init_chat_model", lambda _m: FakeModel())
    monkeypatch.setattr(nodes, "record_dispute", lambda **kwargs: kwargs)

    from agent import build_agent
    app = build_agent(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}

    paused = app.invoke({"complaint_id": "CMP-004"}, cfg)
    assert "__interrupt__" in paused and "customer_letter" not in paused
    assert paused["route"] == "friendly_fraud"

    done = app.invoke(Command(resume={"decision": "approve", "notes": ""}), cfg)
    assert done["letter_quality"]["outcome"] == "decline_claim"
    assert done["letter_quality"]["source"] == "llm"
    assert "Financial Ombudsman Service" in done["customer_letter"]
