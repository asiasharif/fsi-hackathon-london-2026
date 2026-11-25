from langgraph.store.memory import InMemoryStore

from tools.cases import get_dispute_history
from tools.memory import memory_summary, recall_disputes, record_dispute

ROW = dict(customer_id="CUST-102", complaint_id="CMP-004", transaction_id="TX-5006", merchant="PixelGames Store",
           reason_code="fraud_card_not_present", outcome="pending", decision="approve", notes="decline_claim.")


def test_no_store_saves_nothing():
    assert record_dispute(None, **ROW) is None
    assert recall_disputes(None, "CUST-102") == []


def test_store_round_trip():
    store = InMemoryStore()
    saved = record_dispute(store, **ROW)
    assert saved["dispute_id"].startswith("RUN-")
    assert recall_disputes(store, "CUST-102") == [saved]
    assert recall_disputes(store, "CUST-999") == []


def test_summary_from_seeded_history():
    lines = memory_summary(get_dispute_history("CUST-102"), [])
    assert lines[0].startswith("This customer has lost 2 earlier fraud claims (PixelGames Store, 2026-07-02; SkyFlix")


def test_summary_won_and_none():
    assert memory_summary(get_dispute_history("CUST-104"), []) == ["Won 1 earlier dispute (AirLink, 2025-03-11)."]
    assert memory_summary([], []) == ["No earlier disputes."]
