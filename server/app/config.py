"""Runtime settings, read from environment variables (or a local .env file).

Every value has a safe default for local development. In production
(Railway), set them in the service's "Variables" tab.
"""

import os
import secrets
from pathlib import Path

from dotenv import dotenv_values

SERVER_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVER_DIR.parent


def _load_env_files(*paths: Path) -> None:
    """Load .env files without letting blank values hide real ones.

    Order of precedence: real environment variables, then server/.env, then
    the project-root .env (where GEMINI_API_KEY lived before). A line like
    `GEMINI_API_KEY=` with nothing after it is ignored, so an unfilled copy
    of .env.example can't override a key set in the other file.
    """
    for path in paths:
        for key, value in dotenv_values(path).items():
            if value and not os.environ.get(key):
                os.environ[key] = value


_load_env_files(SERVER_DIR / ".env", PROJECT_ROOT / ".env")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# Frames per second Gemini samples from the video. 1 is Gemini's default.
# Higher values catch fast moves (dynos) but multiply video tokens.
GEMINI_VIDEO_FPS = _float("GEMINI_VIDEO_FPS", 1.0)

# Beta protection
# Shared token budget across all testers, reset every UTC day.
DAILY_TOKEN_BUDGET = _int("DAILY_TOKEN_BUDGET", 1_000_000)
# Analyses one tester can start per UTC day.
PER_TESTER_DAILY_ANALYSES = _int("PER_TESTER_DAILY_ANALYSES", 15)
# Token reservations checked before a Gemini call is allowed to start.
# Actual usage reported by Gemini is what gets recorded afterwards.
ESTIMATED_VIDEO_ANALYSIS_TOKENS = _int("ESTIMATED_VIDEO_ANALYSIS_TOKENS", 15_000)
ESTIMATED_COACHING_TOKENS = _int("ESTIMATED_COACHING_TOKENS", 8_000)
# Protects the /api/admin endpoints that create and revoke invite codes.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
# Signs short-lived video links. Set it in production so links survive restarts.
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)

# Video limits
MAX_VIDEO_SECONDS = _float("MAX_VIDEO_SECONDS", 20.0)
# Small allowance for container rounding (a "20 s" phone clip is often 20.03 s).
DURATION_TOLERANCE_SECONDS = 0.5
MAX_UPLOAD_BYTES = _int("MAX_UPLOAD_MB", 250) * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".3gp"}
# Normalized analysis copy: shorter side in pixels, constant frame rate.
NORMALIZED_SHORT_SIDE = _int("NORMALIZED_SHORT_SIDE", 720)
NORMALIZED_FPS = _int("NORMALIZED_FPS", 30)

# Wall angle (degrees past vertical: negative = slab, positive = overhang)
MIN_WALL_ANGLE = -30.0
MAX_WALL_ANGLE = 80.0

# Storage
DATA_DIR = Path(os.getenv("DATA_DIR", str(SERVER_DIR / "data"))).resolve()
DB_PATH = DATA_DIR / "climbing_coach.sqlite3"
ANALYSES_DIR = DATA_DIR / "analyses"
RETENTION_DAYS = _int("RETENTION_DAYS", 30)

# MediaPipe
MODEL_PATH = Path(
    os.getenv("POSE_MODEL_PATH", str(SERVER_DIR / "models" / "pose_landmarker_full.task"))
).resolve()
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_full/float16/latest/pose_landmarker_full.task"
)

# Server
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
JOB_WORKERS = _int("JOB_WORKERS", 2)
