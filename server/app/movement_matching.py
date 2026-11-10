"""Match Gemini's timestamped movements with MediaPipe measurements.

From phase06 movement_matching_service.py. Changes:
- Only frames where MediaPipe actually ran are used (inference_performed).
- Adds metric-unit measurements: hip speed along the wall (m/s) and foot
  speed (m/s). Elbow angles are the 3D angles when available.
"""

from math import isfinite
from statistics import mean

# key in the matched result -> (frame field, validity flag or None, value range or None)
METRICS = {
    "left_elbow": ("left_elbow_angle", "left_arm_valid", (0, 180)),
    "right_elbow": ("right_elbow_angle", "right_arm_valid", (0, 180)),
    "hip_vertical_velocity": ("hip_vertical_velocity", None, None),
    "hip_up_wall_velocity_mps": ("hip_up_wall_velocity_mps", None, None),
    "left_foot_speed": ("left_foot_speed_mps", "left_leg_tracking_valid", None),
    "right_foot_speed": ("right_foot_speed_mps", "right_leg_tracking_valid", None),
    "left_knee": ("left_knee_angle", "left_leg_tracking_valid", (0, 180)),
    "right_knee": ("right_knee_angle", "right_leg_tracking_valid", (0, 180)),
}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def summarize(frames: list[dict], field: str, valid_key: str | None, value_range) -> dict:
    samples = []
    for frame in frames:
        if valid_key is not None and frame.get(valid_key) is not True:
            continue
        value = frame.get(field)
        if not _is_number(value):
            continue
        if value_range is not None and not (value_range[0] <= value <= value_range[1]):
            continue
        samples.append({"timestamp_seconds": round(frame["timestamp_seconds"], 3), "value": round(value, 4)})

    values = [s["value"] for s in samples]
    total = len(frames)
    return {
        "samples": len(samples),
        "inference_frames": total,
        "coverage": round(len(samples) / total, 3) if total else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": round(mean(values), 4) if values else None,
        "time_series": samples,
    }


def match_gemini_movements(gemini_result: dict, metrics: dict) -> list[dict]:
    analyzed = [
        frame for frame in metrics["frames"]
        if frame.get("inference_performed") is True
        and _is_number(frame.get("timestamp_seconds"))
    ]
    matched = []

    for movement in gemini_result.get("movements", []):
        start, end = movement["start_seconds"], movement["end_seconds"]
        window = [f for f in analyzed if start <= f["timestamp_seconds"] <= end]

        mediapipe = {"inference_frames": len(window)}
        for key, (field, valid_key, value_range) in METRICS.items():
            mediapipe[key] = summarize(window, field, valid_key, value_range)

        matched.append({"gemini_movement": movement, "mediapipe": mediapipe})

    return matched
