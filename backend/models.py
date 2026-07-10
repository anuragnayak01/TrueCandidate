"""
models.py — Core data models for the Sherlock Candidate Identification Engine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    PARTICIPANT_JOIN = "participant_join"
    PARTICIPANT_LEAVE = "participant_leave"
    SPEAKING_START = "speaking_start"
    SPEAKING_END = "speaking_end"
    TRANSCRIPT_SEGMENT = "transcript_segment"
    SCREEN_SHARE_START = "screen_share_start"
    SCREEN_SHARE_END = "screen_share_end"
    NAME_CHANGE = "name_change"
    WEBCAM_ON = "webcam_on"
    WEBCAM_OFF = "webcam_off"
    FACE_SAMPLE = "face_sample"    # data: {"embedding": [...], "liveness_ok": bool}
    VOICE_SAMPLE = "voice_sample"  # data: {"embedding": [...]}


class SignalType(str, Enum):
    NAME_MATCH = "name_match"
    EMAIL_MATCH = "email_match"
    INTERVIEWER_EXCLUSION = "interviewer_exclusion"
    SPEAKING_PATTERN = "speaking_pattern"
    TRANSCRIPT_LANGUAGE = "transcript_language"
    JOIN_ORDER = "join_order"
    SCREEN_SHARE = "screen_share"
    FACE_MATCH = "face_match"
    VOICE_MATCH = "voice_match"


# ---------------------------------------------------------------------------
# Signal weights (must sum to 1.0)
# ---------------------------------------------------------------------------

# Weights below reflect a deliberate design choice: face/voice are biometric
# identity anchors (hard to spoof, immune to name/device changes) so they
# carry the majority of the weight — but they are still BLENDED into the
# same weighted average as every other signal, not a hard override. A bad
# frame or noisy audio sample degrades gracefully via signal_confidence
# rather than being able to unilaterally flip the decision. See engine.py
# for the one deliberate exception: cross-modal (face vs voice) disagreement
# is escalated as a separate IDENTITY_MISMATCH flag rather than blended away.
SIGNAL_WEIGHTS: Dict[SignalType, float] = {
    SignalType.FACE_MATCH: 0.35,
    SignalType.VOICE_MATCH: 0.22,
    SignalType.EMAIL_MATCH: 0.13,
    SignalType.INTERVIEWER_EXCLUSION: 0.11,
    SignalType.NAME_MATCH: 0.09,
    SignalType.SPEAKING_PATTERN: 0.05,
    SignalType.TRANSCRIPT_LANGUAGE: 0.03,
    SignalType.JOIN_ORDER: 0.015,
    SignalType.SCREEN_SHARE: 0.005,
}

SIGNAL_LABELS: Dict[SignalType, str] = {
    SignalType.FACE_MATCH: "Face Match",
    SignalType.VOICE_MATCH: "Voice Match",
    SignalType.EMAIL_MATCH: "Email Match",
    SignalType.INTERVIEWER_EXCLUSION: "Interviewer Exclusion",
    SignalType.NAME_MATCH: "Name Match",
    SignalType.SPEAKING_PATTERN: "Speaking Pattern",
    SignalType.TRANSCRIPT_LANGUAGE: "Transcript Language",
    SignalType.JOIN_ORDER: "Join Order",
    SignalType.SCREEN_SHARE: "Screen Share",
}


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass
class MeetingEvent:
    event_type: EventType
    participant_id: str
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "participant_id": self.participant_id,
            "timestamp": self.timestamp,
            "data": self.data,
        }


# ---------------------------------------------------------------------------
# Meeting context (ATS / Calendar metadata)
# ---------------------------------------------------------------------------

@dataclass
class MeetingContext:
    meeting_id: str
    candidate_name: str
    candidate_email: str
    interviewer_names: List[str]
    interviewer_emails: List[str]
    scheduled_time: float = field(default_factory=time.time)
    job_title: str = ""
    company: str = "Acme Corp"

    # Pre-meeting biometric references, extracted once during enrollment
    # (candidate photo + ~20s voice clip) and delivered to the meeting bot
    # for the duration of this interview only — never persisted longer than
    # that. See README "Biometric enrollment" section for the full pipeline.
    candidate_face_embedding: Optional[List[float]] = None
    candidate_voice_embedding: Optional[List[float]] = None

    def to_dict(self) -> dict:
        return {
            "meeting_id": self.meeting_id,
            "candidate_name": self.candidate_name,
            "candidate_email": self.candidate_email,
            "interviewer_names": self.interviewer_names,
            "interviewer_emails": self.interviewer_emails,
            "job_title": self.job_title,
            "company": self.company,
            # Never serialize the raw vectors to the client — only whether
            # a biometric reference was successfully enrolled pre-meeting.
            "has_face_reference": self.candidate_face_embedding is not None,
            "has_voice_reference": self.candidate_voice_embedding is not None,
        }


# ---------------------------------------------------------------------------
# Per-signal result
# ---------------------------------------------------------------------------

@dataclass
class SignalResult:
    signal_type: SignalType
    score: float          # [0.0, 1.0]: 0 = definitely not candidate, 1 = definitely candidate
    signal_confidence: float   # [0.0, 1.0]: how reliable is this signal given available data
    reason: str
    evidence: dict = field(default_factory=dict)

    def effective_weight(self) -> float:
        base = SIGNAL_WEIGHTS.get(self.signal_type, 0.0)
        return base * self.signal_confidence

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type.value,
            "label": SIGNAL_LABELS.get(self.signal_type, self.signal_type.value),
            "score": round(self.score, 4),
            "signal_confidence": round(self.signal_confidence, 4),
            "weight": SIGNAL_WEIGHTS.get(self.signal_type, 0.0),
            "effective_weight": round(self.effective_weight(), 4),
            "reason": self.reason,
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------
# Per-participant rolling state
# ---------------------------------------------------------------------------

@dataclass
class ParticipantState:
    participant_id: str
    display_name: str
    join_order: int        # 1-indexed join sequence
    join_time: float

    email: Optional[str] = None
    speaking_duration: float = 0.0
    speaking_turns: int = 0
    longest_speaking_turn: float = 0.0
    current_speaking_start: Optional[float] = None

    transcript_segments: List[str] = field(default_factory=list)
    has_shared_screen: bool = False
    screen_share_duration: float = 0.0
    current_screen_share_start: Optional[float] = None
    webcam_on: bool = True
    is_active: bool = True
    name_history: List[str] = field(default_factory=list)

    # Most recent biometric samples captured for this participant. These
    # are overwritten (not accumulated) — the signal only ever compares
    # against the freshest frame/clip, it doesn't try to average over time.
    latest_face_embedding: Optional[List[float]] = None
    latest_face_liveness_ok: bool = True
    last_face_sample_time: Optional[float] = None

    latest_voice_embedding: Optional[List[float]] = None
    last_voice_sample_time: Optional[float] = None

    # Rolling signal results — updated on every event
    signals: Dict[SignalType, SignalResult] = field(default_factory=dict)

    @property
    def avg_turn_length(self) -> float:
        return self.speaking_duration / max(self.speaking_turns, 1)

    @property
    def composite_score(self) -> float:
        """Weighted average of signal scores, weighted by effective_weight."""
        total_eff_weight = 0.0
        weighted_score = 0.0
        for result in self.signals.values():
            ew = result.effective_weight()
            weighted_score += result.score * ew
            total_eff_weight += ew
        if total_eff_weight == 0:
            return 0.5
        return weighted_score / total_eff_weight

    def to_dict(self) -> dict:
        return {
            "participant_id": self.participant_id,
            "display_name": self.display_name,
            "join_order": self.join_order,
            "join_time": self.join_time,
            "email": self.email,
            "speaking_duration": round(self.speaking_duration, 2),
            "speaking_turns": self.speaking_turns,
            "avg_turn_length": round(self.avg_turn_length, 2),
            "longest_speaking_turn": round(self.longest_speaking_turn, 2),
            "has_shared_screen": self.has_shared_screen,
            "webcam_on": self.webcam_on,
            "is_active": self.is_active,
            "name_history": self.name_history,
            "transcript_word_count": sum(len(s.split()) for s in self.transcript_segments),
            "has_face_sample": self.latest_face_embedding is not None,
            "face_liveness_ok": self.latest_face_liveness_ok,
            "has_voice_sample": self.latest_voice_embedding is not None,
            "signals": {k.value: v.to_dict() for k, v in self.signals.items()},
            "composite_score": round(self.composite_score, 4),
        }


# ---------------------------------------------------------------------------
# Final identification result
# ---------------------------------------------------------------------------

@dataclass
class IdentificationResult:
    candidate_participant_id: Optional[str]
    candidate_display_name: Optional[str]
    confidence: float            # 0.0 – 1.0 after softmax
    is_ambiguous: bool
    ambiguity_reason: Optional[str]
    explanation: List[str]       # Human-readable ordered explanation
    participant_scores: Dict[str, float]        # raw composite scores
    participant_probabilities: Dict[str, float] # post-softmax
    signal_breakdown: Dict[str, List[dict]]     # per-participant signal dicts
    event_count: int
    timestamp: float = field(default_factory=time.time)

    # Cross-modal biometric disagreement (face says yes, voice says no, or
    # vice versa — both at high confidence). This is deliberately NOT folded
    # into the weighted-average score: two independent biometric channels
    # contradicting each other is a different kind of event than one signal
    # being unsure, so it's surfaced as its own hard-triggered flag instead
    # of being averaged away. See engine.py `_check_identity_mismatch`.
    identity_mismatch: bool = False
    identity_mismatch_participant_id: Optional[str] = None
    identity_mismatch_reason: Optional[str] = None

    CONFIDENCE_LOCKED_THRESHOLD = 0.85

    @property
    def is_locked(self) -> bool:
        return self.confidence >= self.CONFIDENCE_LOCKED_THRESHOLD and not self.is_ambiguous

    def to_dict(self) -> dict:
        return {
            "candidate_participant_id": self.candidate_participant_id,
            "candidate_display_name": self.candidate_display_name,
            "confidence": round(self.confidence, 4),
            "is_ambiguous": self.is_ambiguous,
            "is_locked": self.is_locked,
            "ambiguity_reason": self.ambiguity_reason,
            "explanation": self.explanation,
            "participant_scores": {k: round(v, 4) for k, v in self.participant_scores.items()},
            "participant_probabilities": {k: round(v, 4) for k, v in self.participant_probabilities.items()},
            "signal_breakdown": self.signal_breakdown,
            "event_count": self.event_count,
            "timestamp": self.timestamp,
            "identity_mismatch": self.identity_mismatch,
            "identity_mismatch_participant_id": self.identity_mismatch_participant_id,
            "identity_mismatch_reason": self.identity_mismatch_reason,
        }
