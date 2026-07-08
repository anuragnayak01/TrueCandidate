"""
scenarios.py — Demo scenarios for the Sherlock prototype.

Each scenario describes:
  - A MeetingContext (ATS / calendar metadata)
  - A sequence of timed MeetingEvents that simulate a real interview session
  - A difficulty tag and description for the UI
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from models import EventType, MeetingContext, MeetingEvent

# ---------------------------------------------------------------------------
# Helper to build timed event lists cleanly
# ---------------------------------------------------------------------------

class _EventBuilder:
    def __init__(self, base_time: float):
        self._base = base_time
        self._events: List[Dict[str, Any]] = []

    def add(self, delay: float, etype: EventType, pid: str, **data) -> "_EventBuilder":
        self._events.append({
            "delay": delay,
            "event_type": etype,
            "participant_id": pid,
            "data": data,
        })
        return self

    def build(self) -> List[Dict[str, Any]]:
        return self._events


def _mk_event(raw: Dict[str, Any], base: float) -> MeetingEvent:
    return MeetingEvent(
        event_type=EventType(raw["event_type"]),
        participant_id=raw["participant_id"],
        timestamp=base + raw["delay"],
        data=raw.get("data", {}),
    )


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

SCENARIOS: Dict[str, Dict[str, Any]] = {}


def _register(key: str, meta: dict, context: MeetingContext, raw_events: List[dict]):
    SCENARIOS[key] = {"meta": meta, "context": context, "raw_events": raw_events}


def get_scenario_events(key: str, base_time: float | None = None) -> tuple[MeetingContext, List[MeetingEvent]]:
    s = SCENARIOS[key]
    base = base_time or time.time()
    events = [_mk_event(e, base) for e in s["raw_events"]]
    return s["context"], events


# ===========================================================================
# 1. Happy Path
# ===========================================================================
_ctx = MeetingContext(
    meeting_id="meet-001",
    candidate_name="Sarah Chen",
    candidate_email="sarah.chen@gmail.com",
    interviewer_names=["Alex Rivera", "Jordan Kim"],
    interviewer_emails=["alex.r@acmecorp.com", "jordan.k@acmecorp.com"],
    job_title="Senior Software Engineer",
    company="Acme Corp",
)
_evs: List[dict] = [
    # Participants join
    {"delay": 0.5,  "event_type": "participant_join",    "participant_id": "p1", "data": {"display_name": "Alex Rivera",  "email": "alex.r@acmecorp.com"}},
    {"delay": 1.5,  "event_type": "participant_join",    "participant_id": "p2", "data": {"display_name": "Jordan Kim",   "email": "jordan.k@acmecorp.com"}},
    {"delay": 3.0,  "event_type": "participant_join",    "participant_id": "p3", "data": {"display_name": "Sarah Chen",   "email": "sarah.chen@gmail.com"}},
    # Alex intro
    {"delay": 4.0,  "event_type": "speaking_start",     "participant_id": "p1", "data": {}},
    {"delay": 9.0,  "event_type": "speaking_end",       "participant_id": "p1", "data": {}},
    {"delay": 9.0,  "event_type": "transcript_segment", "participant_id": "p1", "data": {"text": "Hi Sarah, thanks for joining us today. Can you tell me about yourself and your background?"}},
    # Sarah answers (long turn)
    {"delay": 9.5,  "event_type": "speaking_start",     "participant_id": "p3", "data": {}},
    {"delay": 42.0, "event_type": "speaking_end",       "participant_id": "p3", "data": {}},
    {"delay": 42.0, "event_type": "transcript_segment", "participant_id": "p3", "data": {"text": "Sure! I worked at Google for three years as a senior engineer on the Search infrastructure team. I built several high-scale distributed systems. Before that, my background was at a startup where I led a team of five engineers and we developed our core data pipeline."}},
    # Jordan asks question
    {"delay": 43.0, "event_type": "speaking_start",     "participant_id": "p2", "data": {}},
    {"delay": 49.0, "event_type": "speaking_end",       "participant_id": "p2", "data": {}},
    {"delay": 49.0, "event_type": "transcript_segment", "participant_id": "p2", "data": {"text": "That's great. Tell me more about a specific technical challenge you faced and how you overcame it."}},
    # Sarah long answer
    {"delay": 50.0, "event_type": "speaking_start",     "participant_id": "p3", "data": {}},
    {"delay": 98.0, "event_type": "speaking_end",       "participant_id": "p3", "data": {}},
    {"delay": 98.0, "event_type": "transcript_segment", "participant_id": "p3", "data": {"text": "In my previous role at Google, we had a distributed caching system that was experiencing inconsistency issues under high load. I designed and implemented a novel read-repair mechanism that reduced stale reads by 94%. My approach involved instrumenting every cache node, identifying hotspots, and introducing a two-phase commit for critical invalidations."}},
    # Alex follow-up
    {"delay": 99.0, "event_type": "speaking_start",     "participant_id": "p1", "data": {}},
    {"delay": 104.0,"event_type": "speaking_end",       "participant_id": "p1", "data": {}},
    {"delay": 104.0,"event_type": "transcript_segment", "participant_id": "p1", "data": {"text": "What was the impact on latency? How did you measure success?"}},
    # Sarah answers
    {"delay": 105.0,"event_type": "speaking_start",     "participant_id": "p3", "data": {}},
    {"delay": 140.0,"event_type": "speaking_end",       "participant_id": "p3", "data": {}},
    {"delay": 140.0,"event_type": "transcript_segment", "participant_id": "p3", "data": {"text": "We measured p99 latency and saw it drop from 45ms to 12ms. My team set up Grafana dashboards to monitor the rollout. I ran the A/B test for two weeks and we saw a 3% improvement in overall search quality as well."}},
]
_register("happy_path", {"name": "Happy Path", "difficulty": "easy", "description": "Candidate joins with their real name and email — straightforward identification.", "emoji": "🟢"}, _ctx, _evs)


# ===========================================================================
# 2. Nickname — Candidate joins as "Mike" vs "Michael Chen"
# ===========================================================================
_ctx2 = MeetingContext(
    meeting_id="meet-002",
    candidate_name="Michael Chen",
    candidate_email="m.chen92@protonmail.com",
    interviewer_names=["Alex Rivera", "Priya Nair"],
    interviewer_emails=["alex.r@acmecorp.com", "priya.n@acmecorp.com"],
    job_title="Backend Engineer",
    company="Acme Corp",
)
_evs2: List[dict] = [
    {"delay": 0.5,  "event_type": "participant_join",    "participant_id": "p1", "data": {"display_name": "Alex Rivera",  "email": "alex.r@acmecorp.com"}},
    {"delay": 1.5,  "event_type": "participant_join",    "participant_id": "p2", "data": {"display_name": "Priya Nair",   "email": "priya.n@acmecorp.com"}},
    # Candidate joins as "Mike" — nickname
    {"delay": 4.0,  "event_type": "participant_join",    "participant_id": "p3", "data": {"display_name": "Mike",         "email": None}},
    # Alex speaks first
    {"delay": 5.0,  "event_type": "speaking_start",     "participant_id": "p1", "data": {}},
    {"delay": 11.0, "event_type": "speaking_end",       "participant_id": "p1", "data": {}},
    {"delay": 11.0, "event_type": "transcript_segment", "participant_id": "p1", "data": {"text": "Hey Mike, welcome! Can you start by walking us through your experience?"}},
    # Mike's first answer
    {"delay": 12.0, "event_type": "speaking_start",     "participant_id": "p3", "data": {}},
    {"delay": 55.0, "event_type": "speaking_end",       "participant_id": "p3", "data": {}},
    {"delay": 55.0, "event_type": "transcript_segment", "participant_id": "p3", "data": {"text": "Sure! My name is Michael Chen, I go by Mike. I've been working as a backend engineer for about six years. Most recently I was at Netflix where I worked on the recommendation engine. I designed and built the data pipeline that processes viewing history for over 200 million users."}},
    # Priya question
    {"delay": 56.0, "event_type": "speaking_start",     "participant_id": "p2", "data": {}},
    {"delay": 61.0, "event_type": "speaking_end",       "participant_id": "p2", "data": {}},
    {"delay": 61.0, "event_type": "transcript_segment", "participant_id": "p2", "data": {"text": "Can you describe a specific technical decision you made and why?"}},
    # Mike answers
    {"delay": 62.0, "event_type": "speaking_start",     "participant_id": "p3", "data": {}},
    {"delay": 110.0,"event_type": "speaking_end",       "participant_id": "p3", "data": {}},
    {"delay": 110.0,"event_type": "transcript_segment", "participant_id": "p3", "data": {"text": "Great question. In my role at Netflix, I had to decide between a push-based and pull-based recommendation update model. My approach was to analyze the latency requirements first — we needed sub-second updates. So I designed a hybrid: push for top-tier users, pull with aggressive caching for the rest. My solution cut infrastructure cost by 30%."}},
    # Alex short follow-up
    {"delay": 111.0,"event_type": "speaking_start",     "participant_id": "p1", "data": {}},
    {"delay": 115.0,"event_type": "speaking_end",       "participant_id": "p1", "data": {}},
    {"delay": 115.0,"event_type": "transcript_segment", "participant_id": "p1", "data": {"text": "Interesting trade-off. What tech stack did you use?"}},
    # Mike answers again
    {"delay": 116.0,"event_type": "speaking_start",     "participant_id": "p3", "data": {}},
    {"delay": 150.0,"event_type": "speaking_end",       "participant_id": "p3", "data": {}},
    {"delay": 150.0,"event_type": "transcript_segment", "participant_id": "p3", "data": {"text": "We used Apache Kafka for event streaming, Flink for stream processing, and Redis for the cache layer. My team also built a custom monitoring dashboard. For the ML model serving, I integrated TorchServe."}},
]
_register("nickname", {"name": "Nickname / Shortened Name", "difficulty": "medium", "description": "Candidate joins as 'Mike' — ATS says 'Michael Chen'. Signals converge via transcript.", "emoji": "🟡"}, _ctx2, _evs2)


# ===========================================================================
# 3. MacBook Pro — Candidate joins as device name
# ===========================================================================
_ctx3 = MeetingContext(
    meeting_id="meet-003",
    candidate_name="Zara Ahmed",
    candidate_email="zara.ahmed.dev@gmail.com",
    interviewer_names=["Sam Torres"],
    interviewer_emails=["s.torres@techstart.io"],
    job_title="ML Engineer",
    company="TechStart",
)
_evs3: List[dict] = [
    {"delay": 0.5,  "event_type": "participant_join",    "participant_id": "p1", "data": {"display_name": "Sam Torres",    "email": "s.torres@techstart.io"}},
    # Candidate joins as device name
    {"delay": 2.0,  "event_type": "participant_join",    "participant_id": "p2", "data": {"display_name": "MacBook Pro",   "email": None}},
    # Sam speaks
    {"delay": 3.0,  "event_type": "speaking_start",     "participant_id": "p1", "data": {}},
    {"delay": 8.0,  "event_type": "speaking_end",       "participant_id": "p1", "data": {}},
    {"delay": 8.0,  "event_type": "transcript_segment", "participant_id": "p1", "data": {"text": "Hi there, can you introduce yourself?"}},
    # Candidate responds — first clue via transcript
    {"delay": 9.0,  "event_type": "speaking_start",     "participant_id": "p2", "data": {}},
    {"delay": 52.0, "event_type": "speaking_end",       "participant_id": "p2", "data": {}},
    {"delay": 52.0, "event_type": "transcript_segment", "participant_id": "p2", "data": {"text": "Hi Sam! I'm Zara Ahmed. Sorry about the display name — I forgot to change it. I've been working in ML engineering for four years. My most recent work was building a real-time fraud detection model at Stripe that reduced false positives by 40%."}},
    # Candidate changes their name
    {"delay": 54.0, "event_type": "name_change",        "participant_id": "p2", "data": {"new_name": "Zara Ahmed"}},
    # Sam asks question
    {"delay": 55.0, "event_type": "speaking_start",     "participant_id": "p1", "data": {}},
    {"delay": 60.0, "event_type": "speaking_end",       "participant_id": "p1", "data": {}},
    {"delay": 60.0, "event_type": "transcript_segment", "participant_id": "p1", "data": {"text": "Impressive! Tell me about your model architecture choices."}},
    # Zara answers
    {"delay": 61.0, "event_type": "speaking_start",     "participant_id": "p2", "data": {}},
    {"delay": 100.0,"event_type": "speaking_end",       "participant_id": "p2", "data": {}},
    {"delay": 100.0,"event_type": "transcript_segment", "participant_id": "p2", "data": {"text": "For the fraud model, my approach was ensemble-based. I used XGBoost for tabular features and a small transformer for sequence features like transaction history. The key insight I had was to include velocity features — how fast amounts were escalating. I wrote the feature engineering pipeline in PySpark and the model was served with a sub-10ms latency."}},
]
_register("macbook_pro", {"name": "Device Name", "difficulty": "hard", "description": "Candidate joins as 'MacBook Pro'. Transcript + name-change events eventually identify them.", "emoji": "🔴"}, _ctx3, _evs3)


# ===========================================================================
# 4. Panel Interview — 3 interviewers, 2 observers, 1 candidate
# ===========================================================================
_ctx4 = MeetingContext(
    meeting_id="meet-004",
    candidate_name="Diego Ferreira",
    candidate_email="diego.f@outlook.com",
    interviewer_names=["Linda Park", "Tom Walsh", "Aisha Okafor"],
    interviewer_emails=["l.park@corp.com", "t.walsh@corp.com", "a.okafor@corp.com"],
    job_title="VP of Engineering",
    company="Corp Inc",
)
_evs4: List[dict] = [
    # Interviewers join
    {"delay": 0.5,  "event_type": "participant_join",    "participant_id": "p1", "data": {"display_name": "Linda Park",   "email": "l.park@corp.com"}},
    {"delay": 1.0,  "event_type": "participant_join",    "participant_id": "p2", "data": {"display_name": "Tom Walsh",    "email": "t.walsh@corp.com"}},
    {"delay": 1.5,  "event_type": "participant_join",    "participant_id": "p3", "data": {"display_name": "Aisha Okafor", "email": "a.okafor@corp.com"}},
    # Silent observers (no email)
    {"delay": 2.0,  "event_type": "participant_join",    "participant_id": "p4", "data": {"display_name": "Observer 1",   "email": None}},
    {"delay": 2.5,  "event_type": "participant_join",    "participant_id": "p5", "data": {"display_name": "HR Notes",     "email": None}},
    # Candidate joins last
    {"delay": 5.0,  "event_type": "participant_join",    "participant_id": "p6", "data": {"display_name": "Diego Ferreira","email": "diego.f@outlook.com"}},
    # Linda intro
    {"delay": 6.0,  "event_type": "speaking_start",     "participant_id": "p1", "data": {}},
    {"delay": 12.0, "event_type": "speaking_end",       "participant_id": "p1", "data": {}},
    {"delay": 12.0, "event_type": "transcript_segment", "participant_id": "p1", "data": {"text": "Diego, welcome! I'm Linda, this is Tom and Aisha. We have two observers joining silently. Can you start with your leadership philosophy?"}},
    # Diego answers (long)
    {"delay": 13.0, "event_type": "speaking_start",     "participant_id": "p6", "data": {}},
    {"delay": 75.0, "event_type": "speaking_end",       "participant_id": "p6", "data": {}},
    {"delay": 75.0, "event_type": "transcript_segment", "participant_id": "p6", "data": {"text": "Thank you Linda. My leadership philosophy is centered on psychological safety and systems thinking. In my previous role as Head of Engineering at a Series C startup, I built a team of 40 engineers across 6 countries. My approach was to establish clear ownership, reduce handoffs, and invest heavily in tooling so the team could move fast autonomously."}},
    # Tom question (short)
    {"delay": 76.0, "event_type": "speaking_start",     "participant_id": "p2", "data": {}},
    {"delay": 81.0, "event_type": "speaking_end",       "participant_id": "p2", "data": {}},
    {"delay": 81.0, "event_type": "transcript_segment", "participant_id": "p2", "data": {"text": "How did you handle underperforming engineers?"}},
    # Diego answers
    {"delay": 82.0, "event_type": "speaking_start",     "participant_id": "p6", "data": {}},
    {"delay": 125.0,"event_type": "speaking_end",       "participant_id": "p6", "data": {}},
    {"delay": 125.0,"event_type": "transcript_segment", "participant_id": "p6", "data": {"text": "I had a clear framework: first understand the root cause — was it unclear expectations, personal issues, skill gaps, or wrong role fit? I documented a specific case where an engineer was struggling. My approach was a 30-60-90 day plan with bi-weekly check-ins. In that case the engineer ended up becoming one of our top performers after moving to a more appropriate domain."}},
    # Aisha question
    {"delay": 126.0,"event_type": "speaking_start",     "participant_id": "p3", "data": {}},
    {"delay": 130.0,"event_type": "speaking_end",       "participant_id": "p3", "data": {}},
    {"delay": 130.0,"event_type": "transcript_segment", "participant_id": "p3", "data": {"text": "What would you change about your last company if you could go back?"}},
    # Diego answers again
    {"delay": 131.0,"event_type": "speaking_start",     "participant_id": "p6", "data": {}},
    {"delay": 170.0,"event_type": "speaking_end",       "participant_id": "p6", "data": {}},
    {"delay": 170.0,"event_type": "transcript_segment", "participant_id": "p6", "data": {"text": "That's a great question. I would have invested in the on-call culture earlier. We had too many engineers burned out by pager duty. My solution was to implement a proper SLO framework and reduce alert fatigue, but I implemented it too late. I also wish I had established a more rigorous RFC process for architectural decisions from day one."}},
]
_register("panel_interview", {"name": "Panel + Silent Observers", "difficulty": "hard", "description": "3 interviewers, 2 silent observers, 1 candidate. Tests exclusion + email + speaking signals.", "emoji": "🔴"}, _ctx4, _evs4)


# ===========================================================================
# 5. Name Change Mid-Interview
# ===========================================================================
_ctx5 = MeetingContext(
    meeting_id="meet-005",
    candidate_name="Lena Mueller",
    candidate_email="lena.mueller@gmail.com",
    interviewer_names=["Chris Brown"],
    interviewer_emails=["c.brown@startupxyz.com"],
    job_title="Product Designer",
    company="StartupXYZ",
)
_evs5: List[dict] = [
    {"delay": 0.5,  "event_type": "participant_join",    "participant_id": "p1", "data": {"display_name": "Chris Brown",  "email": "c.brown@startupxyz.com"}},
    # Candidate joins with wrong name
    {"delay": 2.0,  "event_type": "participant_join",    "participant_id": "p2", "data": {"display_name": "iPhone",       "email": None}},
    # Chris
    {"delay": 3.0,  "event_type": "speaking_start",     "participant_id": "p1", "data": {}},
    {"delay": 7.0,  "event_type": "speaking_end",       "participant_id": "p1", "data": {}},
    {"delay": 7.0,  "event_type": "transcript_segment", "participant_id": "p1", "data": {"text": "Hi, are you Lena? I see an iPhone joining..."}},
    # Candidate speaks — transcript identifies them
    {"delay": 8.0,  "event_type": "speaking_start",     "participant_id": "p2", "data": {}},
    {"delay": 18.0, "event_type": "speaking_end",       "participant_id": "p2", "data": {}},
    {"delay": 18.0, "event_type": "transcript_segment", "participant_id": "p2", "data": {"text": "Yes, hi! Sorry, I'm Lena Mueller. I'm joining from my phone, let me fix my display name."}},
    # Name change
    {"delay": 22.0, "event_type": "name_change",        "participant_id": "p2", "data": {"new_name": "Lena Mueller"}},
    # Continue interview
    {"delay": 23.0, "event_type": "speaking_start",     "participant_id": "p1", "data": {}},
    {"delay": 28.0, "event_type": "speaking_end",       "participant_id": "p1", "data": {}},
    {"delay": 28.0, "event_type": "transcript_segment", "participant_id": "p1", "data": {"text": "Perfect! Can you walk me through your design portfolio?"}},
    # Lena
    {"delay": 29.0, "event_type": "speaking_start",     "participant_id": "p2", "data": {}},
    {"delay": 80.0, "event_type": "speaking_end",       "participant_id": "p2", "data": {}},
    {"delay": 80.0, "event_type": "transcript_segment", "participant_id": "p2", "data": {"text": "Of course! My most recent project was redesigning the onboarding flow for a fintech app. My design process started with 25 user interviews, followed by affinity mapping and journey mapping. I created wireframes in Figma and ran 3 rounds of usability testing, reducing time-to-first-value from 8 minutes to under 2 minutes."}},
    {"delay": 81.0, "event_type": "screen_share_start", "participant_id": "p2", "data": {}},
    {"delay": 110.0,"event_type": "screen_share_end",   "participant_id": "p2", "data": {}},
    {"delay": 111.0,"event_type": "speaking_start",     "participant_id": "p2", "data": {}},
    {"delay": 140.0,"event_type": "speaking_end",       "participant_id": "p2", "data": {}},
    {"delay": 140.0,"event_type": "transcript_segment", "participant_id": "p2", "data": {"text": "As you can see in my portfolio, I worked on three main projects: the onboarding redesign I mentioned, a design system for a healthcare startup, and a B2B dashboard for logistics tracking. Each of these had distinct user personas and constraints."}},
]
_register("name_change", {"name": "Name Change Mid-Interview", "difficulty": "medium", "description": "Candidate starts as 'iPhone', reveals identity in transcript, then updates display name.", "emoji": "🟡"}, _ctx5, _evs5)


# ===========================================================================
# 6. Missing ATS Data — Minimal Context
# ===========================================================================
_ctx6 = MeetingContext(
    meeting_id="meet-006",
    candidate_name="",           # No ATS data
    candidate_email="",
    interviewer_names=[],
    interviewer_emails=[],
    job_title="Software Engineer",
    company="Unknown",
)
_evs6: List[dict] = [
    {"delay": 0.5,  "event_type": "participant_join",    "participant_id": "p1", "data": {"display_name": "Rachel Gomez", "email": None}},
    {"delay": 2.0,  "event_type": "participant_join",    "participant_id": "p2", "data": {"display_name": "User 2938",    "email": None}},
    {"delay": 3.0,  "event_type": "participant_join",    "participant_id": "p3", "data": {"display_name": "Mark S",       "email": None}},
    # Rachel speaks short (interviewer pattern)
    {"delay": 4.0,  "event_type": "speaking_start",     "participant_id": "p1", "data": {}},
    {"delay": 8.0,  "event_type": "speaking_end",       "participant_id": "p1", "data": {}},
    {"delay": 8.0,  "event_type": "transcript_segment", "participant_id": "p1", "data": {"text": "Hi everyone. Can the candidate please introduce themselves?"}},
    # Mark answers (long) — candidate pattern
    {"delay": 9.0,  "event_type": "speaking_start",     "participant_id": "p3", "data": {}},
    {"delay": 52.0, "event_type": "speaking_end",       "participant_id": "p3", "data": {}},
    {"delay": 52.0, "event_type": "transcript_segment", "participant_id": "p3", "data": {"text": "Hi, I'm Mark. I've been a software engineer for 8 years, mostly in backend systems. In my previous role I built microservices handling 10 million requests per day. I'm really excited about this opportunity and I've been preparing for this interview by studying your engineering blog."}},
    # User 2938 silent — observer pattern
    # Rachel asks another question
    {"delay": 53.0, "event_type": "speaking_start",     "participant_id": "p1", "data": {}},
    {"delay": 57.0, "event_type": "speaking_end",       "participant_id": "p1", "data": {}},
    {"delay": 57.0, "event_type": "transcript_segment", "participant_id": "p1", "data": {"text": "Mark, tell me about a time you had to make a difficult architectural decision."}},
    # Mark long answer
    {"delay": 58.0, "event_type": "speaking_start",     "participant_id": "p3", "data": {}},
    {"delay": 105.0,"event_type": "speaking_end",       "participant_id": "p3", "data": {}},
    {"delay": 105.0,"event_type": "transcript_segment", "participant_id": "p3", "data": {"text": "Sure. I once had to decide whether to refactor our monolith to microservices under a tight deadline. My analysis showed that the coupling was too high for a clean split given the timeline. My decision was to first extract the three highest-value services while keeping the core monolith stable, rather than doing a full rewrite. That turned out to be the right call."}},
]
_register("missing_ats", {"name": "No ATS Data", "difficulty": "hard", "description": "No candidate name or email. System relies entirely on speech patterns + join order.", "emoji": "🔴"}, _ctx6, _evs6)


# ---------------------------------------------------------------------------
# Utility: list all scenarios for the API
# ---------------------------------------------------------------------------

def list_scenarios() -> List[dict]:
    return [
        {
            "key": k,
            **v["meta"],
            "context": v["context"].to_dict(),
        }
        for k, v in SCENARIOS.items()
    ]
