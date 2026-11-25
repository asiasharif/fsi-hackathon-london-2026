# Slide notes: The Friendly Fraudsters | NatWest

Content for each slide of the LangChain **FSI Hackathon Submission Template**, in order. Save the deck as **`HACK_NATWEST_THEFRIENDLYFRAUDSTERS`**. Deadline: **15:45** (fork link and slides). Demo: 5 minutes plus Q&A at 16:00.

Numbers are from the final eval (14:15, all agents merged; same result on 2 runs). Every figure has a source, so we can answer "where's that from?" in Q&A.

---

## Slide 1: Title

- **Team and company name:** The Friendly Fraudsters | NatWest
- **Names line:** Asia Sharif · Pradeep Senguttuvan · Wasiu Ademola Adekola · Miriam Lobete · FSI Hackathon · 25 November 2026

## Slide 2: The team

**The Friendly Fraudsters · NatWest**

| Name | Role | What they owned today |
| --- | --- | --- |
| Asia Sharif | Data and evals | Test data (25 labelled cases), evals and LangSmith experiments, ROI, notebook, slides |
| Pradeep Senguttuvan | Graph and routing | Quality reviewer, graph and routing, vulnerability check and crisis fast lane |
| Wasiu Ademola Adekola | Customer comms and demo | Customer letter agent, human approval, demo |
| Miriam Lobete | Specialist agents | Fraud, merchant and friendly-fraud specialists, evidence pack |

Roles as on the final deck.

## Slide 3: What we're solving

- **Heading (pick one):** Bring your own: **card dispute and chargeback handling**
- **One-line framing:** A team of AI agents that investigates "I didn't make this payment" disputes, recommends what to do, checks its own work, and hands every decision to a human, with extra care for vulnerable customers.

## Slide 4: The problem

**Who's affected, and why it matters**

- **Who:** the bank's disputes operations team, and customers waiting for their money back
- **What:** every dispute is read, classified, investigated and written up by hand, and a letter is written; telling real fraud from "friendly fraud" (the customer's own or a family member's purchase) is slow and inconsistent
- **Why now:** UK card-not-present fraud cases rose **13% to 3.2 million** in 2025 (UK Finance, June 2026). **49%** of UK adults show signs of vulnerability (FCA Financial Lives 2024). Also: **48%** of consumers have mistakenly disputed a real purchase (Mastercard). The FCA's Consumer Duty requires good outcomes for vulnerable customers, within **8 weeks**

**Right-hand box (the concrete example):**
> *"After everything this year I feel like there's no way out. Now £400 has gone to something called LuxeStay and I just can't face dealing with it."*

The customer never mentions self-harm. Our agent recognises crisis language and sends the case **straight to a human**, skipping the investigation.

## Slide 5: Our CCC approach

**Customer, colleague, company: everyone wins**

**Top box:** We judged every design choice by three groups: **the customer, the colleague and the company.** Customers get a fast, fair answer, colleagues get a case ready to decide, and NatWest cuts cost while meeting Consumer Duty.

| Card | Line | Proof point |
| --- | --- | --- |
| **Customer** | Fast, fair answers; a person on every crisis | Crisis to a human in under 5 s |
| **Colleague** | The agent investigates; the analyst decides | 22 / 23 packs ready first time |
| **Company** | Lower cost, fewer wrong chargebacks | ≈ £2.4M a year + Consumer Duty |

**What to say (about 30 s):**
- **Customer:** half of UK adults show signs of vulnerability (FCA Financial Lives, 49%), so crisis cases go to a person in under 5 seconds (our CMP-011 run: 4.8 s), letters never accuse, and every decline names the Financial Ombudsman.
- **Colleague:** the agent does the reading, classifying and write-up; the analyst gets a decision-ready evidence pack (22 of 23 pass our quality reviewer first time) and makes the call. The AI never decides alone.
- **Company:** about £2.4M a year on card-not-present fraud disputes alone (slide 9), fewer wrong chargebacks from friendly fraud (48% of consumers have mistakenly disputed a real purchase, Mastercard), and an audit trail for Consumer Duty and the 8-week deadline.

Icons: hand with heart (customer), person in a tie (colleague), bank building (company), in the deck's blue.

## Slide 6: How we built it

**Architecture, flow, and what's underneath**

**Left box:** screenshot of the graph in LangSmith Studio (`uv run langgraph dev`), showing all the steps and the review loop.

- **Working flow:** load case → **vulnerability check** (crisis → fast lane to a human) → classify reason code → triage rules → fraud / merchant / friendly-fraud **specialist** → evidence pack → **quality reviewer** (sends weak packs back to the step that caused the problem, max 2 retries) → **human approval** → **customer letter** → save to customer memory
- **Controls / evals:**
  - Human-in-the-loop: every case pauses for a person (`interrupt()`); the AI never decides alone
  - **PII-redaction middleware** (LangChain) on the classifier: names, card numbers, emails, UK phone numbers and sort codes are removed before the text reaches the model
  - The quality reviewer checks every evidence pack against the raw data (8 / 8 on planted mistakes)
  - Triage is plain Python rules, so routing is repeatable and auditable
  - LangSmith evals on 25 labelled cases, before and after every change
  - The crisis holding letter uses no AI at all; every decline mentions the Financial Ombudsman

**Tools & libraries used:** LangGraph · LangChain middleware (PII redaction) · LangSmith (tracing, datasets, experiments) · LLM Gateway · Pydantic. (Remove "Deep Agents" from the template line: we didn't use it.)

**GitHub link:** https://github.com/asiasharif/fsi-hackathon-london-2026 (code in `the_friendly_fraudsters/`)

## Slide 7: How we built it, more detail (optional)

- **Left box:** screenshot of the LangSmith trace for CMP-003 (the sofa case), showing the quality reviewer **rejecting the first evidence pack and passing the rewrite**, then the pause for a human. Find it under Tracing Projects → `fsi-hackathon-Asia Sharif`.
- **Right box, design choices:**
  - Vulnerability changes *how* we handle a case, not *whether* the customer is right
  - An unknown device or a failed 3-D Secure blocks the "friendly fraud" route, so real fraud victims are never wrongly declined
  - Friendly fraud is often a family member: letters never accuse

## Slide 8: What we got

**Outcome, evidence, and the value it creates**

| Metric | Before (starter agent) | With our agent |
| --- | --- | --- |
| **Crisis customers sent straight to a human** | 0 / 2 | **2 / 2** |
| Vulnerable customers spotted correctly | 24 / 25 | **25 / 25** |
| Dispute type (reason code) correct | 23 / 25 | **25 / 25** |
| Sent to the right specialist | 21 / 25 | **25 / 25** |
| Right action recommended | 19 / 23 | **23 / 23** |
| Planted mistakes caught by the reviewer | n/a | **8 / 8** |
| Letters passing every rule (8 scenarios, real agent) | n/a | **8 / 8** |
| All 25 cases run end to end, through to the letter | n/a | **25 / 25, no errors** |
| Evidence packs passing review first time | 12 / 23 | **22 / 23** |
| Time per case, full graph | n/a | median 17 s (slowest 25 s) |

Small note under the table: *25 hand-labelled synthetic cases, including traps: vague complaints, mixed problems, lookalikes, and anger that isn't vulnerability. Investigation takes about 5 s per case; the full graph (evidence pack, review and letter) has a median of 17 s.*

**Right box:** screenshot of the LangSmith experiment comparison (Datasets & Experiments → `friendly-fraudsters-disputes-v3`), baseline vs latest.

**If asked "is 100% realistic?":** it's 25 synthetic cases we designed, including traps. It shows the agent handles every situation we tested, not that it's perfect in production, and every case still goes to a human.

## Slide 9: Business value and what's next (optional)

- **Business value:** about **£2.4M a year** saved on card-not-present fraud disputes alone: 3.2M UK cases in 2025 (UK Finance) × NatWest's 16.5% current-account share (NatWest Group) × about £7.70 per dispute (Mastercard, US benchmark) × 60% of handling effort removed (**our assumption**: a human still approves every case). Plus faster answers, consistent vulnerable-customer care and no missed 8-week deadlines. Merchant disputes and friendly fraud aren't counted, so the real figure is likely higher.
- **Next step:**
  - A bigger, harder test set with real-world volumes
  - A "request more information" outcome instead of declining
  - Tracking the FCA 8-week deadline on every open case
  - An LLM judge for letter tone, online evals and a human annotation queue in LangSmith
  - Tracking the FCA 8-week deadline on every open case

## Slide 10: Questions?

**The Friendly Fraudsters · https://github.com/asiasharif/fsi-hackathon-london-2026**

---

## Live demo script (about 2 minutes, LangSmith Studio)

Before the demo: `cd the_friendly_fraudsters && uv run langgraph dev`. Start case 004 while you talk, because it takes about 35 seconds.

1. **CMP-004: Tom, "This PixelGames charge isn't me"** (friendly fraud, about 75 seconds). Input `{"complaint_id": "CMP-004"}`. Show:
   - vulnerability check → **none**
   - triage → **friendly fraud**, with its three reasons: an earlier purchase at the shop, his own device + 3-D Secure, 2 lost fraud claims
   - friendly-fraud specialist → **decline**
   - quality reviewer **fails the first pack → rewrite → passes** (agents checking each other)
   - **pause for a human:** the approval screen shows memory, *"This customer has lost 2 earlier fraud claims"*
   - resume with `{"decision": "approve", "notes": "ok"}`, then the letter: a gentle decline, **"This doesn't mean we think you've done anything wrong"**, Financial Ombudsman, 14 days to send more information
2. **CMP-011: Jordan, "I can't cope with any of this anymore"** (crisis, about 30 seconds). Input `{"complaint_id": "CMP-011"}`. Show:
   - vulnerability check → **HIGH** → straight to a human (**fast lane**; the investigation is skipped, 2 seconds vs 35)
   - the **fast-lane screen**: a banner *"High-risk vulnerable customer. Contact them now; the investigation is on hold"*, the vulnerability reasons and the customer's words. Resume with `{"decision": "contacted", "notes": "Called the customer"}` (the choices here are `contacted` or `escalated`, not approve)
   - the holding letter, written **without AI**: a person will call within 24 hours, **Samaritans 116 123**, 999 if in danger
3. **Close on slide 8** (the scores).

**Backup:** if Studio is slow or fails, open `dispute_agent.ipynb` section 4 (full sofa run with outputs saved).

## Likely Q&A

- **"Is the ROI real?"** Volumes and costs are public (UK Finance, NatWest, Mastercard). The 60% is our assumption and is labelled as such. We counted one fraud type only.
- **"Why not let the AI decide?"** A wrong decline harms customers and breaks Consumer Duty. The saving comes from faster investigation, not removing people.
- **"How do you know it works?"** 25 labelled cases including deliberate traps, scored in LangSmith before and after every change, plus 8 planted-mistake packs for the reviewer.
- **"Do scores vary?"** Earlier versions moved by ±1 between runs; the final version scored the same on two runs.
- **"Did you use middleware / Deep Agents?"** Middleware, yes: PII redaction on the classifier, so customer names and card details never reach the model (proven by capturing the model's input). Deep Agents, not yet: we chose a LangGraph workflow because disputes need auditable, repeatable routing. Making each specialist a Deep Agent is our next step.
- **"Is this real data?"** No, all synthetic, as the rules require.

## Sources

- [UK Finance: Fraud continues to pose a major threat with over £1 billion stolen in 2024](https://www.ukfinance.org.uk/news-and-insight/press-release/fraud-report-2025-press-release)
- [FCA: Aggregate complaints data 2025 H2](https://www.fca.org.uk/data/aggregate-complaints-data-2025-h2)
- [NatWest Group: Our investment case](https://investors.natwestgroup.com/our-investment-case)
- [Mastercard: What's the true cost of a chargeback for businesses?](https://www.mastercard.com/gb/en/news-and-trends/Insights/2025/what-s-the-true-cost-of-a-chargeback-in-2025.html)
