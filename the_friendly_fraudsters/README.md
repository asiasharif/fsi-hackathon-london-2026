# The Friendly Fraudsters: card dispute and chargeback agent

"I didn't make this payment" -> reason code -> specialist -> evidence pack -> human approval -> memory.

```
load_case -> classify_dispute -> triage -+-> fraud_specialist ----------+
                                         +-> merchant_specialist -------+-> draft_evidence_pack -> human_approval -> finalise
                                         +-> friendly_fraud_specialist -+
```

## Who owns what (team of 4)

| Owner | Files |
|-------|-------|
| Data and evals | `data/*.jsonl` (grow `complaints.jsonl` to 20–30 labelled cases), `evals/run_evals.py` |
| Graph and routing | `agent.py`, `utils/state.py`, `load_case`, `classify_dispute`, `triage` in `utils/nodes.py` |
| Specialists and output | the three `*_specialist` nodes and `draft_evidence_pack` |
| Memory, HITL and demo | `human_approval`, `finalise`, `tools/memory.py`, slides and demo script |

`utils/state.py` is the contract between everyone, so agree on it first and change it together.

## Run

```bash
cd the_friendly_fraudsters
uv run langgraph dev          # opens LangSmith Studio; input {"complaint_id": "CMP-001"}
uv run python -m evals.run_evals
```

Sample cases: CMP-001 (true fraud), CMP-002 (cancelled subscription), CMP-003 (non-delivery, vulnerable customer),
CMP-004 (friendly fraud: earlier purchases at the merchant plus two lost fraud claims).
