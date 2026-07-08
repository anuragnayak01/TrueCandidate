"""
engine.py — CandidateIdentificationEngine

Rolling per-participant state machine. Processes meeting events, recomputes
all seven signals, and fuses them via a weighted-average + softmax pipeline.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional

from models import (
    EventType,
    IdentificationResult,
    MeetingContext,
    MeetingEvent,
    ParticipantState,
    SignalType,
)
from signals import compute_all_signals

# Temperature for softmax — lower = sharper distinctions
_SOFTMAX_TEMP = 0.25

# Gap threshold: if top-2 probabilities are within this margin → ambiguous
_AMBIGUITY_GAP = 0.12

# Minimum events before we make any claim
_MIN_EVENTS_FOR_CLAIM = 3


class CandidateIdentificationEngine:
    """
    Event-driven engine. Call `process_event(event)` for every incoming
    meeting event. Returns an updated IdentificationResult after each event.
    """

    def __init__(self, context: MeetingContext) -> None:
        self.context = context
        self.participants: Dict[str, ParticipantState] = {}
        self.event_log: List[dict] = []
        self._join_counter = 0
        self._event_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_event(self, event: MeetingEvent) -> IdentificationResult:
        """Ingest one event, update state, recompute signals, fuse → result."""
        self._event_count += 1
        self._apply_event(event)
        self._recompute_all_signals()
        result = self._fuse()
        self.event_log.append(
            {
                "n": self._event_count,
                "event": event.to_dict(),
                "candidate_id": result.candidate_participant_id,
                "confidence": round(result.confidence, 3),
            }
        )
        return result

    def get_state(self) -> dict:
        return {
            "context": self.context.to_dict(),
            "participants": {pid: p.to_dict() for pid, p in self.participants.items()},
            "event_count": self._event_count,
        }

    # ------------------------------------------------------------------
    # Event application
    # ------------------------------------------------------------------

    def _apply_event(self, event: MeetingEvent) -> None:
        pid = event.participant_id
        now = event.timestamp

        if event.event_type == EventType.PARTICIPANT_JOIN:
            self._join_counter += 1
            name = event.data.get("display_name", f"Participant {pid}")
            email = event.data.get("email")
            p = ParticipantState(
                participant_id=pid,
                display_name=name,
                join_order=self._join_counter,
                join_time=now,
                email=email,
            )
            p.name_history.append(name)
            self.participants[pid] = p

        elif event.event_type == EventType.PARTICIPANT_LEAVE:
            if pid in self.participants:
                # End any in-progress speaking turn
                p = self.participants[pid]
                if p.current_speaking_start is not None:
                    dur = now - p.current_speaking_start
                    p.speaking_duration += dur
                    p.longest_speaking_turn = max(p.longest_speaking_turn, dur)
                    p.current_speaking_start = None
                p.is_active = False

        elif event.event_type == EventType.SPEAKING_START:
            if pid in self.participants:
                self.participants[pid].current_speaking_start = now

        elif event.event_type == EventType.SPEAKING_END:
            if pid in self.participants:
                p = self.participants[pid]
                if p.current_speaking_start is not None:
                    dur = now - p.current_speaking_start
                    p.speaking_duration += dur
                    p.speaking_turns += 1
                    p.longest_speaking_turn = max(p.longest_speaking_turn, dur)
                    p.current_speaking_start = None

        elif event.event_type == EventType.TRANSCRIPT_SEGMENT:
            if pid in self.participants:
                text = event.data.get("text", "").strip()
                if text:
                    self.participants[pid].transcript_segments.append(text)

        elif event.event_type == EventType.SCREEN_SHARE_START:
            if pid in self.participants:
                p = self.participants[pid]
                p.has_shared_screen = True
                p.current_screen_share_start = now

        elif event.event_type == EventType.SCREEN_SHARE_END:
            if pid in self.participants:
                p = self.participants[pid]
                if p.current_screen_share_start is not None:
                    p.screen_share_duration += now - p.current_screen_share_start
                    p.current_screen_share_start = None

        elif event.event_type == EventType.NAME_CHANGE:
            if pid in self.participants:
                new_name = event.data.get("new_name", "")
                if new_name:
                    self.participants[pid].display_name = new_name
                    self.participants[pid].name_history.append(new_name)

        elif event.event_type == EventType.WEBCAM_ON:
            if pid in self.participants:
                self.participants[pid].webcam_on = True

        elif event.event_type == EventType.WEBCAM_OFF:
            if pid in self.participants:
                self.participants[pid].webcam_on = False

    # ------------------------------------------------------------------
    # Signal recomputation
    # ------------------------------------------------------------------

    def _recompute_all_signals(self) -> None:
        all_ps = list(self.participants.values())
        for p in all_ps:
            if p.is_active:
                compute_all_signals(p, self.context, all_ps)

    # ------------------------------------------------------------------
    # Fusion layer
    # ------------------------------------------------------------------

    def _fuse(self) -> IdentificationResult:
        active = [p for p in self.participants.values() if p.is_active]

        if not active:
            return self._empty_result()

        # Composite raw scores
        raw_scores: Dict[str, float] = {p.participant_id: p.composite_score for p in active}

        # Softmax with temperature for sharper separation
        probabilities = _softmax(raw_scores, temperature=_SOFTMAX_TEMP)

        if not probabilities:
            return self._empty_result()

        # Sort by probability
        ranked = sorted(probabilities.items(), key=lambda x: x[1], reverse=True)
        best_id, best_prob = ranked[0]
        second_prob = ranked[1][1] if len(ranked) > 1 else 0.0

        # Ambiguity check
        is_ambiguous = False
        ambiguity_reason: Optional[str] = None

        if self._event_count < _MIN_EVENTS_FOR_CLAIM:
            is_ambiguous = True
            ambiguity_reason = "Insufficient events to make a confident identification"
        elif best_prob - second_prob < _AMBIGUITY_GAP:
            is_ambiguous = True
            second_name = self.participants[ranked[1][0]].display_name if len(ranked) > 1 else "?"
            ambiguity_reason = (
                f"Top two candidates are close: "
                f"{self.participants[best_id].display_name} ({best_prob:.0%}) vs "
                f"{second_name} ({second_prob:.0%})"
            )

        best_participant = self.participants[best_id]

        # Build explanation from top signals
        explanation = self._build_explanation(best_participant, best_prob, is_ambiguous)

        # Signal breakdown per participant
        signal_breakdown = {
            p.participant_id: [sr.to_dict() for sr in p.signals.values()]
            for p in active
        }

        return IdentificationResult(
            candidate_participant_id=best_id if not is_ambiguous else None,
            candidate_display_name=best_participant.display_name if not is_ambiguous else None,
            confidence=round(best_prob, 4),
            is_ambiguous=is_ambiguous,
            ambiguity_reason=ambiguity_reason,
            explanation=explanation,
            participant_scores={p.participant_id: round(p.composite_score, 4) for p in active},
            participant_probabilities={pid: round(prob, 4) for pid, prob in probabilities.items()},
            signal_breakdown=signal_breakdown,
            event_count=self._event_count,
            timestamp=time.time(),
        )

    def _build_explanation(
        self,
        participant: ParticipantState,
        probability: float,
        is_ambiguous: bool,
    ) -> List[str]:
        lines: List[str] = []

        if is_ambiguous:
            lines.append("⚠️  Identification is ambiguous — gathering more evidence.")
        else:
            lines.append(
                f"✅  Identified '{participant.display_name}' as the candidate "
                f"with {probability:.0%} confidence."
            )

        # Top contributing signals (by effective weight × score delta from 0.5)
        scored_signals = sorted(
            participant.signals.values(),
            key=lambda r: r.effective_weight() * abs(r.score - 0.5),
            reverse=True,
        )

        for sr in scored_signals[:4]:
            if sr.signal_confidence < 0.05:
                continue
            direction = "↑" if sr.score > 0.5 else "↓"
            lines.append(f"  {direction} [{sr.signal_type.value}] {sr.reason}")

        if not lines[1:]:
            lines.append("  ℹ️  Signals are still accumulating — confidence will grow with more data.")

        return lines

    def _empty_result(self) -> IdentificationResult:
        return IdentificationResult(
            candidate_participant_id=None,
            candidate_display_name=None,
            confidence=0.0,
            is_ambiguous=True,
            ambiguity_reason="No active participants",
            explanation=["No participants have joined yet."],
            participant_scores={},
            participant_probabilities={},
            signal_breakdown={},
            event_count=self._event_count,
        )


# ---------------------------------------------------------------------------
# Softmax helper
# ---------------------------------------------------------------------------

def _softmax(scores: Dict[str, float], temperature: float = 1.0) -> Dict[str, float]:
    """
    Softmax with temperature scaling over a dict of scores.
    Lower temperature → sharper winner-takes-most distribution.
    """
    if not scores:
        return {}

    vals = list(scores.values())
    keys = list(scores.keys())

    # Numerical stability: subtract max
    max_val = max(vals)
    exps = [math.exp((v - max_val) / temperature) for v in vals]
    total = sum(exps)

    return {k: e / total for k, e in zip(keys, exps)}
