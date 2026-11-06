"""All timers and thresholds live here, behind DEMO_MODE.

DEMO_MODE is on by default so the live demo shows state changes in seconds.
Set BIRDIE_DEMO_MODE=0 in the environment for production timings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEMO_MODE: bool = os.getenv("BIRDIE_DEMO_MODE", "1").strip().lower() not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class Timers:
    """Timers in seconds. One instance for demo mode and one for production."""

    hold_seconds: int  # HELD -> REVIEW_REQUIRED after belongings remain unattended this long
    smoothing_frames: int  # an observation only counts after k consecutive frames
    camera_stale_seconds: int  # live seat states expire when no usable frame arrives for this long


DEMO_TIMERS = Timers(
    hold_seconds=30,
    smoothing_frames=3,
    camera_stale_seconds=10,
)

PRODUCTION_TIMERS = Timers(
    hold_seconds=30 * 60,
    smoothing_frames=3,
    camera_stale_seconds=10,
)

TIMERS: Timers = DEMO_TIMERS if DEMO_MODE else PRODUCTION_TIMERS

# --- Vision ---------------------------------------------------------------
DETECTOR_MODEL_ID = "PekingU/rtdetr_r18vd"
DETECTION_THRESHOLD = 0.4  # minimum detector score that counts for seat states
UNCERTAIN_DETECTION_THRESHOLD = 0.2  # lower scores make an affected seat UNKNOWN, never FREE
MAX_FRAME_SIDE = 640  # long side of a frame is resized to at most this many pixels
TARGET_FPS = 1.0  # frames per second sent from the browser / sampled from clips
MIN_OVERLAP = 0.2  # fallback seat assignment: box must overlap the seat polygon by more than this

# --- Scheduler ------------------------------------------------------------
SCHEDULER_INTERVAL_SECONDS = 2.0

# --- Forecast -------------------------------------------------------------
BUCKET_MINUTES = 15
SYNTHETIC_HISTORY_WEEKS = 4
CHRONOS_MODEL_ID = "amazon/chronos-bolt-small"
USE_CHRONOS = os.getenv("BIRDIE_USE_CHRONOS", "0").strip().lower() in ("1", "true", "yes", "on")

# --- Paths ----------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("BIRDIE_DATA_DIR", ROOT_DIR / "data"))
DB_PATH = Path(os.getenv("BIRDIE_DB_PATH", DATA_DIR / "birdie.db"))
VENUES_DIR = Path(os.getenv("BIRDIE_VENUES_DIR", ROOT_DIR / "venues"))

# --- Venues ---------------------------------------------------------------
LIVE_VENUE_ID = "nestwork-msheireb"
