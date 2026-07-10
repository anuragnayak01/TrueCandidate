"""
signals.py — Seven independent weak-signal analyzers.

Each analyzer returns a SignalResult with:
  - score            [0,1]: probability this participant IS the candidate
  - signal_confidence[0,1]: how much to trust this signal given current data
  - reason           str:   human-readable explanation
  - evidence         dict:  raw numbers used to reach the decision
"""

from __future__ import annotations

import re
from typing import List

import math

from models import (
    MeetingContext,
    ParticipantState,
    SignalResult,
    SignalType,
)


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two equal-length embedding vectors, in
    [-1, 1]. Pure-Python — no numpy dependency needed for this repo."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)

# ---------------------------------------------------------------------------
# Optional: rapidfuzz for better fuzzy matching
# ---------------------------------------------------------------------------
try:
    from rapidfuzz import fuzz as _fuzz

    def _fuzzy(s1: str, s2: str) -> float:
        return _fuzz.token_set_ratio(s1.lower(), s2.lower()) / 100.0

except ImportError:
    def _fuzzy(s1: str, s2: str) -> float:  # type: ignore[misc]
        """Fallback pure-Python fuzzy match."""
        s1, s2 = s1.lower().strip(), s2.lower().strip()
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 1.0
        if s1 in s2 or s2 in s1:
            return 0.85
        # Jaccard on character trigrams
        def trigrams(s):
            return {s[i:i+3] for i in range(len(s) - 2)} if len(s) >= 3 else {s}
        t1, t2 = trigrams(s1), trigrams(s2)
        if not t1 or not t2:
            return 0.0
        return len(t1 & t2) / len(t1 | t2)


# ---------------------------------------------------------------------------
# Device / system name patterns that should penalize name-match signal
# ---------------------------------------------------------------------------
_DEVICE_RE = re.compile(
    r"\b(macbook|imac|iphone|ipad|android|windows|laptop|desktop|computer|pc|"
    r"surface|chromebook|phone|tablet|guest|meeting\s*room|conference\s*room|"
    r"host|join\s*by\s*phone|zoom\s*room)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Transcript language fingerprints
# ---------------------------------------------------------------------------
_CANDIDATE_RES = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bi (worked|built|designed|implemented|developed|created|led|managed|wrote|deployed|owned|drove)\b",
        r"\bmy (project|team|role|experience|background|approach|solution|code|work|startup|company)\b",
        r"\bin my (previous|current|last|former|past|prior) (role|job|position|company|team|org)\b",
        r"\b(i have|i had|i was|i am|i did|i do)\b",
        r"\bwe (built|deployed|scaled|migrated|developed|shipped|launched)\b",
        r"\b(for example|for instance|specifically|in particular|to give you an example)\b",
        r"\b(the challenge (was|i faced|we had|i ran into))\b",
        r"\bi (learned|realized|decided|discovered|found that|ended up)\b",
        r"\b(my approach|my strategy|my solution|my answer)\b",
        r"\b(i'm (currently|working|based|looking))\b",
    ]
]

_INTERVIEWER_RES = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(tell me (about|more|a little|your|us))\b",
        r"\b(can you (describe|explain|walk (me|us)|share|give))\b",
        r"\b(what (was|were|did|is|are) (your|the|a))\b",
        r"\b(how (did|do|would|have) you)\b",
        r"\b(give me an example)\b",
        r"\b(that'?s? (great|interesting|good|perfect|wonderful|helpful|awesome))\b",
        r"\b(next question|moving on|let'?s? (talk|discuss|move|jump|pivot))\b",
        r"\b(could you (elaborate|clarify|expand|tell))\b",
        r"\b(i'?m? (going to|here to|joining to) (ask|discuss|interview))\b",
        r"\bthank(s| you) for (joining|being here|your time|taking the time)\b",
    ]
]


# ---------------------------------------------------------------------------
# 1. Name Match
# ---------------------------------------------------------------------------

def compute_name_match(
    participant: ParticipantState,
    context: MeetingContext,
    all_participants: List[ParticipantState],
) -> SignalResult:
    """
    Fuzzy-match display name against:
      - candidate full name
      - individual name tokens (handles nicknames like "Mike" vs "Michael")
      - email username prefix

    Penalises device/room names.
    """
    if not context.candidate_name:
        return SignalResult(
            signal_type=SignalType.NAME_MATCH,
            score=0.5,
            signal_confidence=0.0,
            reason="No candidate name available from ATS",
            evidence={},
        )

    display = participant.display_name
    cand = context.candidate_name
    email_prefix = context.candidate_email.split("@")[0] if "@" in context.candidate_email else ""

    # Device name penalty
    if _DEVICE_RE.search(display):
        return SignalResult(
            signal_type=SignalType.NAME_MATCH,
            score=0.10,
            signal_confidence=0.80,
            reason=f"'{display}' looks like a device/room name, not a person",
            evidence={"is_device_name": True},
        )

    # Full-name fuzzy match
    full_score = _fuzzy(display, cand)

    # Token-level match (handles "Mike" → "Michael Chen")
    cand_tokens = cand.lower().split()
    disp_tokens = display.lower().split()
    token_hits = sum(
        1
        for dt in disp_tokens
        if any(_fuzzy(dt, ct) >= 0.80 for ct in cand_tokens)
    )
    token_score = (token_hits / max(len(cand_tokens), 1)) * 0.85  # cap at 85%

    # Email-prefix match
    email_score = _fuzzy(display, email_prefix) if email_prefix else 0.0

    best = max(full_score, token_score, email_score)

    ev = {
        "full_name_similarity": round(full_score, 3),
        "token_name_score": round(token_score, 3),
        "email_prefix_similarity": round(email_score, 3),
    }

    if best >= 0.90:
        reason = f"'{display}' is an exact / near-exact match for candidate '{cand}'"
    elif best >= 0.75:
        reason = f"'{display}' is a strong fuzzy match for '{cand}' ({best:.0%})"
    elif best >= 0.55:
        reason = f"'{display}' is a partial name match for '{cand}' ({best:.0%}) — possible nickname"
    else:
        reason = f"'{display}' does not resemble candidate name '{cand}'"

    return SignalResult(
        signal_type=SignalType.NAME_MATCH,
        score=min(1.0, max(0.0, best)),
        signal_confidence=0.90,
        reason=reason,
        evidence=ev,
    )


# ---------------------------------------------------------------------------
# 2. Interviewer Exclusion
# ---------------------------------------------------------------------------

def compute_interviewer_exclusion(
    participant: ParticipantState,
    context: MeetingContext,
    all_participants: List[ParticipantState],
) -> SignalResult:
    """
    If this participant's name / email matches a known interviewer → strong NOT-candidate signal.
    If they're not in the known-interviewer list → neutral-positive signal.
    """
    display = participant.display_name
    email = (participant.email or "").lower()

    # --- Email match (highest confidence) ---
    for ie in context.interviewer_emails:
        if email and email == ie.lower():
            return SignalResult(
                signal_type=SignalType.INTERVIEWER_EXCLUSION,
                score=0.02,
                signal_confidence=0.98,
                reason=f"Email '{email}' exactly matches known interviewer",
                evidence={"matched_interviewer_email": ie},
            )

    # --- Name fuzzy match ---
    name_matches = [
        (iname, _fuzzy(display, iname))
        for iname in context.interviewer_names
        if _fuzzy(display, iname) >= 0.75
    ]

    if name_matches:
        best_name, best_score = max(name_matches, key=lambda x: x[1])
        return SignalResult(
            signal_type=SignalType.INTERVIEWER_EXCLUSION,
            score=0.04,
            signal_confidence=0.85,
            reason=f"'{display}' matches known interviewer '{best_name}' ({best_score:.0%})",
            evidence={"matched_interviewer_name": best_name, "similarity": round(best_score, 3)},
        )

    # --- Same company domain as interviewers (but not same as candidate) ---
    if email and context.interviewer_emails:
        part_domain = email.split("@")[1] if "@" in email else ""
        cand_domain = context.candidate_email.split("@")[1] if "@" in context.candidate_email else ""
        iview_domains = {ie.split("@")[1].lower() for ie in context.interviewer_emails if "@" in ie}
        if part_domain and part_domain in iview_domains and part_domain != cand_domain:
            return SignalResult(
                signal_type=SignalType.INTERVIEWER_EXCLUSION,
                score=0.08,
                signal_confidence=0.80,
                reason=f"Email domain '@{part_domain}' matches interviewer org",
                evidence={"domain": part_domain},
            )

    # --- Not matched — neutral-positive ---
    has_context = bool(context.interviewer_names or context.interviewer_emails)
    return SignalResult(
        signal_type=SignalType.INTERVIEWER_EXCLUSION,
        score=0.68 if has_context else 0.50,
        signal_confidence=0.80 if has_context else 0.25,
        reason=f"Not found in {len(context.interviewer_names)} known interviewer(s) — possible candidate",
        evidence={"known_interviewers": len(context.interviewer_names)},
    )


# ---------------------------------------------------------------------------
# 3. Email Match
# ---------------------------------------------------------------------------

def compute_email_match(
    participant: ParticipantState,
    context: MeetingContext,
    all_participants: List[ParticipantState],
) -> SignalResult:
    """
    Direct email comparison — the most reliable signal when available.
    """
    cand_email = context.candidate_email.lower().strip() if context.candidate_email else ""
    part_email = (participant.email or "").lower().strip()

    if not cand_email:
        return SignalResult(
            signal_type=SignalType.EMAIL_MATCH,
            score=0.5,
            signal_confidence=0.0,
            reason="No candidate email in ATS — signal unavailable",
            evidence={},
        )

    if not part_email:
        return SignalResult(
            signal_type=SignalType.EMAIL_MATCH,
            score=0.5,
            signal_confidence=0.15,
            reason="Participant email not exposed by meeting platform",
            evidence={},
        )

    if part_email == cand_email:
        return SignalResult(
            signal_type=SignalType.EMAIL_MATCH,
            score=1.0,
            signal_confidence=0.99,
            reason=f"Exact email match: {cand_email}",
            evidence={"matched_email": cand_email},
        )

    # Check interviewer domain
    iview_domains = {ie.split("@")[1].lower() for ie in context.interviewer_emails if "@" in ie}
    part_domain = part_email.split("@")[1] if "@" in part_email else ""
    cand_domain = cand_email.split("@")[1] if "@" in cand_email else ""
    if part_domain and part_domain in iview_domains and part_domain != cand_domain:
        return SignalResult(
            signal_type=SignalType.EMAIL_MATCH,
            score=0.04,
            signal_confidence=0.85,
            reason=f"'{part_email}' domain matches interviewer org — not candidate",
            evidence={"part_domain": part_domain},
        )

    return SignalResult(
        signal_type=SignalType.EMAIL_MATCH,
        score=0.05,
        signal_confidence=0.90,
        reason=f"'{part_email}' does not match candidate email '{cand_email}'",
        evidence={"participant_email": part_email, "candidate_email": cand_email},
    )


# ---------------------------------------------------------------------------
# 4. Speaking Pattern
# ---------------------------------------------------------------------------

def compute_speaking_pattern(
    participant: ParticipantState,
    context: MeetingContext,
    all_participants: List[ParticipantState],
) -> SignalResult:
    """
    Candidates answer questions → longer continuous speaking turns.
    Interviewers ask questions → shorter, frequent bursts.

    Scoring is on average turn length and speaking share.
    """
    dur = participant.speaking_duration
    turns = participant.speaking_turns

    if dur < 8.0:
        return SignalResult(
            signal_type=SignalType.SPEAKING_PATTERN,
            score=0.5,
            signal_confidence=0.05,
            reason=f"Only {dur:.1f}s of speaking — insufficient data",
            evidence={"speaking_duration": dur},
        )

    avg_turn = dur / max(turns, 1)

    # Turn-length heuristic score
    # Candidate: 30–120s avg; Interviewer: 5–20s avg
    if avg_turn >= 90:
        turn_score = 0.92
    elif avg_turn >= 60:
        turn_score = 0.85
    elif avg_turn >= 30:
        turn_score = 0.75
    elif avg_turn >= 15:
        turn_score = 0.55
    elif avg_turn >= 8:
        turn_score = 0.40
    else:
        turn_score = 0.20

    # Speaking-share heuristic
    total_dur = sum(p.speaking_duration for p in all_participants)
    n_active = sum(1 for p in all_participants if p.speaking_duration >= 5)
    speaking_share = dur / total_dur if total_dur > 0 else 0.0
    expected_share = 1.0 / max(n_active, 1)

    if speaking_share > expected_share * 1.3:
        share_score = 0.72
    elif speaking_share > expected_share * 0.9:
        share_score = 0.58
    else:
        share_score = 0.38

    combined = turn_score * 0.70 + share_score * 0.30
    # Confidence grows with more speaking data
    confidence = min(0.78, 0.20 + (dur / 180) * 0.58)

    if avg_turn >= 30:
        reason = (
            f"Long avg speaking turns ({avg_turn:.0f}s) — consistent with "
            f"detailed interview answers (candidate pattern)"
        )
    elif avg_turn <= 10:
        reason = (
            f"Short avg speaking turns ({avg_turn:.0f}s) — consistent with "
            f"asking short questions (interviewer pattern)"
        )
    else:
        reason = f"Moderate speaking turns ({avg_turn:.0f}s avg) — pattern still developing"

    return SignalResult(
        signal_type=SignalType.SPEAKING_PATTERN,
        score=round(combined, 4),
        signal_confidence=round(confidence, 4),
        reason=reason,
        evidence={
            "speaking_duration": round(dur, 1),
            "speaking_turns": turns,
            "avg_turn_length_s": round(avg_turn, 1),
            "speaking_share": round(speaking_share, 3),
        },
    )


# ---------------------------------------------------------------------------
# 5. Transcript Language
# ---------------------------------------------------------------------------

def compute_transcript_language(
    participant: ParticipantState,
    context: MeetingContext,
    all_participants: List[ParticipantState],
) -> SignalResult:
    """
    Pattern-match transcript segments for first-person experience language
    (candidate) vs. question/evaluation language (interviewer).
    """
    if not participant.transcript_segments:
        return SignalResult(
            signal_type=SignalType.TRANSCRIPT_LANGUAGE,
            score=0.5,
            signal_confidence=0.0,
            reason="No transcript data yet",
            evidence={},
        )

    text = " ".join(participant.transcript_segments)
    word_count = len(text.split())

    if word_count < 25:
        return SignalResult(
            signal_type=SignalType.TRANSCRIPT_LANGUAGE,
            score=0.5,
            signal_confidence=0.08,
            reason=f"Only {word_count} words transcribed — too little for reliable analysis",
            evidence={"word_count": word_count},
        )

    c_hits = sum(1 for r in _CANDIDATE_RES if r.search(text))
    i_hits = sum(1 for r in _INTERVIEWER_RES if r.search(text))
    total_hits = c_hits + i_hits

    if total_hits == 0:
        score, reason = 0.50, "No distinctive speech patterns matched"
    else:
        ratio = c_hits / total_hits
        # Map [0,1] ratio → [0.15, 0.85] score
        score = 0.15 + ratio * 0.70
        if ratio >= 0.65:
            reason = (
                f"{c_hits}/{total_hits} candidate-style phrase patterns detected "
                f"(e.g. 'I built', 'my experience', 'for example')"
            )
        elif ratio <= 0.35:
            reason = (
                f"{i_hits}/{total_hits} interviewer-style phrase patterns detected "
                f"(e.g. 'tell me about', 'how did you', 'can you describe')"
            )
        else:
            reason = f"Mixed speech patterns: {c_hits} candidate, {i_hits} interviewer indicators"

    confidence = min(0.72, 0.15 + (word_count / 600) * 0.57)

    return SignalResult(
        signal_type=SignalType.TRANSCRIPT_LANGUAGE,
        score=round(score, 4),
        signal_confidence=round(confidence, 4),
        reason=reason,
        evidence={
            "word_count": word_count,
            "candidate_pattern_hits": c_hits,
            "interviewer_pattern_hits": i_hits,
        },
    )


# ---------------------------------------------------------------------------
# 6. Join Order
# ---------------------------------------------------------------------------

def compute_join_order(
    participant: ParticipantState,
    context: MeetingContext,
    all_participants: List[ParticipantState],
) -> SignalResult:
    """
    Candidates are invited to a meeting they didn't organise → tend to join after interviewers.
    Weak signal — eager candidates sometimes join first.
    """
    n = len(all_participants)
    order = participant.join_order

    if n <= 1:
        return SignalResult(
            signal_type=SignalType.JOIN_ORDER,
            score=0.5,
            signal_confidence=0.02,
            reason="Only participant — join order provides no signal",
            evidence={},
        )

    if order == 1:
        score, reason = 0.32, f"Joined first of {n} — organisers tend to join first (interviewer pattern)"
    elif order == n:
        score, reason = 0.68, f"Joined last (#{order} of {n}) — invited guests tend to join last (candidate pattern)"
    else:
        frac = (order - 1) / (n - 1)
        score = 0.42 + frac * 0.18
        reason = f"Joined #{order} of {n} — mid-range join order, limited signal"

    return SignalResult(
        signal_type=SignalType.JOIN_ORDER,
        score=round(score, 4),
        signal_confidence=0.28,
        reason=reason,
        evidence={"join_order": order, "total_participants": n},
    )


# ---------------------------------------------------------------------------
# 7. Screen Share
# ---------------------------------------------------------------------------

def compute_screen_share(
    participant: ParticipantState,
    context: MeetingContext,
    all_participants: List[ParticipantState],
) -> SignalResult:
    """
    In most interviews, interviewers share their screen (job desc, coding prompt).
    Candidates rarely share unless it's a live-coding session.
    Very weak signal.
    """
    any_share = any(p.has_shared_screen for p in all_participants)

    if not any_share:
        return SignalResult(
            signal_type=SignalType.SCREEN_SHARE,
            score=0.5,
            signal_confidence=0.03,
            reason="No screen sharing has occurred — signal unavailable",
            evidence={},
        )

    if participant.has_shared_screen:
        return SignalResult(
            signal_type=SignalType.SCREEN_SHARE,
            score=0.38,
            signal_confidence=0.22,
            reason="Shared screen — slightly more common for interviewers, but occurs in technical interviews",
            evidence={"screen_share_duration": round(participant.screen_share_duration, 1)},
        )

    return SignalResult(
        signal_type=SignalType.SCREEN_SHARE,
        score=0.58,
        signal_confidence=0.20,
        reason="Did not share screen — slight candidate signal",
        evidence={},
    )


# ---------------------------------------------------------------------------
# 8. Face Match — pre-meeting biometric reference (highest weight)
# ---------------------------------------------------------------------------
#
# Unlike every other signal, this doesn't ask "does this look like the
# candidate given the meeting so far" — it asks "does this frame match a
# reference embedding captured BEFORE the meeting even started." That's why
# it can carry a much higher weight: it's not inferring from behavior, it's
# checking against enrolled ground truth. It's still blended (not a hard
# override) because face matching has a real error rate under bad lighting,
# poor angle, or camera compression — see SIGNAL_WEIGHTS comment in models.py.

def _rescale(sim: float, reject_at: float, match_at: float) -> float:
    """Linearly rescale a similarity value onto [0,1], anchored so that
    `reject_at` -> 0 and `match_at` -> 1. Clamped at the ends. This is used
    instead of a generic [-1,1]->[0,1] map because different embedding
    techniques compress their similarity range very differently (e.g. the
    lightweight MFCC descriptor in biometrics.py sits entirely within
    ~0.97-1.0) — anchoring to the calibrated thresholds is what makes the
    resulting score actually discriminate match vs no-match."""
    if match_at == reject_at:
        return 0.5
    frac = (sim - reject_at) / (match_at - reject_at)
    return max(0.0, min(1.0, frac))


_FACE_MATCH_THRESHOLD = 0.55   # cosine sim above this = same person
_FACE_REJECT_THRESHOLD = 0.30  # below this = confidently a different person


def compute_face_match(
    participant: ParticipantState,
    context: MeetingContext,
    all_participants: List[ParticipantState],
) -> SignalResult:
    if context.candidate_face_embedding is None:
        return SignalResult(
            signal_type=SignalType.FACE_MATCH,
            score=0.5,
            signal_confidence=0.0,
            reason="No pre-meeting face reference enrolled — signal unavailable",
            evidence={},
        )

    if participant.latest_face_embedding is None:
        return SignalResult(
            signal_type=SignalType.FACE_MATCH,
            score=0.5,
            signal_confidence=0.0,
            reason="No face detected yet (webcam off, or no frame captured)",
            evidence={},
        )

    if not participant.latest_face_liveness_ok:
        # A "match" against a static photo/spoof shouldn't be trusted as a
        # positive signal — treat it as suspicious rather than confirmatory.
        return SignalResult(
            signal_type=SignalType.FACE_MATCH,
            score=0.10,
            signal_confidence=0.75,
            reason="Liveness check failed on this frame — possible photo/spoof attempt",
            evidence={"liveness_ok": False},
        )

    sim = _cosine_similarity(context.candidate_face_embedding, participant.latest_face_embedding)
    # NOTE: 0.55/0.30 are reasonable starting anchors for the pixel-descriptor
    # in biometrics.py but are NOT empirically calibrated against real face
    # photos (this sandbox has no real photo data to test against — see
    # conversation notes). Calibrate against real enrollment/webcam pairs
    # before relying on this in production; same caveat applies if this is
    # swapped for a real ArcFace embedding, which has its own typical range.
    score = _rescale(sim, _FACE_REJECT_THRESHOLD, _FACE_MATCH_THRESHOLD)

    if sim >= _FACE_MATCH_THRESHOLD:
        reason = f"Face matches enrolled reference (similarity={sim:.2f})"
        confidence = 0.95
    elif sim <= _FACE_REJECT_THRESHOLD:
        reason = f"Face does NOT match enrolled reference (similarity={sim:.2f})"
        confidence = 0.90
    else:
        reason = f"Face match inconclusive (similarity={sim:.2f})"
        confidence = 0.5

    return SignalResult(
        signal_type=SignalType.FACE_MATCH,
        score=score,
        signal_confidence=confidence,
        reason=reason,
        evidence={"cosine_similarity": round(sim, 4)},
    )


# ---------------------------------------------------------------------------
# 9. Voice Match — pre-meeting biometric reference
# ---------------------------------------------------------------------------

# NOTE ON THRESHOLDS: these are calibrated for the lightweight MFCC
# mean/std descriptor in biometrics.py, NOT a generic [-1,1] cosine range.
# Measured empirically: same-speaker clips land around sim≈0.999+, while
# clearly different speakers still land around sim≈0.97-0.98 — MFCC-pooled
# vectors are dominated by generic speech-spectrum shape, not speaker
# identity, so similarity is compressed near 1.0 regardless of match. If
# biometrics.extract_voice_embedding() is swapped for a real deep
# speaker-embedding model (ECAPA-TDNN etc), these thresholds MUST be
# recalibrated — deep speaker embeddings typically separate same/different
# speakers much more widely (e.g. same-speaker ~0.7-0.9, different ~0.0-0.3).
_VOICE_MATCH_THRESHOLD = 0.995
_VOICE_REJECT_THRESHOLD = 0.985


def compute_voice_match(
    participant: ParticipantState,
    context: MeetingContext,
    all_participants: List[ParticipantState],
) -> SignalResult:
    if context.candidate_voice_embedding is None:
        return SignalResult(
            signal_type=SignalType.VOICE_MATCH,
            score=0.5,
            signal_confidence=0.0,
            reason="No pre-meeting voice reference enrolled — signal unavailable",
            evidence={},
        )

    if participant.latest_voice_embedding is None:
        return SignalResult(
            signal_type=SignalType.VOICE_MATCH,
            score=0.5,
            signal_confidence=0.0,
            reason="No voice sample captured yet (muted, or not yet spoken)",
            evidence={},
        )

    sim = _cosine_similarity(context.candidate_voice_embedding, participant.latest_voice_embedding)
    # Rescale using the calibrated thresholds as anchors (NOT a generic
    # [-1,1] -> [0,1] map) — see threshold comment above for why: this
    # descriptor's similarities are compressed near 1.0, so anchoring the
    # score to the actual reject/match boundary is what makes "no match"
    # actually pull the composite score down instead of barely moving it.
    score = _rescale(sim, _VOICE_REJECT_THRESHOLD, _VOICE_MATCH_THRESHOLD)

    if sim >= _VOICE_MATCH_THRESHOLD:
        reason = f"Voice matches enrolled reference (similarity={sim:.2f})"
        confidence = 0.90
    elif sim <= _VOICE_REJECT_THRESHOLD:
        reason = f"Voice does NOT match enrolled reference (similarity={sim:.2f})"
        confidence = 0.85
    else:
        reason = f"Voice match inconclusive (similarity={sim:.2f}) — short/noisy sample"
        confidence = 0.4

    return SignalResult(
        signal_type=SignalType.VOICE_MATCH,
        score=score,
        signal_confidence=confidence,
        reason=reason,
        evidence={"cosine_similarity": round(sim, 4)},
    )


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

ALL_SIGNAL_FUNCS = {
    SignalType.NAME_MATCH: compute_name_match,
    SignalType.EMAIL_MATCH: compute_email_match,
    SignalType.INTERVIEWER_EXCLUSION: compute_interviewer_exclusion,
    SignalType.SPEAKING_PATTERN: compute_speaking_pattern,
    SignalType.TRANSCRIPT_LANGUAGE: compute_transcript_language,
    SignalType.JOIN_ORDER: compute_join_order,
    SignalType.SCREEN_SHARE: compute_screen_share,
    SignalType.FACE_MATCH: compute_face_match,
    SignalType.VOICE_MATCH: compute_voice_match,
}


def compute_all_signals(
    participant: ParticipantState,
    context: MeetingContext,
    all_participants: List[ParticipantState],
) -> None:
    """Recompute all signals in-place on participant.signals."""
    for sig_type, fn in ALL_SIGNAL_FUNCS.items():
        participant.signals[sig_type] = fn(participant, context, all_participants)