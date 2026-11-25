# Demo script and slides: The Friendly Fraudsters | NatWest

5 minutes, then Q&A. Deck: LangChain template, named `HACK_NATWEST_THEFRIENDLYFRAUDSTERS`.
Numbers are from the TODO.md scoreboard (12:15). **Refresh them from Asia's final eval before 15:45.**

## Timing

| Part | Time | Slide |
| --- | --- | --- |
| The problem | 0:00–0:40 | 1 |
| How it works | 0:40–1:30 | 2 |
| Live demo (3 cases) | 1:30–3:30 | 3 |
| Results and ROI | 3:30–4:30 | 4 |
| How we built it | 4:30–5:00 | 5 |

---

## Slide 1: The problem

**Title:** Card disputes: slow, manual, and easy to get wrong

- 2.6M card-not-present fraud cases in the UK in 2024, up 22% (UK Finance)
- Every dispute needs a person to classify it, pull the evidence, decide and write it up
- 48% of consumers have mistakenly disputed a real purchase (Mastercard): "friendly fraud" is common, and accusing an honest customer is a Consumer Duty risk
- Vulnerable customers need extra care, and a crisis must reach a human straight away

**Say:** "Our user is NatWest's card disputes team. Every 'I didn't make this payment' is minutes of manual work, and the hard part is telling real fraud from a family member's purchase without accusing anyone."

## Slide 2: How it works

**Title:** A team of agents, with a human making every decision

```
load case → vulnerability check ──(high risk)──→ human now (fast lane)
               ↓
classify → triage → fraud | merchant | friendly-fraud specialist
       → evidence pack ⇄ quality reviewer (max 2 rewrites)
       → human approval → customer letter → memory
```

- **Vulnerability check first:** a crisis skips the investigation and goes straight to a person
- **Triage is plain rules**, so routing is explainable and testable
- **Quality reviewer** sends weak evidence packs back with feedback: agents checking agents
- **Human approves or overrides** every decision. The AI never has the final say
- **Customer letter:** code decides the facts, the AI writes the words, guardrails check them (Ombudsman on declines, never accusing, gentler for vulnerable customers)
- **Memory:** the reviewer sees the customer's history; outcomes are saved in LangGraph's store

## Slide 3: Live demo (switch to LangSmith Studio)

See the demo script below. Title on the slide, in case the demo fails: **"Live: sofa, friendly fraud, crisis"** with screenshots of the three letters as backup.

## Slide 4: Results

**Title:** Measured on 25 labelled cases in LangSmith

| Measure | Starter | Now |
| --- | --- | --- |
| Crisis cases sent straight to a human | 0 / 2 | **2 / 2** |
| Vulnerability spotted correctly | 24 / 25 | **25 / 25** |
| Route correct | 21 / 25 | 23 / 25 |
| Reason code correct | 23 / 25 | 23 / 25 |
| Recommendation correct | 19 / 23 | 19–20 / 23 |
| Quality reviewer catches planted mistakes | n/a | **8 / 8** |
| Customer letters passing every rule | n/a | **8 / 8** |

**ROI (conservative, fraud disputes only):** 430,000 cases a year × £7.70 per dispute × 60% effort removed ≈ **£2M a year**, minus AI cost

- Sourced: 2.6M UK CNP fraud cases (UK Finance), NatWest 16.5% share (NatWest), £7.70 per dispute (Mastercard, US benchmark)
- **Assumption:** 60% of handling effort removed. A human still reviews every case: the saving is faster investigation, not removing people
- Beyond money: faster answers, consistent vulnerable-customer care, no missed 8-week deadlines

## Slide 5: How we built it

- **LangGraph:** 12-step graph with conditional routing, a review loop, a human-in-the-loop interrupt and a memory store
- **LangSmith:** tracing for every step, datasets and evals (5 scores), before-and-after scoring
- **Evals as the spec:** 25 labelled cases, 8 evidence-pack test packs, 8 letter scenarios with must / must-not rules
- **69 automated tests**, plus live checks with the real model
- 4 people, 1 day, one shared state schema agreed in the first hour

**Close:** "Faster disputes, fairer letters, and a human in charge of every decision. Thank you."

---

## Demo script (LangSmith Studio)

### Before you go on stage

```bash
cd ~/team-dispute-agent/the_friendly_fraudsters
git pull origin main
uv run langgraph dev
```

- Studio opens in the browser. Select the graph **card_dispute_agent**
- Run CMP-004 once beforehand, so the memory line shows "Handled by this agent before" on stage
- Keep the three backup letter screenshots on slide 3 in case the Wi-Fi or the model is slow

### Case 1: the sofa (CMP-003): vulnerable customer, normal flow (about 50 s)

1. Input `{"complaint_id": "CMP-003"}` and run
2. **Say:** "Amara paid £820 for a sofa that never arrived, and wrote 'I'm really struggling'."
3. Point at the steps lighting up: vulnerability check flags **medium**, classified as goods not received, merchant specialist, evidence pack, **quality reviewer** (if it sent the pack back, show the retry: agents checking agents)
4. The graph **pauses at human approval**. Show the top of the screen: vulnerability, then memory, then the recommendation (file a chargeback)
5. Resume with `{"decision": "approve", "notes": ""}`
6. Show the letter: plain English, what happens next and when, the free support line, "no pressure or rush"

### Case 2: friendly fraud (CMP-004): never accusing (about 40 s)

1. Input `{"complaint_id": "CMP-004"}`
2. **Say:** "Tom says 'this isn't me'. But he's bought from PixelGames before, on his own phone, and lost two earlier fraud claims."
3. At approval, point at the **memory line**: "This customer has lost 2 earlier fraud claims", plus the earlier run
4. Approve. Show the letter: says what our records show, gently suggests someone he knows may have used the card, "this doesn't mean we think you've done anything wrong", and his right to go to the Financial Ombudsman

### Case 3: crisis (CMP-011): fast lane (about 30 s)

1. Input `{"complaint_id": "CMP-011"}`
2. **Say:** "Jordan wrote 'I can't cope with any of this anymore'."
3. The graph **skips the whole investigation** and goes straight to a person, marked FAST LANE
4. Resume with `{"decision": "contacted", "notes": "Called the customer"}`
5. Show the message: no decision, a person will call within 24 hours, Samaritans 116 123 and 999. **Say:** "In a crisis, the AI doesn't write anything. This is a fixed, approved message."

---

## Q&A prep

| Question | Answer |
| --- | --- |
| What if the AI gets it wrong? | A human approves or overrides every case, and the letter follows the human's decision, not the AI's |
| How do you stop it accusing customers? | Code decides the facts; deterministic guardrails block accusing phrases; if the AI fails twice, a safe template is sent |
| How do you know it works? | 25 labelled cases scored in LangSmith, 8/8 reviewer test packs, 8/8 letter scenarios, 69 tests |
| Is the £2M real? | Sourced inputs, one labelled assumption (60%). Conservative: merchant disputes and friendly fraud are not counted |
| Why not let the AI decide? | Consumer Duty and accountability: the saving is in investigation time, the decision stays with a person |
| What about data privacy? | Synthetic data only. Memory stores only what's needed for the next case |
