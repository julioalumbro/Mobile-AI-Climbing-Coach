"""Background analysis jobs.

Pipeline for one upload:

    normalize (FFmpeg) ─┬─> pose (MediaPipe + rule feedback) ─┐
                        └─> gemini (video movements) ─────────┴─> hybrid

Pose and Gemini both only need the normalized video, so they run at the
same time. The app polls the status and shows each result as soon as its
stage is done: the skeleton and metrics usually arrive before Gemini.

Jobs run in a thread pool inside the API process. That's enough for a
small beta and needs no extra services (no Redis/Celery to host).
"""

import json
import logging
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import budget, config, db, gemini_service, video_utils
from app.hybrid_feedback import generate_hybrid_feedback
from app.movement_matching import match_gemini_movements
from app.pose_processor import process_climbing_video
from app.rule_feedback import generate_feedback
from app.wall_geometry import describe_wall

log = logging.getLogger("climbing_coach.jobs")

_executor = ThreadPoolExecutor(max_workers=config.JOB_WORKERS, thread_name_prefix="analysis")


# Storage layout: DATA_DIR/analyses/<id>/...

def analysis_dir(analysis_id: str) -> Path:
    return config.ANALYSES_DIR / analysis_id


def raw_upload_path(analysis_id: str, extension: str) -> Path:
    return analysis_dir(analysis_id) / f"upload{extension}"


def video_path(analysis_id: str) -> Path:
    return analysis_dir(analysis_id) / "video.mp4"


def result_path(analysis_id: str, name: str) -> Path:
    return analysis_dir(analysis_id) / f"{name}.json"


def write_json(path: Path, data) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as file:
        json.dump(data, file, separators=(",", ":"))
    temp.replace(path)


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def submit(analysis_id: str, raw_path: Path, tester_id: int, wall_angle_deg: float) -> None:
    _executor.submit(_run_safely, analysis_id, raw_path, tester_id, wall_angle_deg)


def _run_safely(*args) -> None:
    try:
        run_analysis(*args)
    except Exception:  # last-resort guard so a job never dies silently
        log.exception("Analysis %s crashed", args[0])
        db.set_status(args[0], "failed", "Unexpected server error during analysis.")


def run_analysis(analysis_id: str, raw_path: Path, tester_id: int, wall_angle_deg: float) -> None:
    db.set_status(analysis_id, "processing")

    # 1. Normalize
    db.set_stage(analysis_id, "normalize", "running")
    normalized = video_path(analysis_id)
    try:
        video_utils.normalize_video(raw_path, normalized)
        duration = video_utils.probe_duration(normalized)
    except Exception as exc:
        message = str(exc) if isinstance(exc, video_utils.VideoError) else "Video conversion failed."
        log.exception("Normalize failed for %s", analysis_id)
        db.set_stage(analysis_id, "normalize", "failed", message)
        db.set_status(analysis_id, "failed", message)
        for stage in ("pose", "gemini", "hybrid"):
            db.set_stage(analysis_id, stage, "skipped")
        return
    raw_path.unlink(missing_ok=True)  # keep only the small normalized copy
    db.set_stage(analysis_id, "normalize", "done")

    # 2a. Gemini in a parallel thread
    gemini_outcome: dict = {}
    gemini_thread = threading.Thread(
        target=_gemini_stage,
        args=(analysis_id, normalized, duration, wall_angle_deg, tester_id, gemini_outcome),
        name=f"gemini-{analysis_id[:8]}",
        daemon=True,
    )
    gemini_thread.start()

    # 2b. Pose on this thread
    db.set_stage(analysis_id, "pose", "running")
    metrics = None
    try:
        metrics, overlay = process_climbing_video(normalized, wall_angle_deg)
        feedback = generate_feedback(metrics, wall_angle_deg)
        write_json(result_path(analysis_id, "metrics"), metrics)
        write_json(result_path(analysis_id, "overlay"), overlay)
        write_json(result_path(analysis_id, "feedback"), feedback)
        db.set_stage(analysis_id, "pose", "done")
    except Exception:
        log.exception("Pose stage failed for %s", analysis_id)
        db.set_stage(analysis_id, "pose", "failed", "Pose tracking failed on this video.")

    gemini_thread.join()

    # 3. Hybrid (needs both)
    if metrics is not None and "result" in gemini_outcome:
        db.set_stage(analysis_id, "hybrid", "running")
        try:
            matched = match_gemini_movements(gemini_outcome["result"], metrics)
            write_json(result_path(analysis_id, "hybrid_feedback"), generate_hybrid_feedback(matched))
            db.set_stage(analysis_id, "hybrid", "done")
        except Exception:
            log.exception("Hybrid stage failed for %s", analysis_id)
            db.set_stage(analysis_id, "hybrid", "failed", "Could not combine Gemini and pose results.")
    else:
        db.set_stage(analysis_id, "hybrid", "skipped", "Needs both pose and Gemini results.")

    if metrics is None:
        db.set_status(analysis_id, "failed", "Pose tracking failed on this video.")
    else:
        db.set_status(analysis_id, "completed")


def _gemini_stage(analysis_id, normalized, duration, wall_angle_deg, tester_id, outcome) -> None:
    db.set_stage(analysis_id, "gemini", "running")
    try:
        result = gemini_service.analyze_video(
            normalized, duration, describe_wall(wall_angle_deg), tester_id, analysis_id
        )
        write_json(result_path(analysis_id, "gemini_movements"), result)
        outcome["result"] = result
        db.set_stage(analysis_id, "gemini", "done")
    except budget.BudgetExceeded as exc:
        db.set_stage(analysis_id, "gemini", "skipped", str(exc))
    except gemini_service.GeminiUnavailable as exc:
        db.set_stage(analysis_id, "gemini", "skipped", str(exc))
    except Exception:
        log.exception("Gemini stage failed for %s", analysis_id)
        db.set_stage(analysis_id, "gemini", "failed", "Gemini video analysis failed.")


# Retention

def cleanup_expired() -> int:
    """Delete stored videos and results older than RETENTION_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.RETENTION_DAYS)
    removed = 0
    for analysis_id in db.list_analyses_older_than(cutoff.isoformat(timespec="seconds")):
        shutil.rmtree(analysis_dir(analysis_id), ignore_errors=True)
        db.set_status(analysis_id, "expired", "Deleted after the retention period.")
        removed += 1
    return removed


def start_cleanup_loop(stop: threading.Event) -> threading.Thread:
    def loop():
        while not stop.is_set():
            try:
                cleanup_expired()
            except Exception:
                log.exception("Cleanup failed")
            stop.wait(6 * 60 * 60)

    thread = threading.Thread(target=loop, name="cleanup", daemon=True)
    thread.start()
    return thread
