# The Friendly Fraudsters: Card Dispute Agent

Team plan, 24 Nov 2026

## Getting started

```bash
git clone https://github.com/asiasharif/fsi-hackathon-london-2026.git
cd fsi-hackathon-london-2026
uv sync --all-packages
cp .env.example .env              # add your own keys; never commit .env
cd the_friendly_fraudsters
git checkout -b <your-role>       # e.g. data-evals, graph-routing, specialists, memory-demo
uv run langgraph dev              # opens LangSmith Studio; input {"complaint_id": "CMP-001"}
uv run python -m evals.run_evals  # scores the agent in LangSmith
```

## Overview

We are building an AI agent that handles card disputes for a bank. A customer says "I didn't make this payment", and the agent works out what kind of problem it is, checks the evidence, recommends what to do and writes the case up. A member of staff then approves the decision. A working starter is in this folder (`the_friendly_fraudsters/`), and the 4 of us each take one part and improve it during the day.

## The problem

Banks get thousands of complaints like "I didn't make this £89 payment", "I cancelled my subscription and they still charged me" or "my sofa never arrived". These are called **disputes**. For each one, a staff member has to:

1. Work out what kind of problem it is.
2. Look up the payment and the customer's history.
3. Decide whether the customer is right.
4. If they are, claw the money back from the shop. That is a **chargeback**, and it needs a written evidence pack.

It is slow, repetitive work, which makes it a good fit for an AI agent.

## The three kinds of dispute

Telling these three apart is the core job of the agent.

| Kind | Example | What usually happens |
| --- | --- | --- |
| Real fraud | A criminal used the card at 3am in Romania | Refund the customer and charge it back |
| Merchant problem | The shop didn't deliver, or kept charging after the customer cancelled | Charge it back to the shop |
| Friendly fraud | The customer says "not me", but they have bought there before on their own phone. Often a family member made the purchase | Usually decline the claim |

## What we're building

The agent works like an assembly line. Each step does one job and passes a growing "case file" to the next.

```
load_case -> classify_dispute -> triage -+-> fraud_specialist ----------+
                                         +-> merchant_specialist -------+-> draft_evidence_pack -> human_approval -> finalise
                                         +-> friendly_fraud_specialist -+
```

1. **Load the case:** pull up the complaint, the customer, the payment, earlier purchases at that shop and the customer's past disputes.
2. **Classify (AI):** read the complaint and pick a reason code, such as "fraud", "goods not received" or "cancelled subscription". Also flag whether the customer sounds vulnerable, for example stressed or in financial hardship.
3. **Triage (plain rules, no AI):** choose which of the three kinds it is. A "not me" claim is treated as likely friendly fraud if at least two of these are true:
   - they have bought from this shop before
   - the payment came from their own device and passed the bank's security check (3-D Secure)
   - they have lost fraud claims before
4. **Specialist (AI):** one of three expert agents (fraud, merchant or friendly fraud) reviews the evidence and recommends an action: file a chargeback, refund the customer, or decline the claim.
5. **Evidence pack (AI):** writes the case up as a tidy report.
6. **Human approval:** the agent pauses, and a member of staff approves the recommendation or overrides it. The AI never has the final say.
7. **Remember:** the outcome is saved to the customer's history, so their next dispute takes it into account.

## Example from a test run

The starter already works end to end. The customer wrote: *"I paid for a sofa three weeks ago and it never arrived… I'm really struggling."*

- The agent classified it as **goods not received**.
- It sent the case to the **merchant specialist**.
- It recommended **filing a chargeback**.
- It flagged the customer as **vulnerable**.
- It wrote a full evidence pack, then paused for a person to approve it.

Sample cases in `data/complaints.jsonl`: CMP-001 (true fraud), CMP-002 (cancelled subscription), CMP-003 (non-delivery, vulnerable customer), CMP-004 (friendly fraud: earlier purchases at the merchant plus two lost fraud claims).

## Why judges should like it

- **Real value:** every bank handles disputes. There is a clear user (the disputes team) and a measurable win (less handling time, fewer bad chargebacks).
- **Technical depth:** a classifier, three specialist agents, memory of each customer and a human approval step. That covers everything the judges listed.
- **Measurable:** the eval script checks how often the agent picks the right reason code and the right specialist. We can show the score before and after improving a prompt.
- **Good live demo:** type "I didn't make this payment", show the steps in LangSmith Studio, show the evidence pack, then click approve.

## What's in this folder

It is a working starting point, not a finished product.

| File | What it is |
| --- | --- |
| `data/` | Fake customers, payments, past disputes and 4 sample complaints with the right answers attached |
| `agent.py` | Connects the steps in order |
| `utils/nodes.py` | What each step actually does |
| `utils/state.py` | The fields in the case file. Agree this as a team first, because everyone's code depends on it |
| `tools/` | Look-ups for the case data, and saving outcomes to the customer's history |
| `evals/run_evals.py` | Scores the agent in LangSmith |
| `README.md` | This plan |

## The 4 roles

Each person can work in parallel once we have agreed the case-file fields (`utils/state.py`) in the first hour. Put your name next to a role.

| Role | In short | Delivers | Owner |
| --- | --- | --- | --- |
| 1. Data and evals | Create the fake world the agent works in, and measure how well it does | Dataset, baseline score, improved score |  |
| 2. Graph and routing | Own the assembly line, so cases reach the right specialist | Working end-to-end run by midday |  |
| 3. Specialists and evidence pack | Make the three expert agents smart and the report professional | Good recommendations and a polished evidence pack |  |
| 4. Memory, approval and demo | The human side, the agent's memory, and the pitch | The demo and the slides |  |

### 1. Data and evals

- Grow the sample complaints from 4 to 20–30 in `data/complaints.jsonl`, each with the right answer attached (expected reason code and expected specialist).
- Cover all three kinds and every reason code, including some tricky or vague ones.
- Add matching customers, payments and past disputes so each case makes sense. For example, a friendly-fraud case needs earlier purchases at the same shop.
- Include a few vulnerable customers.
- Run `evals/run_evals.py` to get accuracy scores in LangSmith.
- Find where the agent gets things wrong, help fix a prompt, and re-run to show the score going up. That before-and-after is a key demo moment.

**Files:** `data/`, `evals/`

### 2. Graph and routing (the "glue" person)

- Own `utils/state.py`, the case-file fields. Nobody changes it without telling this person.
- Own `agent.py`, the order the steps run in.
- Improve the classifier prompt in `classify_dispute` so it picks the right reason code more often, working with the data and evals person.
- Tune the triage rules: which signals mean friendly fraud, and how many are needed.
- Optional extras: send cases the agent isn't sure about straight to a human, or put vulnerable customers in a priority queue.
- Merge everyone's work into one branch and keep it running end to end.

**Files:** `agent.py`, `utils/state.py`, and `load_case`, `classify_dispute` and `triage` in `utils/nodes.py`

### 3. Specialist agents and evidence pack

- **Fraud specialist:** check for warning signs such as a country different from the customer's home, an unknown device, a failed security check or an odd hour.
- **Merchant specialist:** check cancellation dates against the charge date, delivery times, and duplicate amounts.
- **Friendly-fraud specialist:** be fair and careful. Often a family member made the purchase, so the customer isn't lying on purpose.
- Give each specialist its own prompt, and possibly its own tools.
- Make the evidence pack read like a real bank document, with clear sections and the evidence quoted.
- Optional: make each specialist a mini agent that decides which data to look up, rather than receiving everything up front.

**Files:** the three `*_specialist` functions and `draft_evidence_pack` in `utils/nodes.py`

### 4. Memory, human approval and demo

- Make the approval step clear for the reviewer: what the agent recommends, why, and whether the customer is vulnerable. The reviewer can approve or override.
- Make memory visible. On a repeat dispute the agent should say something like "this customer has lost 2 earlier fraud claims".
- Optional: move memory from the data file to LangGraph's built-in store, which shows up nicely in LangSmith.
- Write the 5-minute demo script and slides: the problem, how it works, the live demo, the eval scores and the impact.
- Pick the 2–3 best example complaints for the live demo, and rehearse.

**Files:** `human_approval` and `finalise` in `utils/nodes.py`, `tools/memory.py`, the slides

## Timeline

The goal is one complaint running all the way through by midday, then improve and measure.

| When | Everyone |
| --- | --- |
| First hour | Agree the case-file fields and data format together |
| Midday | One complaint runs end to end, even if the agents are basic |
| Afternoon | Each person improves their part. Run the evals, fix one thing and show the score improve |
| Last hour | Stop adding features, rehearse the demo, push the code |

**Who depends on whom:**

- The data person feeds the evals, and works with the graph person on the classifier.
- The specialists need the case-file fields from the graph person.
- The demo person needs everyone's work by mid-afternoon.
