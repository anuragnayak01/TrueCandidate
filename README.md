 

# TrueCandidate(Sherlock) :  Real-Time Interview Candidate Identification

Sherlock identifies the actual interview candidate among all participants in
a live meeting — even when they join under the wrong name, a device name
("MacBook Pro"), a nickname, or when the ATS/scheduling data itself is
wrong — and flags it when someone else appears to be answering on the
candidate's behalf.

It fuses **9 independent weak signals** (2 of them biometric, pre-enrolled
before the meeting) into a single confidence score via a weighted average +
temperature-scaled softmax, and separately hard-triggers a fraud alert when
face and voice biometrics actively disagree with each other.

---

## How it works, end to end

```
 BEFORE THE MEETING                    DURING THE MEETING
 ───────────────────                   ──────────────────

 Recruiter fills in the        Zoom sends webhook events
 "New Case Intake" form   ──▶  (participant joined/left)  ──┐
 on dashboard/index.html       to /api/zoom/webhook           │
   • candidate name/email                                     │
   • interviewer name/email    zoom_bot.py (optional,          ├──▶ engine.py
   • candidate photo      ──▶  Playwright) reports              │   fuses 9
     → face embedding           speaking_start/end +            │   signals,
   • ~20s voice clip      ──▶   face/voice samples to           │   softmax,
     → voice embedding          /api/meeting/{id}/event ──────┘   ambiguity +
                                                                    mismatch
                                                                    checks
        stored on a MeetingContext,           │
        keyed by the Zoom meeting ID          ▼
                                    dashboard/index.html
                                    (WebSocket /ws/{id})
                                    live confidence + evidence
                                    breakdown per participant
```

Two independent event sources feed the same session, keyed by the same
`meeting_id` (the real Zoom numeric meeting ID) and the same
`participant_id` (see `stable_pid()` — a deterministic hash of display name,
shared by the webhook handler and `zoom_bot.py`, so both sources land on
the same participant instead of creating duplicates):

- **Zoom webhook** (`/api/zoom/webhook`) — authoritative for
  participant join/leave. Always available, no bot required, uses real
  Zoom participant data.
- **`zoom_bot.py`** (optional, Playwright-based) — joins the meeting via
  the Zoom web client to observe things webhooks don't carry: speaking
  activity, and (if you wire up capture) face frames for the biometric
  signals.

You can run either alone or both together. Webhook-only gives you Name
Match, Email Match, Interviewer Exclusion, and Join Order. Adding the bot
(or pre-enrolled biometrics) unlocks Speaking Pattern, Face Match, and
Voice Match — see [Signal coverage by data source](#signal-coverage-by-data-source)
below.

---

## The 9 signals

| Signal | Weight | Data source | Notes |
|---|---|---|---|
| Face Match | 0.35 | Pre-enrolled photo + live face frames | Blended, not a hard override — see [Fusion design](#fusion-design) |
| Voice Match | 0.22 | Pre-enrolled ~20s clip + live voice samples | |
| Email Match | 0.13 | Intake form + Zoom participant email | Only available if the participant is logged into Zoom |
| Interviewer Exclusion | 0.11 | Known interviewer list (fuzzy match) | |
| Name Match | 0.09 | Intake form + Zoom display name | Fuzzy matching, device-name penalty ("MacBook Pro") |
| Speaking Pattern | 0.05 | Bot-observed speaking activity | Requires `zoom_bot.py` — webhooks don't carry this |
| Transcript Language | 0.03 | Live transcript segments | No native real-time transcript from Zoom webhooks — requires a separate captioning/transcript integration |
| Join Order | 0.015 | Join sequence | |
| Screen Share | 0.005 | Zoom sharing_started/ended webhook (if subscribed) | |

Weights sum to exactly 1.0. Each signal returns a `(score, confidence)`
pair — a signal with no data available (e.g. Face Match before any photo
is enrolled) contributes `signal_confidence=0`, so it's excluded from the
weighted average entirely rather than dragging the score down. This is
what makes missing data degrade gracefully instead of breaking
identification.

### Fusion design

Composite score per participant = confidence-weighted average of all 9
signals → **softmax** (temperature 0.25) across all participants turns
scores into a probability distribution → if the top-two probabilities are
within 12%, the result is reported as **ambiguous** rather than guessing.

Face and Voice Match are **blended into this average, not a hard
override** — a single bad frame or noisy clip shouldn't be able to
unilaterally flip the decision. The one deliberate exception: if Face
Match and Voice Match are both confident but **disagree** with each other
(one says match, the other says no-match), that's escalated as a separate
`IDENTITY_MISMATCH` fraud flag — shown as a distinct red banner on the
dashboard — rather than quietly averaged into a mediocre score.

---

 

## Setup

### 1. Backend (Render)

```bash
git clone https://github.com/anuragnayak01/TrueCandidate.git
cd TrueCandidate
```

Render (`render.yaml`) uses its native Python runtime — `buildCommand`
installs `requirements.txt` + Playwright's Chromium, `startCommand` runs
`cd backend && python server.py`. It does **not** use the `Dockerfile`
(that file is currently stale — see Known limitations).

**Environment variables to set on Render** (Settings → Environment):

| Variable | Required for | Notes |
|---|---|---|
| `ZOOM_WEBHOOK_SECRET_TOKEN` | Zoom webhook signature verification + CRC handshake | **Exact name matters** — `render.yaml`'s comment currently says `ZOOM_WEBHOOK_SECRET`, which is wrong; the code reads `ZOOM_WEBHOOK_SECRET_TOKEN`. Get this from your Zoom Marketplace app's Feature → Access page. |
| `PORT` | Already set in `render.yaml` | |
| `GMEET_BOT_EMAIL` / `GMEET_BOT_PASSWORD` | Only if using `gmeet_bot.py` for Google Meet | Not needed for Zoom-only setups |

Health check path is `/api/scenarios` (already configured in `render.yaml`).

### 2. Dashboard (`dashboard/index.html`)

This is a single static HTML file — deploy it anywhere that serves static
files (Vercel, Netlify, GitHub Pages, or just open it locally). No build
step. On load, it reads the **Backend URL** field (defaults to your Render
URL — edit the default value in the `#apiBase` input if yours differs)
directly from the page, not from a hardcoded config, so one deployed copy
works against any backend URL you type in.

### 3. Local development

```bash
cd backend
pip install -r requirements.txt
python server.py   # runs on :8765
```

Open `dashboard/index.html` directly in a browser, set Backend URL to
`http://localhost:8765`.

---

## Zoom App configuration (webhook)

1. Create an app at [marketplace.zoom.us](https://marketplace.zoom.us) →
   **Webhook Only** app type (no OAuth scopes needed for this).
2. Under **Feature → Access**, copy the **Secret Token** → set it as
   `ZOOM_WEBHOOK_SECRET_TOKEN` on Render.
3. Under **Feature → Event Subscriptions**, add your endpoint URL:
   ```
   https://<your-render-app>.onrender.com/api/zoom/webhook
   ```
4. Subscribe to at minimum: `Meeting Participant/Host has joined`,
   `Meeting Participant/Host has left`. Add sharing/recording events if
   you plan to extend `_ZOOM_EVENT_MAP` in `server.py` for them.
5. Click **Validate** — Zoom sends an `endpoint.url_validation` request;
   the server answers it automatically (see `server.py`'s CRC handler).
   This validation re-runs periodically, not just once — the endpoint
   needs to stay up.

**Important:** the numeric Zoom Meeting ID is what routes webhook events
to the right session — it must be the *same* ID entered in the dashboard's
"New Case Intake" form (`ic_meetingId`) before the meeting starts.
Recurring meetings reuse the same numeric ID across occurrences (Zoom
disambiguates via a separate `uuid` field) — for one-off interview
meetings, the primary use case here, this is fine.

---

## Pre-meeting candidate intake

The dashboard's **New Case Intake** form does all of this in one step
before the interview happens:

1. Creates the session (`POST /api/meeting/live`), keyed by the Zoom
   meeting ID.
2. If a photo and/or ~20s voice clip is attached, enrolls biometrics
   (`POST /api/meeting/{id}/enroll`) — `biometrics.py` extracts a face
   embedding (OpenCV Haar-cascade + normalized pixel descriptor) and/or a
   voice embedding (librosa MFCC mean/std), validates that a face was
   actually detected / real speech was actually present, and **discards
   the raw photo/audio immediately** — only the embedding vector is kept,
   in memory, for the lifetime of that session.

Both steps are idempotent — safe to call again (e.g. to add biometrics in
a second pass) without losing anything already entered.

---

## API reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/scenarios` | GET | List built-in demo scenarios |
| `/api/meeting/start` | POST | Start a demo scenario replay (`{scenario: key}`) |
| `/api/meeting/live` | POST | Pre-meeting intake — create a session for a real meeting |
| `/api/meeting/{id}/enroll` | POST | Biometric enrollment (`photo_b64`, `audio_b64`) |
| `/api/meeting/{id}` | GET | Snapshot fetch (context + current state) |
| `/api/meeting/{id}/event` | POST | Live event ingestion, used by `zoom_bot.py`/`gmeet_bot.py` |
| `/api/meeting/{id}/end` | POST | End a session, notify connected dashboards, clear state |
| `/api/zoom/webhook` | POST | Zoom Event Subscriptions endpoint |
| `/ws/{id}` | WebSocket | Live identification stream, consumed by `dashboard/index.html` |
| `/api/health` | GET | Health check |

---

  
 
## Assumptions

- Interviews are scheduled as one-off (non-recurring) Zoom meetings, so the
  numeric Meeting ID uniquely identifies one interview.
- The person doing pre-meeting intake knows the Zoom Meeting ID in advance
  (from the calendar invite) at the time they fill in the intake form.
- Candidate consent for biometric enrollment is obtained outside this
  system, before a photo/voice clip is submitted — this repo does not
  implement a consent-collection flow.
