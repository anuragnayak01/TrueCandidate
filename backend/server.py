"""
server.py — FastAPI + WebSocket server for the Sherlock prototype.

Endpoints
---------
GET  /api/scenarios                 → list available demo scenarios
POST /api/meeting/start             → start a new meeting / demo scenario
POST /api/event/{meeting_id}        → inject a single event (used by bots)
GET  /api/meeting/{meeting_id}      → current engine state snapshot
POST /api/zoom/webhook              → Zoom webhook receiver (free developer account)
WS   /ws/{meeting_id}              → real-time event stream

WebSocket message types (server → client)
------------------------------------------
  { "type": "connected",      "meeting_id": "..." }
  { "type": "meeting_event",  "event": {...}, "identification": {...}, "state": {...} }
  { "type": "scenario_complete" }
  { "type": "error",          "message": "..." }
"""

from __future__ import annotations
import os
import asyncio
import json
import time
import uuid
from typing import Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from engine import CandidateIdentificationEngine
from models import MeetingContext, MeetingEvent
from scenarios import SCENARIOS, get_scenario_events, list_scenarios

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Sherlock Candidate Identification API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

class MeetingSession:
    def __init__(self, meeting_id: str, context: MeetingContext):
        self.meeting_id = meeting_id
        self.engine = CandidateIdentificationEngine(context)
        self.connections: List[WebSocket] = []
        self.is_running = False
        self.task: Optional[asyncio.Task] = None

    async def broadcast(self, payload: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)


_sessions: Dict[str, MeetingSession] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/scenarios")
async def get_scenarios():
    return JSONResponse(list_scenarios())


@app.post("/api/meeting/start")
async def start_meeting(body: dict):
    """
    Body: { "scenario": "happy_path" }
          OR custom context via { "context": {...}, "events": [...] }
    """
    meeting_id = str(uuid.uuid4())[:8]

    scenario_key = body.get("scenario")
    if scenario_key and scenario_key in SCENARIOS:
        context, events = get_scenario_events(scenario_key, base_time=time.time())
    else:
        # Custom context
        raw_ctx = body.get("context", {})
        context = MeetingContext(
            meeting_id=meeting_id,
            candidate_name=raw_ctx.get("candidate_name", ""),
            candidate_email=raw_ctx.get("candidate_email", ""),
            interviewer_names=raw_ctx.get("interviewer_names", []),
            interviewer_emails=raw_ctx.get("interviewer_emails", []),
            job_title=raw_ctx.get("job_title", ""),
            company=raw_ctx.get("company", ""),
        )
        events = []

    session = MeetingSession(meeting_id, context)
    _sessions[meeting_id] = session

    # Schedule event playback in background
    if events:
        session.task = asyncio.create_task(
            _play_scenario(session, events)
        )

    return JSONResponse({"meeting_id": meeting_id, "context": context.to_dict()})


@app.get("/api/meeting/{meeting_id}")
async def get_meeting_state(meeting_id: str):
    session = _sessions.get(meeting_id)
    if not session:
        return JSONResponse({"error": "Meeting not found"}, status_code=404)
    return JSONResponse(session.engine.get_state())


@app.post("/api/event/{meeting_id}")
async def inject_event(meeting_id: str, body: dict):
    """
    Single-event injection endpoint.
    Used by the Playwright bots (gmeet_bot.py, zoom_bot.py) to
    push real meeting events without a WebSocket connection.

    Body: {
      "event_type": "participant_join",
      "participant_id": "p1",
      "timestamp": 1720000000.0,
      "data": { "display_name": "Sarah Chen", "email": "..." }
    }
    """
    session = _sessions.get(meeting_id)
    if not session:
        return JSONResponse({"error": "Meeting not found"}, status_code=404)

    try:
        ev = MeetingEvent(
            event_type=body["event_type"],
            participant_id=body["participant_id"],
            timestamp=body.get("timestamp", time.time()),
            data=body.get("data", {}),
        )
    except (KeyError, ValueError) as e:
        return JSONResponse({"error": f"Bad event: {e}"}, status_code=400)

    result = session.engine.process_event(ev)
    await session.broadcast({
        "type": "meeting_event",
        "event": ev.to_dict(),
        "identification": result.to_dict(),
        "state": session.engine.get_state(),
    })
    return JSONResponse({"status": "ok", "confidence": result.confidence})


# ---------------------------------------------------------------------------
# Zoom webhook — free developer account, no paid subscription needed
# Sign up at: https://marketplace.zoom.us  (use your existing free Zoom account)
# ---------------------------------------------------------------------------
import hashlib
import hmac

ZOOM_WEBHOOK_SECRET = os.environ.get("ZOOM_WEBHOOK_SECRET", "")


@app.post("/api/zoom/webhook")
async def zoom_webhook(request: Request):
    """
    Receives Zoom participant events via webhook (free developer app).

    Setup (one-time, no subscription needed):
      1. Go to marketplace.zoom.us → Develop → Build App → General App
      2. Under Feature → Event Subscriptions, add:
           - meeting.participant_joined
           - meeting.participant_left
           - meeting.participant_audio_status_updated
      3. Set Notification URL to: https://your-domain/api/zoom/webhook
      4. Set ZOOM_WEBHOOK_SECRET env var from the app's secret token
    """
    body_bytes = await request.body()

    try:
        body = json.loads(body_bytes)
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # --- Zoom URL validation challenge (one-time on setup) ---
    if body.get("event") == "endpoint.url_validation":
        plain_token = body["payload"]["plainToken"]
        if ZOOM_WEBHOOK_SECRET:
            encrypted = hmac.new(
                ZOOM_WEBHOOK_SECRET.encode(),
                plain_token.encode(),
                hashlib.sha256,
            ).hexdigest()
        else:
            encrypted = plain_token  # dev mode without secret
        return JSONResponse({"plainToken": plain_token, "encryptedToken": encrypted})

    # --- Verify signature (skip in dev if no secret set) ---
    if ZOOM_WEBHOOK_SECRET:
        ts  = request.headers.get("x-zm-request-timestamp", "")
        sig = request.headers.get("x-zm-signature", "")
        msg = f"v0:{ts}:{body_bytes.decode()}"
        expected = "v0=" + hmac.new(
            ZOOM_WEBHOOK_SECRET.encode(), msg.encode(), hashlib.sha256
        ).hexdigest()
        if sig != expected:
            return JSONResponse({"error": "Invalid signature"}, status_code=401)

    # --- Map Zoom event → Sherlock MeetingEvent ---
    zoom_event   = body.get("event", "")
    obj          = body.get("payload", {}).get("object", {})
    meeting_id   = str(obj.get("id", obj.get("uuid", "unknown")))
    participant  = obj.get("participant", {})
    pid          = str(participant.get("user_id") or participant.get("participant_uuid") or "?")
    name         = participant.get("user_name", "Unknown")
    email        = participant.get("email")

    # Auto-create session if not already exists
    session = _sessions.get(meeting_id)
    if not session:
        ctx = MeetingContext(
            meeting_id=meeting_id,
            candidate_name="",   # Will be populated via /api/meeting/start later
            candidate_email="",
            interviewer_names=[],
            interviewer_emails=[],
        )
        session = MeetingSession(meeting_id, ctx)
        _sessions[meeting_id] = session

    ev = None
    if zoom_event == "meeting.participant_joined":
        ev = MeetingEvent(EventType.PARTICIPANT_JOIN, pid,
                          data={"display_name": name, "email": email})
    elif zoom_event == "meeting.participant_left":
        ev = MeetingEvent(EventType.PARTICIPANT_LEAVE, pid)
    elif zoom_event == "meeting.participant_audio_status_updated":
        muted = participant.get("audio") == "muted"
        ev = MeetingEvent(
            EventType.SPEAKING_END if muted else EventType.SPEAKING_START, pid
        )
    elif zoom_event == "meeting.participant_video_status_updated":
        on = participant.get("video") == "started"
        ev = MeetingEvent(EventType.WEBCAM_ON if on else EventType.WEBCAM_OFF, pid)

    if ev:
        result = session.engine.process_event(ev)
        await session.broadcast({
            "type": "meeting_event",
            "event": ev.to_dict(),
            "identification": result.to_dict(),
            "state": session.engine.get_state(),
        })

    return JSONResponse({"status": "ok"})


@app.websocket("/ws/{meeting_id}")
async def websocket_endpoint(websocket: WebSocket, meeting_id: str):
    await websocket.accept()

    session = _sessions.get(meeting_id)
    if not session:
        await websocket.send_text(json.dumps({"type": "error", "message": "Meeting not found"}))
        await websocket.close()
        return

    session.connections.append(websocket)
    await websocket.send_text(json.dumps({
        "type": "connected",
        "meeting_id": meeting_id,
        "context": session.engine.context.to_dict(),
        "state": session.engine.get_state(),
    }))

    try:
        while True:
            # Keep connection alive; all pushes are server-initiated
            msg = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            # Handle client commands (e.g. manual event injection)
            try:
                payload = json.loads(msg)
                if payload.get("type") == "inject_event":
                    ev = MeetingEvent(
                        event_type=payload["event_type"],
                        participant_id=payload["participant_id"],
                        timestamp=time.time(),
                        data=payload.get("data", {}),
                    )
                    result = session.engine.process_event(ev)
                    await session.broadcast({
                        "type": "meeting_event",
                        "event": ev.to_dict(),
                        "identification": result.to_dict(),
                        "state": session.engine.get_state(),
                    })
            except Exception:
                pass

    except (WebSocketDisconnect, asyncio.TimeoutError):
        if websocket in session.connections:
            session.connections.remove(websocket)


# ---------------------------------------------------------------------------
# Scenario playback
# ---------------------------------------------------------------------------

async def _play_scenario(session: MeetingSession, events: List[MeetingEvent]):
    """
    Play scenario events with realistic timing.
    Each event delay is relative to the first event's timestamp, but we
    compress time by 1x (real-time) for a 2-minute demo playback.

    To speed up playback, we divide wall-clock delays by SPEED_FACTOR.
    """
    SPEED_FACTOR = 4.0  # 4× faster than real-time

    if not events:
        return

    base_delay = events[0].timestamp
    start_wall = time.time()

    for ev in events:
        # How many seconds into the scenario should this event fire?
        scenario_offset = ev.timestamp - base_delay
        # Scale by speed factor
        wall_offset = scenario_offset / SPEED_FACTOR
        # Sleep until it's time
        target_wall = start_wall + wall_offset
        sleep_dur = target_wall - time.time()
        if sleep_dur > 0:
            await asyncio.sleep(sleep_dur)

        # Fix event timestamp to now
        ev.timestamp = time.time()
        result = session.engine.process_event(ev)

        await session.broadcast({
            "type": "meeting_event",
            "event": ev.to_dict(),
            "identification": result.to_dict(),
            "state": session.engine.get_state(),
        })

    # Signal completion
    await asyncio.sleep(0.5)
    await session.broadcast({"type": "scenario_complete"})


# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------
import os

_FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_FRONTEND):
    app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=True)
