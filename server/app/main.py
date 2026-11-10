"""AI Climbing Coach API (mobile beta).

Run locally from the server/ folder:
    python -m uvicorn app.main:app --reload
"""

import logging
import math
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import auth, budget, config, db, gemini_service, jobs, video_utils
from app.coaching_cache import create_coaching_fingerprint, load_cached_coaching, save_cached_coaching
from app.metrics_summary import summarize_metrics
from app.pose_processor import ensure_model
from app.wall_geometry import wall_category

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("climbing_coach")

_stop_cleanup = threading.Event()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    interrupted = db.fail_interrupted_analyses()
    if interrupted:
        log.warning("Marked %d interrupted analyses as failed", interrupted)
    try:
        ensure_model()
    except Exception:
        log.exception("Could not download the MediaPipe model; pose analysis will fail")
    if not config.GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY is not set: Gemini stages will be skipped")
    if not config.ADMIN_TOKEN:
        log.warning("ADMIN_TOKEN is not set: invite codes cannot be created")
    jobs.start_cleanup_loop(_stop_cleanup)
    yield
    _stop_cleanup.set()


app = FastAPI(title="AI Climbing Coach API", version="1.0.0-beta", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Token"],
)


# Helpers

def _validate_id(analysis_id: str) -> str:
    try:
        return UUID(hex=analysis_id).hex
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid analysis ID.")


def _owned_analysis(analysis_id: str, tester: dict) -> dict:
    analysis = db.get_analysis(_validate_id(analysis_id))
    if analysis is None or analysis["tester_id"] != tester["id"]:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    if analysis["status"] == "expired":
        raise HTTPException(status_code=410, detail="This analysis was deleted after the retention period.")
    return analysis


def _serialize(analysis: dict) -> dict:
    has_video = (
        analysis["stages"]["normalize"]["status"] == "done"
        and jobs.video_path(analysis["id"]).is_file()
    )
    return {
        "id": analysis["id"],
        "created_at": analysis["created_at"],
        "original_filename": analysis["original_filename"],
        "wall_angle_deg": analysis["wall_angle_deg"],
        "wall_label": analysis["wall_label"],
        "wall_category": wall_category(analysis["wall_angle_deg"]),
        "duration_seconds": analysis["duration_seconds"],
        "status": analysis["status"],
        "error": analysis["error"],
        "stages": analysis["stages"],
        "video_url": auth.sign_video_link(analysis["id"]) if has_video else None,
    }


def _require_stage(analysis: dict, stage: str, name: str):
    status = analysis["stages"][stage]["status"]
    if status != "done":
        raise HTTPException(status_code=409, detail=f"{name} is not ready (status: {status}).")


# Public

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "AI Climbing Coach", "version": app.version}


# Tester

@app.get("/api/me")
def me(tester: dict = Depends(auth.require_tester)):
    return {
        "name": tester["name"],
        "analyses_today": db.count_analyses_today(tester["id"]),
        "daily_analysis_limit": config.PER_TESTER_DAILY_ANALYSES,
        "ai_budget_available": budget.can_afford(config.ESTIMATED_VIDEO_ANALYSIS_TOKENS),
        "max_video_seconds": config.MAX_VIDEO_SECONDS,
    }


@app.post("/api/analyses", status_code=202)
def create_analysis(
    file: UploadFile = File(...),
    wall_angle_deg: float = Form(...),
    wall_label: str | None = Form(default=None),
    tester: dict = Depends(auth.require_tester),
):
    if not math.isfinite(wall_angle_deg) or not (config.MIN_WALL_ANGLE <= wall_angle_deg <= config.MAX_WALL_ANGLE):
        raise HTTPException(
            status_code=400,
            detail=f"Wall angle must be between {config.MIN_WALL_ANGLE:g} and {config.MAX_WALL_ANGLE:g} degrees.",
        )

    if db.count_analyses_today(tester["id"]) >= config.PER_TESTER_DAILY_ANALYSES:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily limit reached ({config.PER_TESTER_DAILY_ANALYSES} analyses). "
                "It resets at 00:00 UTC (7 PM Eastern)."
            ),
        )

    original_filename = (file.filename or "video").strip()[:200]
    extension = Path(original_filename).suffix.lower() or ".mp4"
    if extension not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported video format. Use MP4 or MOV.")

    analysis_id = uuid4().hex
    jobs.analysis_dir(analysis_id).mkdir(parents=True, exist_ok=True)
    raw_path = jobs.raw_upload_path(analysis_id, extension)

    try:
        size = 0
        with raw_path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Video exceeds the {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                    )
                output.write(chunk)

        # Enforced here, on the server, before any Gemini tokens can be spent.
        try:
            duration = video_utils.probe_duration(raw_path)
            video_utils.check_duration(duration)
        except video_utils.VideoError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        import shutil
        shutil.rmtree(jobs.analysis_dir(analysis_id), ignore_errors=True)
        raise
    finally:
        file.file.close()

    label = (wall_label or "").strip()[:40] or None
    analysis = db.create_analysis(
        analysis_id, tester["id"], original_filename, wall_angle_deg, label, round(duration, 2)
    )
    jobs.submit(analysis_id, raw_path, tester["id"], wall_angle_deg)
    return _serialize(analysis)


@app.get("/api/analyses")
def list_analyses(tester: dict = Depends(auth.require_tester)):
    return [_serialize(a) for a in db.list_analyses(tester["id"])]


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str, tester: dict = Depends(auth.require_tester)):
    return _serialize(_owned_analysis(analysis_id, tester))


@app.get("/api/analyses/{analysis_id}/pose")
def get_pose(analysis_id: str, tester: dict = Depends(auth.require_tester)):
    """Skeleton overlay data, rule-based feedback and summary metrics."""
    analysis = _owned_analysis(analysis_id, tester)
    _require_stage(analysis, "pose", "Pose analysis")
    metrics = jobs.read_json(jobs.result_path(analysis["id"], "metrics"))
    return {
        "overlay": jobs.read_json(jobs.result_path(analysis["id"], "overlay")),
        "feedback": jobs.read_json(jobs.result_path(analysis["id"], "feedback")),
        "summary": {
            "video": metrics["video"],
            "wall": metrics["wall"],
            "tracking": metrics["tracking"],
            "scale": metrics["scale"],
            "left_arm": metrics["left_arm"]["summary"],
            "right_arm": metrics["right_arm"]["summary"],
        },
    }


@app.get("/api/analyses/{analysis_id}/metrics")
def get_metrics(analysis_id: str, tester: dict = Depends(auth.require_tester)):
    """Full per-frame metrics (large)."""
    analysis = _owned_analysis(analysis_id, tester)
    _require_stage(analysis, "pose", "Pose analysis")
    return FileResponse(jobs.result_path(analysis["id"], "metrics"), media_type="application/json")


@app.get("/api/analyses/{analysis_id}/hybrid")
def get_hybrid(analysis_id: str, tester: dict = Depends(auth.require_tester)):
    analysis = _owned_analysis(analysis_id, tester)
    _require_stage(analysis, "hybrid", "Movement analysis")
    return {
        "movements": jobs.read_json(jobs.result_path(analysis["id"], "gemini_movements"))["movements"],
        "hybrid_feedback": jobs.read_json(jobs.result_path(analysis["id"], "hybrid_feedback")),
    }


@app.post("/api/analyses/{analysis_id}/coaching")
def coaching(analysis_id: str, tester: dict = Depends(auth.require_tester)):
    analysis = _owned_analysis(analysis_id, tester)
    _require_stage(analysis, "pose", "Pose analysis")
    if analysis["stages"]["gemini"]["status"] in ("pending", "running"):
        raise HTTPException(status_code=409, detail="Wait for the movement analysis to finish first.")

    aid = analysis["id"]
    metrics = jobs.read_json(jobs.result_path(aid, "metrics"))
    feedback = jobs.read_json(jobs.result_path(aid, "feedback"))
    movements_path = jobs.result_path(aid, "gemini_movements")
    movements = jobs.read_json(movements_path)["movements"] if movements_path.is_file() else []

    summary = summarize_metrics(metrics, analysis["wall_angle_deg"], feedback, movements)
    fingerprint = create_coaching_fingerprint(
        {"summary": summary, "prompt": gemini_service.COACHING_PROMPT_VERSION}, config.GEMINI_MODEL
    )
    cache_path = jobs.result_path(aid, "coaching")
    cached = load_cached_coaching(cache_path, fingerprint)
    if cached is not None:
        return {"coaching": cached, "cached": True}

    try:
        result = gemini_service.generate_coaching(summary, tester["id"], aid)
    except budget.BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except gemini_service.GeminiUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        log.exception("Coaching failed for %s", aid)
        raise HTTPException(status_code=502, detail="AI coaching failed. Please try again.")

    save_cached_coaching(cache_path, fingerprint, result)
    return {"coaching": result, "cached": False}


@app.get("/api/analyses/{analysis_id}/video")
def get_video(analysis_id: str, expires: int = Query(...), sig: str = Query(...)):
    """Normalized video. Uses a signed link because <video src> can't send headers."""
    analysis_id = _validate_id(analysis_id)
    if not auth.verify_video_link(analysis_id, expires, sig):
        raise HTTPException(status_code=403, detail="Video link expired. Reopen the analysis.")
    path = jobs.video_path(analysis_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video not found.")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=3600"})


# Admin (header X-Admin-Token: <ADMIN_TOKEN>)

class NewTester(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@app.post("/api/admin/testers", dependencies=[Depends(auth.require_admin)])
def admin_create_tester(body: NewTester):
    code = auth.generate_invite_code()
    tester_id = db.create_tester(body.name.strip(), auth.hash_code(code))
    return {
        "id": tester_id,
        "name": body.name.strip(),
        "invite_code": code,
        "note": "Save this code now. Only its hash is stored, so it can't be shown again.",
    }


@app.get("/api/admin/testers", dependencies=[Depends(auth.require_admin)])
def admin_list_testers():
    return db.list_testers()


@app.post("/api/admin/testers/{tester_id}/revoke", dependencies=[Depends(auth.require_admin)])
def admin_revoke_tester(tester_id: int):
    if not db.revoke_tester(tester_id):
        raise HTTPException(status_code=404, detail="Tester not found.")
    return {"revoked": tester_id}


@app.get("/api/admin/usage", dependencies=[Depends(auth.require_admin)])
def admin_usage():
    return {
        "daily_token_budget": config.DAILY_TOKEN_BUDGET,
        "tokens_used_today": db.tokens_used_today(),
        "tokens_remaining_today": budget.remaining_tokens(),
        "by_day": db.usage_by_day(),
    }
