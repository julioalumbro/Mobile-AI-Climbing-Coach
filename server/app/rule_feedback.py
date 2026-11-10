"""Rule-based feedback from deep-elbow-bend intervals (from phase06 feedback_service).

Wall-angle change: on steep walls, bent arms are often necessary (pulling
in, locking off on an overhang), so the minimum bend duration that gets
flagged grows with the wall angle, and the wording says why.
These durations are initial engineering thresholds, not validated values.
"""

from math import isclose

from app.wall_geometry import wall_category

MIN_BEND_SECONDS_BY_WALL = {
    "slab": 0.3,
    "vertical": 0.3,
    "slight overhang": 0.6,
    "steep overhang": 1.0,
    "very steep / roof": 1.5,
}


def min_bend_duration(wall_angle_deg: float) -> float:
    return MIN_BEND_SECONDS_BY_WALL[wall_category(wall_angle_deg)]


def generate_feedback(metrics: dict, wall_angle_deg: float = 0.0) -> list[dict]:
    category = wall_category(wall_angle_deg)
    threshold = min_bend_duration(wall_angle_deg)
    steep = category in ("steep overhang", "very steep / roof")
    feedback = []

    for arm_key, arm_name in (("left_arm", "left"), ("right_arm", "right")):
        for interval in metrics.get(arm_key, {}).get("deep_bend_intervals", []):
            start = interval.get("start")
            end = interval.get("end")
            duration = interval.get("duration")

            if interval.get("status") != "completed":
                continue
            if not all(
                isinstance(v, (int, float)) and not isinstance(v, bool)
                for v in (start, end, duration)
            ):
                continue
            if start < 0 or end < start or duration < 0:
                continue
            if not isclose(end - start, duration, abs_tol=0.02):
                continue
            if duration < threshold:
                continue

            if steep:
                interpretation = (
                    f"On a {category} wall, a bent arm is often needed to keep the "
                    "hips close to the wall. This may be a lock-off or an active pull."
                )
                recommendation = (
                    "Check whether your feet were loading the wall during this bend. "
                    "On steep terrain, toe pressure and core tension can take "
                    "weight off the arm."
                )
            else:
                interpretation = (
                    "This may represent a lock-off, active pulling, or another "
                    "intentional climbing movement."
                )
                recommendation = (
                    "Review this movement and consider whether greater foot support "
                    "or a straighter arm was possible without compromising control."
                )

            feedback.append({
                "type": "sustained_elbow_bend",
                "body_part": f"{arm_name}_elbow",
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "duration_seconds": round(duration, 2),
                "observation": (
                    f"A deep {arm_name} elbow bend (under 90 degrees) was "
                    f"recorded for {duration:.2f} seconds."
                ),
                "interpretation": interpretation,
                "recommendation": recommendation,
                "evidence_status": "measurement_supported",
                "threshold_seconds": threshold,
                "limitations": [
                    "Elbow angle alone cannot establish inefficient technique.",
                    "Handhold position and foot loading were not verified.",
                ],
            })

    feedback.sort(key=lambda item: item["start_seconds"])
    return feedback
