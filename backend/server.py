"""
server.py — Sherlock candidate-identification backend.

This is the actual FastAPI app. It was previously missing entirely — this
file used to contain a static dashboard HTML page (moved to
`local_dashboard.html` for local reference), while `Dockerfile` /
`render.yaml` / `fly.toml` all pointed `python server.py` at it as the
entrypoint. Nothing in the repo ever called `engine.process_event()`.

This wires the existing `CandidateIdentificationEngine` (engine.py),
`MeetingContext` / `MeetingEvent` (models.py), and the demo scenarios
(scenarios.py) to the HTTP + WebSocket contract the deployed Vercel
frontend (frontend/index.html) already expects:

    GET  /api/scenarios          -> list of demo scenarios
    POST /api/meeting/start      -> {scenario} -> {meeting_id, context}
    WS   /ws/{meeting_id}        -> streams meeting_event / scenario_complete
    GET  /api/health             -> health check (render.yaml healthCheckPath)

Live (non-scenario) ingestion for meet_bot/gmeet_bot.py and zoom_bot.py is
also included via POST /api/meeting/live and POST /api/meeting/{id}/event,
so real bots have somewhere to send events.

GET /api/meeting/{meeting_id} exposes current context + engine state for
polling clients (the dashboard) that don't go through the WebSocket.

POST /api/zoom/webhook receives Zoom App Marketplace Event Subscriptions
("all meeting events" subscribed). It is authoritative for
participant_join/participant_leave — meet_bot/zoom_bot.py's DOM-scraping
bot deliberately no longer reports join/leave (see zoom_bot.py comments)
to avoid double-counting participants under two different ID schemes. The
webhook and the bot agree on participant_id via `stable_pid()`, a
deterministic hash of the display name, so events from either source land
on the same ParticipantState.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import biometrics
from engine import CandidateIdentificationEngine
from models import EventType, MeetingContext, MeetingEvent
from scenarios import SCENARIOS, get_scenario_events, list_scenarios

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sherlock.server")

app = FastAPI(title="Sherlock Candidate Identification Engine")

# Vercel (dashboard) and Render (this API) are different origins, so this
# needs real CORS — the frontend's same-origin assumption
# (`window.location.origin`) only holds if they're on one domain. Tighten
# `allow_origins` to the exact Vercel URL before shipping this for real.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def stable_pid(name: str) -> str:
    """
    Deterministic participant_id derived from display name, shared by
    zoom_bot.py and the /api/zoom/webhook handler below so that both
    sources of events for the same human land on the same
    ParticipantState. Must NOT use Python's built-in hash() — that's
    randomized per-process (PYTHONHASHSEED) and won't even survive a
    bot restart, let alone match across the bot and the webhook process.
    """
    norm = name.strip().lower()
    return f"zoom-{hashlib.md5(norm.encode()).hexdigest()[:10]}"


class _Session:
    """One live meeting: an engine instance plus (for scenario runs) the
    pre-built event timeline to replay over the WebSocket."""

    def __init__(self, context: MeetingContext, events: Optional[List[MeetingEvent]] = None,
                 speed: float = 8.0) -> None:
        self.engine = CandidateIdentificationEngine(context)
        self.events = events or []
        self.speed = speed
        self.live = events is None  # True for meet_bot/zoom_bot-fed meetings
        self.subscribers: List[WebSocket] = []
        self.created_at = time.time()
        # Previous face embedding per participant, kept here (not on
        # ParticipantState) purely to support the frame-to-frame liveness
        # heuristic in biometrics.check_liveness — it's session/transport
        # state, not identification state.
        self._prev_face_embedding: Dict[str, List[float]] = {}


_SESSIONS: Dict[str, _Session] = {}


# ---------------------------------------------------------------------------
# Scenario endpoints (used by the demo dashboard)
# ---------------------------------------------------------------------------

class StartMeetingRequest(BaseModel):
    scenario: str
    speed: float = 8.0  # playback-speed multiplier; scenario seconds / speed = real seconds


@app.get("/api/scenarios")
def api_list_scenarios() -> List[dict]:
    return list_scenarios()


@app.post("/api/meeting/start")
def api_start_meeting(req: StartMeetingRequest) -> dict:
    if req.scenario not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Unknown scenario '{req.scenario}'")

    context, events = get_scenario_events(req.scenario)
    meeting_id = f"m-{uuid.uuid4().hex[:10]}"
    _SESSIONS[meeting_id] = _Session(context, events, speed=req.speed)
    log.info("started scenario meeting %s (%s, %d events)", meeting_id, req.scenario, len(events))
    return {"meeting_id": meeting_id, "context": context.to_dict()}


class EnrollRequest(BaseModel):
    photo_b64: Optional[str] = None
    audio_b64: Optional[str] = None


@app.post("/api/meeting/{meeting_id}/enroll")
async def api_enroll_biometrics(meeting_id: str, req: EnrollRequest) -> dict:
    """
    Pre-meeting biometric enrollment (Stage A/B/C from the design doc):
      A. Collection    — candidate photo + ~20s voice clip, base64-encoded
      B. Validation     — must actually detect a face / contain real speech,
                           or this rejects rather than silently enrolling junk
      C. Extraction      — embeddings computed here, once
      (D. Delivery is implicit: the embedding is stored on this session's
          MeetingContext, which the WebSocket/live-event handlers already
          read from — nothing further to wire up.)

    The raw photo/audio bytes exist only for the duration of this request —
    they are decoded, embedded, and immediately discarded. Only the
    embedding vector (a few dozen floats) is retained, and only for the
    lifetime of this in-memory session.
    """
    session = _SESSIONS.get(meeting_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown meeting_id")

    result: Dict[str, Any] = {"face_enrolled": False, "voice_enrolled": False, "errors": []}

    if req.photo_b64:
        try:
            photo_bytes = base64.b64decode(req.photo_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="photo_b64 is not valid base64")
        embedding = biometrics.extract_face_embedding(photo_bytes)
        if embedding is None:
            result["errors"].append(
                "No face detected in enrollment photo — rejected, not enrolled. "
                "Re-upload a clear, single-face, front-facing photo."
            )
        else:
            session.engine.context.candidate_face_embedding = embedding
            result["face_enrolled"] = True
        del photo_bytes  # explicit: raw bytes are not retained past this line

    if req.audio_b64:
        try:
            audio_bytes = base64.b64decode(req.audio_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="audio_b64 is not valid base64")
        embedding = biometrics.extract_voice_embedding(audio_bytes)
        if embedding is None:
            result["errors"].append(
                "Voice clip rejected — too short, silent, or undecodable. "
                "Re-record ~20s of clear speech."
            )
        else:
            session.engine.context.candidate_voice_embedding = embedding
            result["voice_enrolled"] = True
        del audio_bytes

    log.info(
        "enrollment for %s: face=%s voice=%s",
        meeting_id, result["face_enrolled"], result["voice_enrolled"],
    )
    return result


# ---------------------------------------------------------------------------
# Live meeting endpoints (for meet_bot / zoom_bot)
# ---------------------------------------------------------------------------

class StartLiveMeetingRequest(BaseModel):
    meeting_id: Optional[str] = None  # bots can supply their own (e.g. Meet code) or omit to get a generated one
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    interviewer_names: List[str] = []
    interviewer_emails: List[str] = []
    # Display-only context (see MeetingContext.to_dict() / dashboard context
    # card) — NOT scored by any signal, purely informational for whoever is
    # reviewing the case file.
    job_title: Optional[str] = None
    company: Optional[str] = None


class LiveEventRequest(BaseModel):
    event_type: str
    participant_id: str
    data: Dict[str, Any] = {}


@app.post("/api/meeting/live")
def api_start_live_meeting(req: StartLiveMeetingRequest) -> dict:
    meeting_id = req.meeting_id or f"m-{uuid.uuid4().hex[:10]}"
    if meeting_id in _SESSIONS:
        # Idempotent: a bot may call this more than once for the same
        # meeting_id (e.g. retry after a dropped connection, or a race with
        # the Zoom webhook's meeting.started event) — don't blow away an
        # in-progress session's accumulated state.
        return {"meeting_id": meeting_id, "context": _SESSIONS[meeting_id].engine.context.to_dict()}
    context_kwargs = dict(
        meeting_id=meeting_id,
        candidate_name=req.candidate_name or "",
        candidate_email=req.candidate_email or "",
        interviewer_names=req.interviewer_names,
        interviewer_emails=req.interviewer_emails,
        job_title=req.job_title or "",
    )
    if req.company:
        context_kwargs["company"] = req.company  # else MeetingContext's own default applies
    context = MeetingContext(**context_kwargs)
    _SESSIONS[meeting_id] = _Session(context, events=None)
    log.info("started live meeting %s", meeting_id)
    return {"meeting_id": meeting_id, "context": context.to_dict()}


@app.get("/api/meeting/{meeting_id}")
def api_get_meeting(meeting_id: str) -> dict:
    """Polling alternative to the WebSocket — current context + engine state."""
    session = _SESSIONS.get(meeting_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown meeting_id")
    return {
        "meeting_id": meeting_id,
        "context": session.engine.context.to_dict(),
        "state": session.engine.get_state(),
    }


@app.post("/api/meeting/{meeting_id}/event")
async def api_post_live_event(meeting_id: str, req: LiveEventRequest) -> dict:
    session = _SESSIONS.get(meeting_id)
    if not session:
        raise HTTPException(status_code=404, detail="Unknown meeting_id")

    try:
        event_type = EventType(req.event_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown event_type '{req.event_type}'")

    data = dict(req.data)

    # meet_bot/zoom_bot send raw base64 image/audio, not pre-computed
    # embeddings — extraction happens here, server-side, once, so
    # signals.py/engine.py only ever deal with plain float vectors.
    if event_type == EventType.FACE_SAMPLE and "image_b64" in data:
        try:
            image_bytes = base64.b64decode(data.pop("image_b64"))
        except Exception:
            raise HTTPException(status_code=400, detail="image_b64 is not valid base64")
        embedding = biometrics.extract_face_embedding(image_bytes)
        if embedding is None:
            # No face in this frame — not an error, just nothing to report
            # for this event (e.g. participant stepped away, webcam off).
            return {"identification": None, "note": "no face detected in frame"}
        prev = session._prev_face_embedding.get(req.participant_id)
        data["embedding"] = embedding
        data["liveness_ok"] = biometrics.check_liveness(prev, embedding)
        session._prev_face_embedding[req.participant_id] = embedding

    elif event_type == EventType.VOICE_SAMPLE and "audio_b64" in data:
        try:
            audio_bytes = base64.b64decode(data.pop("audio_b64"))
        except Exception:
            raise HTTPException(status_code=400, detail="audio_b64 is not valid base64")
        embedding = biometrics.extract_voice_embedding(audio_bytes)
        if embedding is None:
            return {"identification": None, "note": "no usable speech in clip"}
        data["embedding"] = embedding

    event = MeetingEvent(event_type=event_type, participant_id=req.participant_id, data=data)
    result = session.engine.process_event(event)
    await _broadcast(session, event, result)
    return {"identification": result.to_dict()}


# ---------------------------------------------------------------------------
# Zoom webhook (Event Subscriptions — "all meeting events" subscribed)
# ---------------------------------------------------------------------------
#
# Authoritative for participant_join / participant_leave. zoom_bot.py's
# Playwright bot deliberately no longer reports join/leave from the DOM
# (see zoom_bot.py) — it only reports speaking_start/speaking_end and
# biometric samples, which Zoom's webhook events don't carry. Both sources
# agree on participant_id via stable_pid() so events land on the same
# ParticipantState regardless of which source fires first.
#
# Only join/leave are mapped today. Everything else "all meeting events"
# includes (meeting.started, meeting.ended, sharing, recording, chat, etc.)
# is acknowledged with 200 but not processed — add entries to
# _ZOOM_EVENT_MAP as engine.py grows signals that use them.

ZOOM_WEBHOOK_SECRET_TOKEN = os.environ.get("ZOOM_WEBHOOK_SECRET_TOKEN", "")

_ZOOM_EVENT_MAP = {
    "meeting.participant_joined": "participant_join",
    "meeting.participant_left": "participant_leave",
}


def _verify_zoom_signature(request: Request, raw_body: bytes) -> bool:
    if not ZOOM_WEBHOOK_SECRET_TOKEN:
        log.warning("ZOOM_WEBHOOK_SECRET_TOKEN not set — refusing to verify webhook")
        return False
    timestamp = request.headers.get("x-zm-request-timestamp", "")
    signature = request.headers.get("x-zm-signature", "")
    message = f"v0:{timestamp}:{raw_body.decode()}"
    computed = hmac.new(
        ZOOM_WEBHOOK_SECRET_TOKEN.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"v0={computed}", signature)


@app.post("/api/zoom/webhook")
async def api_zoom_webhook(request: Request) -> dict:
    raw_body = await request.body()
    body = await request.json()
    event = body.get("event", "")

    # Zoom's one-time CRC handshake, fired when you (re)save the Event
    # Subscription URL in the App Marketplace. Must be answered correctly
    # or Zoom disables the subscription — this is NOT signature-verified
    # the normal way, it uses the plainToken directly.
    if event == "endpoint.url_validation":
        if not ZOOM_WEBHOOK_SECRET_TOKEN:
            log.warning("ZOOM_WEBHOOK_SECRET_TOKEN not set — cannot answer CRC handshake")
            raise HTTPException(status_code=500, detail="webhook secret not configured")
        plain_token = body.get("payload", {}).get("plainToken", "")
        encrypted = hmac.new(
            ZOOM_WEBHOOK_SECRET_TOKEN.encode(), plain_token.encode(), hashlib.sha256
        ).hexdigest()
        return {"plainToken": plain_token, "encryptedToken": encrypted}

    if not _verify_zoom_signature(request, raw_body):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = body.get("payload", {}).get("object", {})
    zoom_meeting_id = str(payload.get("id", ""))
    session = _SESSIONS.get(zoom_meeting_id)
    if not session:
        # Webhook arrived before /api/meeting/live created the session
        # (or for a meeting Sherlock isn't tracking) — nothing to do yet.
        log.info("zoom webhook for untracked meeting %s (event=%s)", zoom_meeting_id, event)
        return {"status": "ignored", "reason": "unknown meeting_id"}

    mapped = _ZOOM_EVENT_MAP.get(event)
    if not mapped:
        log.info("zoom webhook event %s not mapped — acked, not processed", event)
        return {"status": "acked", "processed": False}

    participant = payload.get("participant", {})
    display_name = participant.get("user_name", "")
    pid = stable_pid(display_name) if display_name else f"zoom-{participant.get('id', 'unknown')}"
    data = {"display_name": display_name}

    event_obj = MeetingEvent(event_type=EventType(mapped), participant_id=pid, data=data)
    result = session.engine.process_event(event_obj)
    await _broadcast(session, event_obj, result)
    return {"status": "processed", "identification": result.to_dict()}


# ---------------------------------------------------------------------------
# WebSocket — streams identification updates to the dashboard
# ---------------------------------------------------------------------------

async def _broadcast(session: _Session, event: MeetingEvent, result) -> None:
    payload = {
        "type": "meeting_event",
        "event": event.to_dict(),
        "state": session.engine.get_state(),
        "identification": result.to_dict(),
    }
    dead = []
    for ws in session.subscribers:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        session.subscribers.remove(ws)


@app.websocket("/ws/{meeting_id}")
async def ws_meeting(websocket: WebSocket, meeting_id: str) -> None:
    await websocket.accept()
    session = _SESSIONS.get(meeting_id)
    if not session:
        await websocket.send_json({"type": "error", "message": "Unknown meeting_id"})
        await websocket.close()
        return

    session.subscribers.append(websocket)
    await websocket.send_json({"type": "connected", "meeting_id": meeting_id})

    try:
        if session.live:
            # Live meeting: just keep the socket open, events arrive via
            # POST /api/meeting/{id}/event or POST /api/zoom/webhook and get
            # pushed out by _broadcast(). Read (and discard) any client
            # pings so we notice disconnects.
            while True:
                await websocket.receive_text()
        else:
            # Scenario replay: pace events using their recorded timestamps,
            # compressed by `speed`, so the dashboard sees a realistic
            # unfolding meeting rather than an instant dump.
            events = session.events
            prev_ts = events[0].timestamp if events else time.time()
            for ev in events:
                gap = max(0.0, (ev.timestamp - prev_ts) / max(session.speed, 0.01))
                if gap > 0:
                    await asyncio.sleep(min(gap, 3.0))
                prev_ts = ev.timestamp

                result = session.engine.process_event(ev)
                await _broadcast(session, ev, result)

            await websocket.send_json({"type": "scenario_complete"})
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in session.subscribers:
            session.subscribers.remove(websocket)
        if not session.live:
            _SESSIONS.pop(meeting_id, None)


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "active_meetings": len(_SESSIONS)}


@app.get("/")
def root() -> dict:
    return {
        "status": "ok",
        "service": "sherlock-candidate-identification",
        "scenarios_available": len(SCENARIOS),
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8765))
    uvicorn.run(app, host="0.0.0.0", port=port)
