"""Evidence-aware feedback for each Gemini movement (from phase06).

Change: metrics are chosen from Gemini's fixed `movement_category` value
instead of searching its free-text movement_type for words like "foot".
"""

COVERAGE_THRESHOLD = 0.5

LABELS = {
    "left_elbow": ("Left elbow angle", "deg"),
    "right_elbow": ("Right elbow angle", "deg"),
    "hip_up_wall_velocity_mps": ("Hip speed along the wall", "m/s"),
    "hip_vertical_velocity": ("Hip vertical velocity", "screen units/s"),
    "left_foot_speed": ("Left foot speed", "m/s"),
    "right_foot_speed": ("Right foot speed", "m/s"),
    "left_knee": ("Left knee angle", "deg"),
    "right_knee": ("Right knee angle", "deg"),
}


def _fmt(value) -> str:
    return "unavailable" if value is None else f"{value:.2f}"


def evaluate_metric(metric: dict, label: str, unit: str) -> dict:
    coverage = metric.get("coverage")
    if coverage is None or metric.get("samples", 0) == 0:
        return {"status": "insufficient", "message": f"No valid {label.lower()} measurements were available."}
    if coverage < COVERAGE_THRESHOLD:
        return {"status": "limited", "message": f"{label} had limited tracking coverage ({coverage:.0%})."}
    return {
        "status": "supported",
        "message": (
            f"{label}: mean {_fmt(metric['mean'])}, min {_fmt(metric['min'])}, "
            f"max {_fmt(metric['max'])} {unit} (coverage {coverage:.0%})."
        ),
    }


def _sides(body_parts: list[str]) -> list[str]:
    text = " ".join(body_parts).lower()
    has_left, has_right = "left" in text, "right" in text
    if has_left and not has_right:
        return ["left"]
    if has_right and not has_left:
        return ["right"]
    return ["left", "right"]


def _hip_metric(metrics_available: dict) -> str:
    # Prefer metric-unit speed along the wall; fall back to the legacy value
    # (very steep walls, or no body-size scale could be estimated).
    if metrics_available.get("hip_up_wall_velocity_mps", {}).get("samples"):
        return "hip_up_wall_velocity_mps"
    return "hip_vertical_velocity"


def select_relevant_metrics(movement: dict, mediapipe: dict) -> list[str]:
    category = movement.get("movement_category", "other")
    sides = _sides(movement.get("body_parts", []))
    hip = _hip_metric(mediapipe)

    if category == "dynamic_move":
        return [hip, "left_foot_speed", "right_foot_speed", "left_elbow", "right_elbow"]
    if category == "hand_move":
        return [f"{side}_elbow" for side in sides]
    if category == "foot_move":
        return [f"{side}_foot_speed" for side in sides]
    if category == "body_position":
        return [hip] + [f"{side}_knee" for side in sides]
    if category == "rest":
        return ["left_elbow", "right_elbow"]
    return [hip]


def generate_hybrid_feedback(matched_movements: list[dict]) -> list[dict]:
    results = []
    for match in matched_movements:
        movement = match["gemini_movement"]
        mediapipe = match["mediapipe"]

        evaluations = []
        for key in select_relevant_metrics(movement, mediapipe):
            label, unit = LABELS[key]
            metric = mediapipe.get(key)
            if metric is None:
                evaluations.append({"metric": key, "status": "insufficient", "message": f"{label} was not available."})
                continue
            evaluations.append({"metric": key, **evaluate_metric(metric, label, unit)})

        statuses = [e["status"] for e in evaluations]
        if statuses and all(s == "supported" for s in statuses):
            evidence = "measurement_supported"
        elif "supported" in statuses:
            evidence = "partially_supported"
        else:
            evidence = "insufficient_measurement_data"

        results.append({
            "movement_type": movement["movement_type"],
            "movement_category": movement.get("movement_category", "other"),
            "start_seconds": movement["start_seconds"],
            "end_seconds": movement["end_seconds"],
            "body_parts": movement.get("body_parts", []),
            "observation": movement["observation"],
            "gemini_confidence": movement["confidence"],
            "evidence_status": evidence,
            "metric_evaluations": evaluations,
            "feedback": (
                "Relevant movement measurements are available for review. "
                "These measurements describe body motion but do not, by "
                "themselves, establish climbing efficiency."
                if evidence == "measurement_supported"
                else
                "Some relevant measurements are missing or have limited tracking "
                "coverage. Technique conclusions should be deferred until the "
                "movement can be reviewed with better evidence."
            ),
        })
    return results
