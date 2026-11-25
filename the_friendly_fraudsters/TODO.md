# The Friendly Fraudsters: team to-do list

FSI Hackathon London, 25 Nov 2026. Tick items off (`[x]`) as you finish them and push, so everyone can see progress.

## Key times

| Time | What |
| --- | --- |
| 10:00–13:00 | Build block 1 |
| **Before lunch** | Quality reviewer and customer letter agents merged into `main` |
| 13:00–14:00 | Lunch |
| 14:00–15:45 | Build block 2 |
| **15:45** | **Submission deadline:** fork link and slides |
| 16:00 | Demos: 5 minutes plus Q&A |

## Status at a glance (updated after every PR was merged, up to #13)

| Person | Done | Pending |
| --- | --- | --- |
| **Asia** (data, evals and **slides**) | 25 labelled cases, 2 test sets, data checker, eval with 5 scores, notebook sections 1–8, sourced ROI, slide notes, submission deck | Put the final scoreboard into the notebook and deck, final push |
| **Pradeep** (reviewer, then graph) | Quality reviewer (**8/8 on the test packs**), review loop, vulnerability check + **fast lane** (crisis cases 2/2), triage fixes incl. **CMP-019 trap**, classifier reason-code definitions, final eval run twice, all 25 cases run end to end, evidence pack fix (**22/23 pass review first time**) | Keep `main` running until submission |
| **Wasiu** (letters, then demo) | Customer letter agent with fast-lane holding message, memory in the LangGraph store (test runs no longer change the data), memory on the approval screen, 69 passing tests, `DEMO.md` runbook | Rehearse the demo to under 5 minutes |
| **Miriam** (specialists) | Fraud, merchant and friendly-fraud specialists, merged in PR #13 (recommendation **23/23**) | Nothing open |

## Scoreboard (25 cases, LangSmith dataset `friendly-fraudsters-disputes-v3`)

| Measure | Before (starter) | Now | Who can improve it |
| --- | --- | --- | --- |
| **Crisis cases sent straight to a human** | 0 / 2 | **2 / 2** | Done |
| Vulnerability spotted correctly | 24 / 25 | **25 / 25** | Done |
| Route correct | 21 / 25 | **25 / 25** | Done |
| Reason code correct | 23 / 25 | **25 / 25** | Done |
| Recommendation correct (fast-lane excluded) | 19 / 23 | **23 / 23** | Done |
| Quality reviewer on the 8 test packs | n/a | **8 / 8** | Done |
| Letters passing every rule (8 scenarios, real agent) | n/a | **8 / 8** | Done |
| Full graph, all 25 cases end to end (through to the letter) | n/a | **25 / 25, no errors** | Done |
| Evidence packs passing review first time | n/a | 12 / 23 → **22 / 23** | Done |
| Median time per case (investigation steps) | 3.6 s | 4.8 s | |
| Median time per case, full graph (slowest case) | n/a | **17 s (25 s)** | |

Scores move by ±1 between runs because the AI isn't perfectly consistent, so we run the final eval twice. **Final eval, run twice after PR #13: no misses either time.** Run it yourself: `uv run python -m evals.run_evals`

## How we're judged (30 points)

| Area | What judges look for | Who covers it |
| --- | --- | --- |
| Use case impact | A real FSI problem with a clear user. **KPIs and ROI estimated** | Asia (numbers), Wasiu (slides) |
| Technical depth | LangGraph, memory, middleware, **evals**; completeness, system design, architecture | Everyone |
| Presentation | 5-minute demo, on time, **works end to end**, handles Q&A | Wasiu leads, everyone rehearses |

## Submission checklist (everyone)

- [x] Company name: **The Friendly Fraudsters | NatWest**
- [x] README title shows team name **and company**, use case and how to run it
- [ ] `dispute_agent.ipynb` (the notebook) and `agent.py` committed to `main` (notebook is in; final version after the last eval)
- [x] Evals and datasets committed (`data/`, `evals/`)
- [x] 5-minute deck from the LangChain template, named `HACK_NATWEST_THEFRIENDLYFRAUDSTERS` (`.pptx` and `.pdf` committed; update it with the final scoreboard)
- [ ] Fork link and slides submitted via the QR code / link in the master deck, and emailed to both hosts **by 15:45**

## Shared decisions

- [x] **New field names in `utils/state.py`**: agreed and used (`vulnerability`, `review_result`, `review_feedback`, `send_back_to`, `retry_count`, `customer_letter`)
- [x] **What "good enough" means for an evidence pack:** the reviewer's 8-point checklist in `review_pack` (grounded, nothing invented, reason code fits, recommendation matches the evidence, complete, vulnerability handled, no accusing tone, decision-ready)
- [ ] **ROI assumption to agree:** the % of handling effort the agent removes (proposed 60%). Everything else is sourced: see KPIs and ROI

---

## Asia: Task 1, data and evals

Branch: `data-evals`

| # | Task | When | Status |
| --- | --- | --- | --- |
| 1 | Dataset: 25 labelled cases with linked customers, payments and history (vague, mixed, lookalikes, low vulnerability, traps) | Morning | Done |
| 2 | Data checker: `uv run python -m evals.check_data` | Morning | Done |
| 3 | Quality reviewer test set for Pradeep: 8 evidence packs (`data/qa_test_packs.jsonl`) | Morning | Done |
| 4 | Letter test set for Wasiu: 8 scenarios with must / must-not rules (`data/letter_test_cases.jsonl`) | Morning | Done |
| 5 | Eval with 5 scores: reason code, route, vulnerability, high-risk caught, recommendation | Morning | Done |
| 6 | Baseline and first "after" scores (see the scoreboard) | Morning | Done |
| 7 | Scored Pradeep's reviewer (8/8) and the sofa letter (all rules pass) | Morning | Done |
| 8 | Sourced ROI from UK Finance, FCA, NatWest and Mastercard public figures (about £2M a year, conservative) | Morning | Done |
| 9 | Notebook sections 1–5 and 7, including the sofa case end to end with the review loop | Morning | Done |
| 10 | Notebook sections 6 (results table) and 8 (next steps) | Before lunch | Done |
| 11 | Slide notes: content per slide, demo script, Q&A answers, sources (`SLIDE_NOTES.md`) | Before lunch | Done |
| 12 | Pull Miriam's and Pradeep's fixes; final eval, run twice | About 14:30 | Done (Pradeep ran it twice: no misses) |
| 13 | Score all 8 letter cases with the real agent | About 14:30 | Done (8 / 8) |
| 14 | **Slides** from the LangChain template (`HACK_NATWEST_THEFRIENDLYFRAUDSTERS`) | About 15:15 | Done; put the final scoreboard in |
| 15 | Final commit and push | Before 15:45 | To do |

## Pradeep: quality review agent, then Task 2, graph and routing

- [x] `quality_review` with the 8-point checklist and send-back targets (**8/8** on the test packs)
- [x] New fields in `utils/state.py`
- [x] Review loop in `agent.py`: fail → send back with feedback, at most 2 retries, then to the human
- [x] `vulnerability_check` after `load_case`, with the **high-risk fast lane** to a human (crisis cases now 2/2)
- [x] Approval screen shows the vulnerability level
- [x] Triage counts only undisputed earlier purchases; reviewer sees the agent's own findings
- [x] **CMP-019 trap (fixed):** real fraud routed to friendly fraud. An unknown device + failed 3-D Secure should block the friendly-fraud route
- [x] Classifier on mixed problems (fixed): CMP-016 ("I think they charged me twice", but the data shows one payment) and CMP-018 (4am foreign payment framed as a cancelled subscription). Weigh the payment data over the customer's wording
- [x] Keep `main` running end to end; merge teammates' pull requests (all merged; all 25 cases run end to end)
- [x] Evidence pack gets the earlier purchases and past disputes; the reviewer no longer fails reasonable reason codes or plain anger. Packs passing review first time: 12 / 23 → 22 / 23; slowest case 83 s → 25 s

## Wasiu: customer letter agent, then Task 4, memory, approval and demo

- [x] Customer letter agent (`utils/customer_letter.py`, step `write_customer_letter`): letter type from the outcome, Ombudsman on declines, never accusing, gentler for vulnerable customers, fast-lane holding message without the AI
- [x] 63 tests built on the letter test set; the sofa letter passes every rule with the real agent
- [x] **Test runs no longer pollute the data:** outcomes are saved in LangGraph's memory store (`tools/memory.py`), not `data/dispute_history.jsonl`; tests and evals save nothing
- [x] Memory visible on repeat disputes: the approval screen shows "This customer has lost 2 earlier fraud claims (...)" and earlier cases handled by the agent
- [ ] ~~Slides~~: **moved to Asia** (content in `SLIDE_NOTES.md`): problem and who it helps → how it works → live demo → results (scoreboard, ROI) → how we built it. Name: `HACK_NATWEST_THEFRIENDLYFRAUDSTERS`
- [x] Demo runbook in `DEMO.md` (step by step in LangSmith Studio): CMP-003 (sofa, vulnerable, review loop), CMP-004 (friendly-fraud decline, memory), CMP-011 (crisis fast lane)
- [ ] Rehearse to under 5 minutes

## Miriam: Task 3, specialists and evidence pack

**Please push a branch soon, even unfinished, and pull `main` first.** Pradeep is also editing `utils/nodes.py`, so consider putting new prompts in `utils/specialists.py` to avoid merge conflicts.

- [x] **Merchant specialist:** only CMP-015 is still declined ("I thought I'd stopped that"). In a real chargeback the customer's credible account is enough to raise one; decline only when the evidence *contradicts* the customer
- [x] **Fraud specialist:** country vs home, unknown device, failed 3-D Secure, odd hour
- [x] **Friendly-fraud specialist:** fair and careful, never accusing
- [x] Use the vulnerability level: consider refunding while investigating if the customer can't afford the loss
- [x] Evidence pack sections: Summary, Reason code, Transaction details, Evidence, Customer history, **Vulnerability**, Recommendation
- [x] Reviewer feedback reaches the specialists and the evidence pack (wired by Pradeep)
- [x] Test: `uv run python -m evals.run_evals`. Recommendation **23 / 23**
- [x] Merged (PR #13)

---

## The notebook (`dispute_agent.ipynb`)

The judges' proof that the agent works: they can open it on GitHub and see the outputs without running anything.

| Section | What it shows | Status |
| --- | --- | --- |
| 1. The problem | Disputes, and who it helps (the disputes team) | Done |
| 2. Setup | Loads the data and `.env` | Done |
| 3. The dataset | Table of the 25 cases, data checks, both test sets | Done |
| 4. One case end to end | The sofa case: vulnerability check, review loop, human pause, approval, letter | Done |
| 5. Evals | Before and after table, every miss explained | Done (final numbers after the last eval) |
| 6. Results | KYC-style results table, every miss explained | Done (final numbers after the last eval) |
| 7. KPIs and ROI | Sourced figures and the £2M estimate | Done |
| 8. Next steps | What we'd build next | Done |

## KPIs and ROI

**Quality KPIs** (measured by the evals):

- Reason code correct: **25 / 25**
- Route correct: **25 / 25**
- **Missed high-risk vulnerable customers: 0** (2 / 2 caught)
- False vulnerability alarms: **0** (vulnerability flag 25 / 25)
- Planted mistakes caught by the quality reviewer: **6 / 6** (and both good packs passed)
- Letters passing every rule: **8 / 8**

**Speed and cost KPIs** (measured from LangSmith traces): time per case (**median 17 s for the full graph, slowest 25 s**), tokens and cost per case.

**ROI:**

```
Saving per case = (manual minutes − human review minutes with agent) × analyst cost per minute − AI cost per case
Annual saving   = saving per case × cases per year
```

| Number | Where it comes from |
| --- | --- |
| AI time and cost per case | **Measured** in the evals |
| Human review minutes with the agent | **Assumption.** A human still approves every case: this is the time to read the evidence pack |
| Manual minutes per case | **Assumption**, or a public figure if we find a source |
| Analyst cost per hour | **Assumption** |
| Cases per year | **Assumption**, e.g. a mid-sized UK bank |

**Public figures (all verified from the source pages, no internal data):**

| Figure | Value | Source |
| --- | --- | --- |
| UK remote purchase (card-not-present) fraud cases, 2024 | nearly **2.6 million** (up 22%), losses just under £400M | [UK Finance, Annual Fraud Report 2025 press release](https://www.ukfinance.org.uk/news-and-insight/press-release/fraud-report-2025-press-release) |
| UK confirmed unauthorised fraud cases, 2024 | **3.13 million**, £722M lost | UK Finance, as above |
| Complaints to UK firms, 2025 H2 | **1.74M** total; credit cards 218,456; current accounts 492,149; **55.5% upheld** | [FCA aggregate complaints data 2025 H2](https://www.fca.org.uk/data/aggregate-complaints-data-2025-h2) |
| NatWest share of UK current accounts | **16.5%**, 19M Retail Banking customers (Dec 2025) | [NatWest Group investment case](https://investors.natwestgroup.com/our-investment-case) |
| Cost for a bank to process one dispute | **$9.08–$10.32** (US benchmark) ≈ £7.20–£8.15 at $1 ≈ £0.79 | [Mastercard, true cost of a chargeback](https://www.mastercard.com/gb/en/news-and-trends/Insights/2025/what-s-the-true-cost-of-a-chargeback-in-2025.html) |
| Consumers who have mistakenly disputed a real purchase | **48%** (supports our friendly-fraud design) | Mastercard, as above |

**ROI estimate (fraud disputes only, so conservative):**

| Step | Figure | Type |
| --- | --- | --- |
| UK card-not-present fraud cases a year | 2.6M | Sourced |
| NatWest's share, if fraud is proportional to current-account share | 16.5% → about **430,000 cases a year** | Assumption (sourced share) |
| Cost per dispute | about **£7.70** | Sourced (US benchmark) |
| Handling effort removed by the agent (a human still reviews every case) | **60%** | Assumption, team to agree |
| AI cost per case | measured from LangSmith traces | Measured |
| **Estimated saving** | 430,000 × £7.70 × 60% ≈ **£2M a year**, minus AI cost | |

Caveats to say out loud: the cost figure is a US benchmark; merchant disputes and friendly fraud are **not** counted, so the real figure is likely higher; UK Finance published 2025 figures on 25 Nov 2026 that we have not yet checked. Beyond money: faster answers, consistent vulnerable-customer care, and no missed 8-week deadlines.

Label every assumption clearly on the slide. The saving comes from **faster investigation, not removing the human**: that's honest, and a good answer for Q&A.
