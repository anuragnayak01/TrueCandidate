# Sherlock — AI Candidate Identification Engine

> **Sherlock** is a real-time AI system that identifies the interview candidate
> among all meeting participants using **seven independent weak signals** fused
> via a weighted-average + softmax pipeline.

---

## Quick Start

### 1 — Install dependencies

```bash
pip install -r requirements.txt
```

### 2 — Run the server

```bash
cd backend
python server.py
```

The server starts at **http://localhost:8765**.

### 3 — Open the dashboard

Navigate to **http://localhost:8765** in your browser.

Pick a scenario from the dropdown and click **▶ Run Demo**.

---

## Architecture

```
Meeting platform events  (join, speak, transcript, screen-share, name-change)
         │
         ▼
CandidateIdentificationEngine          ← backend/engine.py
  │   Per-participant rolling state
  │   (ParticipantState dataclass)
  │
  ├── 7 Signal Analyzers               ← backend/signals.py
  │     ├── Name Match          (weight 20%)
  │     ├── Email Match         (weight 30%)
  │     ├── Interviewer Exclusion (weight 25%)
  │     ├── Speaking Pattern    (weight 12%)
  │     ├── Transcript Language (weight  7%)
  │     ├── Join Order          (weight  4%)
  │     └── Screen Share        (weight  2%)
  │
  └── Fusion Layer
        ├── Weighted average of (signal_score × signal_confidence)
        ├── Softmax with temperature (T=0.25) for sharp separation
        ├── Ambiguity check (gap < 12% between top-2 → ambiguous)
        └── Human-readable explanation builder

         │
         ▼
WebSocket broadcast  ── Live Dashboard (HTML/CSS/JS)
   (FastAPI)               Confidence bars + signal breakdown
                           Event log + identification summary
```

---

## Demo Scenarios

| Scenario | Difficulty | Description |
|---|---|---|
| 🟢 Happy Path | Easy | Candidate joins with real name + email |
| 🟡 Nickname | Medium | Candidate joins as "Mike" (ATS: "Michael Chen") |
| 🔴 Device Name | Hard | Candidate joins as "MacBook Pro", then renames |
| 🔴 Panel + Observers | Hard | 3 interviewers, 2 silent observers, 1 candidate |
| 🟡 Name Change | Medium | Candidate starts as "iPhone", reveals identity in transcript |
| 🔴 No ATS Data | Hard | No candidate name or email — speech-pattern only |

---

## Signal Design

### Why multiple weak signals?

No single signal is reliable enough in isolation:

| Signal | Strength | Failure Mode |
|---|---|---|
| Email Match | Very High | Email not exposed by platform |
| Interviewer Exclusion | High | Unknown interviewers |
| Name Match | Medium | Nicknames, device names |
| Speaking Pattern | Medium | Short/unstarted interviews |
| Transcript Language | Low-Med | Low transcript volume |
| Join Order | Low | Eager candidates join first |
| Screen Share | Very Low | Candidate shares code |

Combining them using weighted evidence fusion is robust to individual failures.

### Confidence Interpretation

| Range | Meaning |
|---|---|
| 0–40% | Unlikely candidate |
| 40–65% | Inconclusive |
| 65–85% | Probable candidate |
| ≥85% | **LOCKED** — high-confidence identification |

---

## File Structure

```
sherlock-candidate-id/
├── backend/
│   ├── models.py       Data models (events, participants, results)
│   ├── signals.py      7 signal analyzers
│   ├── engine.py       CandidateIdentificationEngine + fusion
│   ├── scenarios.py    6 demo scenarios with realistic event timelines
│   └── server.py       FastAPI + WebSocket server
├── frontend/
│   └── index.html      Single-page real-time dashboard
├── requirements.txt
└── README.md
```

---

## Assumptions

1. The system has access to a **separate audio/video stream per participant** — it does not need to demix a combined stream.
2. **ATS metadata** (candidate name, email, interviewer list) is available at meeting start, but may be incomplete or incorrect.
3. **Email addresses** are sometimes exposed by the meeting platform (e.g. through Google Meet's participant API) and sometimes not.
4. The **transcript** is speaker-attributed (e.g. via Whisper + diarisation, or platform-native transcription).
5. Events are ingested in real-time with sub-second latency.

---

## Trade-offs

- **No external API calls** — all signals run in pure Python for maximum portability and zero cost at demo time. In production, you'd add a vision-based face-match signal and an LLM-powered transcript classifier for higher accuracy.
- **Softmax temperature** (T=0.25) creates sharp winner-takes-most behaviour which looks clean in the UI but can be slow to recover if an early strong wrong signal fires. A higher temperature gives more graceful uncertainty.
- **Ambiguity gap** (12%) is a tunable threshold — lower = more cautious, higher = faster identification.

---

## What to Improve Next

1. **LLM-powered transcript analysis** — GPT/Gemini to classify speech intent rather than regex patterns.
2. **Face/voice embedding** — match webcam frame embeddings against LinkedIn profile photo.
3. **Bayesian update** rather than full recomputation — incremental belief update per event.
4. **Feedback loop** — if the interviewer addresses someone by the candidate's name, use that as a confirmation signal.
5. **Platform SDK integration** — real Google Meet / Zoom / Teams event webhooks.

---

## Testing

Run the six built-in demo scenarios in the dashboard. Each scenario is designed to stress-test specific signals:

- **Happy Path**: all signals fire correctly — expect 95%+ confidence within 5 events.
- **Nickname**: name match starts low; transcript + speaking pattern converge to ~80% by event 12.
- **Device Name**: name match fires negative immediately; transcript rescues identification.
- **Panel**: interviewer exclusion eliminates 3 known interviewers; email match confirms candidate.
- **No ATS Data**: only speaking pattern + transcript available; expect slower convergence to ~70%.
