# Live demo runbook (LangSmith Studio)

About 2 minutes. Slide content, numbers and Q&A are in `SLIDE_NOTES.md`.

## Before you go on stage

```bash
cd ~/team-dispute-agent/the_friendly_fraudsters
git pull origin main
uv run langgraph dev
```

- Studio opens in the browser. Select the graph **card_dispute_agent**
- Run CMP-004 once beforehand, so the memory line shows "Handled by this agent before" on stage
- Keep screenshots of the three letters on the demo slide in case the Wi-Fi or the model is slow

## Case 1: the sofa (CMP-003): vulnerable customer, normal flow (about 50 s)

1. Input `{"complaint_id": "CMP-003"}` and run
2. **Say:** "Amara paid £820 for a sofa that never arrived, and wrote 'I'm really struggling'."
3. Point at the steps lighting up: vulnerability check flags **medium**, classified as goods not received, merchant specialist, evidence pack, **quality reviewer** (if it sent the pack back, show the retry: agents checking agents)
4. The graph **pauses at human approval**. Show the top of the screen: vulnerability, then memory, then the recommendation (file a chargeback)
5. Resume with `{"decision": "approve", "notes": ""}`
6. Show the letter: plain English, what happens next and when, the free support line, "no pressure or rush"

## Case 2: friendly fraud (CMP-004): memory, never accusing (about 40 s)

1. Input `{"complaint_id": "CMP-004"}`
2. **Say:** "Tom says 'this isn't me'. But he's bought from PixelGames before, on his own phone, and lost two earlier fraud claims."
3. At approval, point at the **memory line**: "This customer has lost 2 earlier fraud claims", plus the earlier run
4. Approve. Show the letter: says what our records show, gently suggests someone he knows may have used the card, "this doesn't mean we think you've done anything wrong", and his right to go to the Financial Ombudsman

## Case 3: crisis (CMP-011): fast lane (about 30 s)

1. Input `{"complaint_id": "CMP-011"}`
2. **Say:** "Jordan wrote 'I can't cope with any of this anymore'."
3. The graph **skips the whole investigation** and goes straight to a person, marked FAST LANE
4. Resume with `{"decision": "contacted", "notes": "Called the customer"}`
5. Show the message: no decision, a person will call within 24 hours, Samaritans 116 123 and 999. **Say:** "In a crisis, the AI doesn't write anything. This is a fixed, approved message."
