"""
biometrics.py — real (not mocked) embedding extraction for face + voice.

IMPORTANT — honest scope of what this is:

This module produces genuine, working, comparable embeddings from real
image/audio bytes — it is NOT a mock. But the specific techniques used are
deliberately lightweight so they run anywhere with zero external model
downloads (no GPU, no multi-hundred-MB weights, no calls to Google/Meta
model-hosting endpoints):

  - Face:  OpenCV Haar-cascade detection (ships inside opencv-python,
           nothing to download) + a normalized grayscale pixel descriptor
           of the cropped face. This is the "eigenface"-era approach —
           real and functional, but meaningfully weaker than a modern deep
           embedding model.
  - Voice: librosa MFCC (mel-frequency cepstral coefficient) mean/std
           pooling — a classical, real speaker-characteristic descriptor,
           weaker than a trained deep speaker-embedding model.

SWAP POINT FOR PRODUCTION: both extract_face_embedding() and
extract_voice_embedding() have a stable signature (bytes in, List[float]
or None out). To upgrade to production-grade accuracy, replace the body of
each with a call to:
  - Face:  InsightFace / ArcFace (buffalo_l) via `insightface` + onnxruntime
  - Voice: ECAPA-TDNN via SpeechBrain (`speechbrain.pretrained.EncoderClassifier`)
...and nothing in server.py, signals.py, or engine.py needs to change, since
they only ever see a List[float] embedding and a cosine similarity — this
module is the only thing that would need to change.
"""

from __future__ import annotations

import io
import logging
from typing import List, Optional

import numpy as np

log = logging.getLogger("sherlock.biometrics")

_FACE_SIZE = 64  # face crop is resized to _FACE_SIZE x _FACE_SIZE before descriptor extraction


# ---------------------------------------------------------------------------
# Face
# ---------------------------------------------------------------------------

_face_cascade = None


def _get_face_cascade():
    global _face_cascade
    if _face_cascade is None:
        import cv2

        _face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _face_cascade


def extract_face_embedding(image_bytes: bytes) -> Optional[List[float]]:
    """
    Detect the largest face in `image_bytes` and return a normalized
    descriptor vector, or None if no face is detected (this is the Stage-B
    validation gate: a bad/no-face reference should never be silently
    enrolled).
    """
    import cv2

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        log.warning("extract_face_embedding: could not decode image bytes")
        return None

    cascade = _get_face_cascade()
    faces = cascade.detectMultiScale(img, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    if len(faces) == 0:
        return None

    # Largest detected face (by area) — assume that's the subject, not a
    # smaller face incidentally in frame/background.
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    face = img[y : y + h, x : x + w]
    face = cv2.resize(face, (_FACE_SIZE, _FACE_SIZE)).astype(np.float32)

    # Normalize illumination (zero mean, unit variance) so lighting
    # differences between enrollment photo and live webcam frame matter
    # less than they otherwise would.
    face = (face - face.mean()) / (face.std() + 1e-6)

    vec = face.flatten()
    vec = vec / (np.linalg.norm(vec) + 1e-6)
    return vec.tolist()


def check_liveness(prev_embedding: Optional[List[float]], curr_embedding: List[float]) -> bool:
    """
    Minimal liveness heuristic: a perfectly static photo held up to the
    camera produces near-IDENTICAL consecutive embeddings (since nothing
    in the frame moves at all beyond sensor noise), whereas a real face on
    a live feed has small natural motion. Flags "too perfectly static" as
    suspicious.

    HONEST LIMITATION: this is trivially defeated by a video replay (which
    has natural motion). Production liveness needs texture/frequency-domain
    spoof detection and/or an active challenge (e.g. "turn your head"), not
    just frame-to-frame similarity. Documented as a known gap, not solved.
    """
    if prev_embedding is None:
        return True  # first sample — nothing to compare against yet
    sim = float(np.dot(prev_embedding, curr_embedding))
    # Cosine similarity near-exactly 1.0 across consecutive frames is more
    # consistent with a static photo than a live human face.
    return sim < 0.9995


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------

def extract_voice_embedding(audio_bytes: bytes, sr: int = 16000) -> Optional[List[float]]:
    """
    MFCC mean/std descriptor from a raw audio clip (wav/flac/etc, anything
    soundfile can decode). Returns None if the clip is silent, too short,
    or fails to decode — same validation-gate principle as the face path.
    """
    import librosa
    import soundfile as sf

    try:
        data, orig_sr = sf.read(io.BytesIO(audio_bytes), dtype="float32", always_2d=False)
    except Exception as e:
        log.warning("extract_voice_embedding: could not decode audio bytes: %s", e)
        return None

    if data.ndim > 1:
        data = data.mean(axis=1)  # downmix to mono

    if orig_sr != sr:
        data = librosa.resample(data, orig_sr=orig_sr, target_sr=sr)

    if len(data) < sr * 0.5:  # require at least 0.5s of audio
        return None

    # Basic voice-activity check — reject near-silent clips rather than
    # enrolling a meaningless reference.
    rms = float(np.sqrt(np.mean(data**2)))
    if rms < 1e-4:
        return None

    mfcc = librosa.feature.mfcc(y=data, sr=sr, n_mfcc=20)
    # Mean + std pooling across time -> fixed-length vector regardless of
    # clip duration.
    desc = np.concatenate([mfcc.mean(axis=1), mfcc.std(axis=1)])
    desc = desc / (np.linalg.norm(desc) + 1e-6)
    return desc.tolist()