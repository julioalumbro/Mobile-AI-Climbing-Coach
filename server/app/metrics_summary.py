"""Compact summary of an analysis for the coaching prompt (from phase07).

Data-quality fix: samples come only from frames where MediaPipe actually
ran and found a pose. Before, frames were picked with frames[::step], which
on 60 FPS video landed on skipped frames (all None, or stale foot speeds).
"""

from app.wall_geometry import describe_wall

MAX_SAMPLES = 20

SAMPLE_FIELDS = (
    "hip_up_wall_velocity_mps",
    "left_elbow_angle",
    "right_elbow_angle",
    "left_knee_angle",
    "right_knee_angle",
    "left_foot_speed_mps",
    "right_foot_speed_mps",
)


def _r(value, digits=2):
    return None if value is None else round(value, digits)


def summarize_metrics(
    metrics: dict,
    wall_angle_deg: float,
    rule_feedback: list[dict] | None = None,
    gemini_movements: list[dict] | None = None,
) -> dict:
    frames = metrics.get("frames", [])
    usable = [
        f for f in frames
        if f.get("inference_performed") is True and f.get("pose_detected") is True
    ]

    step = max(1, len(usable) // MAX_SAMPLES)
    samples = [
        {"timestamp_seconds": _r(f["timestamp_seconds"])} | {k: _r(f.get(k)) for k in SAMPLE_FIELDS}
        for f in usable[::step][:MAX_SAMPLES]
    ]

    def arm(key):
        summary = metrics.get(key, {}).get("summary", {})
        return {k: _r(v) for k, v in summary.items()}

    return {
        "wall": {"angle_deg": wall_angle_deg, "description": describe_wall(wall_angle_deg)},
        "video_duration_seconds": metrics.get("video", {}).get("duration_seconds"),
        "tracking": metrics.get("tracking", {}),
        "units": {
            "angles": "degrees (3D, from MediaPipe world landmarks)",
            "hip_up_wall_velocity_mps": "meters/second along the wall, positive = upward",
            "foot_speed_mps": "meters/second in the camera plane, relative to the hips (noisy)",
        },
        "deep_elbow_bends": {"left": arm("left_arm"), "right": arm("right_arm")},
        "flagged_sustained_bends": [
            {k: item[k] for k in ("body_part", "start_seconds", "end_seconds", "duration_seconds")}
            for item in (rule_feedback or [])
        ],
        "observed_movements": [
            {k: m.get(k) for k in ("start_seconds", "end_seconds", "movement_type", "body_parts", "observation", "confidence")}
            for m in (gemini_movements or [])
        ],
        "movement_samples": samples,
    }
