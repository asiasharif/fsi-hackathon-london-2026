
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

import utils.customer_letter as cl
import utils.nodes as nodes
from utils.db import DATA_DIR


class FakeModel:

    def __init__(self):
        self.schema = None

    def with_structured_output(self, schema, **kwargs):
        clone = FakeModel()
        clone.schema = schema
        return clone

    def invoke(self, prompt):
        name = self.schema.__name__ if self.schema else None
        if name == "VulnerabilityAssessment":
            return nodes.VulnerabilityAssessment(level="none", types=[], reasons=[])
        if name == "Classification":
            return nodes.Classification(reason_code="fraud_card_not_present", vulnerable_signals=[])
        if name == "Assessment":
            return nodes.Assessment(assessment="Known device, earlier purchases.", recommendation="decline_claim")
        if name == "QualityReview":
            return nodes.QualityReview(issues=[], verdict="pass", send_back_to="human_approval", feedback="")
        if name == "Letter":
            return cl.Letter(subject="About your payment", body=(
                "Dear Tom,\n\nThank you for asking about the £89.99 payment to PixelGames Store. Our records show it was "
                "made in the usual way from a device used with your card before, so we are not able to refund it. "
                "Someone you know may have used it without you realising. You can ask the Financial Ombudsman Service "
                "to review this.\n\nYours sincerely,\nCard Disputes Team\nFriendly Bank"))
        return type("Msg", (), {"content": "# Evidence pack"})()


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(nodes, "llm", lambda: FakeModel())
    monkeypatch.setattr(cl, "init_chat_model", lambda _m: FakeModel())
    # The classifier runs through create_agent (for the PII middleware); give it the same fake answer.
    monkeypatch.setattr(nodes, "create_agent", lambda **kw: type("FakeAgent", (), {"invoke": lambda self, _i: {
        "structured_response": FakeModel().with_structured_output(kw["response_format"]).invoke(None)}})())
    from agent import build_agent
    return build_agent(checkpointer=InMemorySaver(), store=InMemoryStore())


def run_case(app, complaint_id, thread_id):
    cfg = {"configurable": {"thread_id": thread_id}}
    paused = app.invoke({"complaint_id": complaint_id}, cfg)
    done = app.invoke(Command(resume={"decision": "approve", "notes": ""}), cfg)
    return paused, done


def test_full_run_writes_letter_after_approval(app):
    paused, done = run_case(app, "CMP-004", "t1")
    assert "__interrupt__" in paused and "customer_letter" not in paused
    assert paused["route"] == "friendly_fraud"
    assert done["letter_quality"]["outcome"] == "decline_claim"
    assert done["letter_quality"]["source"] == "llm"
    assert "Financial Ombudsman Service" in done["customer_letter"]


def test_runs_do_not_change_the_data_files(app):
    before = (DATA_DIR / "dispute_history.jsonl").read_bytes()
    run_case(app, "CMP-004", "t1")
    assert (DATA_DIR / "dispute_history.jsonl").read_bytes() == before


def test_memory_shown_on_repeat_dispute(app):
    first, _ = run_case(app, "CMP-004", "t1")
    memory = first["__interrupt__"][0].value["memory"]
    assert memory[0].startswith("This customer has lost 2 earlier fraud claims")
    assert not any("Handled by this agent" in line for line in memory)

    second, _ = run_case(app, "CMP-004", "t2")
    memory = second["__interrupt__"][0].value["memory"]
    assert any("Handled by this agent before: 1 case (CMP-004 PixelGames Store: approve" in line for line in memory)
    assert second["route"] == "friendly_fraud"
