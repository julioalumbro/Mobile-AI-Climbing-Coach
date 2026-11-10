import math

import pytest

from app.angle_utils import calculateAngle3D
from app.gemini_service import one_sentence, sanitize_movements
from app.rule_feedback import min_bend_duration
from app.wall_geometry import hip_to_wall_distance, up_wall_velocity, wall_category, wall_vectors


def test_angle_3d():
    assert calculateAngle3D((1, 0, 0), (0, 0, 0), (0, 0, 1)) == pytest.approx(90)
    assert calculateAngle3D((1, 0, 0), (0, 0, 0), (-1, 0, 0)) == pytest.approx(180)
    assert calculateAngle3D((0, 0, 0), (0, 0, 0), (1, 0, 0)) is None


def test_wall_vectors_vertical_and_roof():
    up, out = wall_vectors(0)
    assert up == pytest.approx((0, -1, 0)) and out == pytest.approx((0, 0, -1))
    up, out = wall_vectors(90)
    assert up == pytest.approx((0, 0, -1), abs=1e-9) and out == pytest.approx((0, 1, 0), abs=1e-9)
    up, out = wall_vectors(37)
    assert sum(a * b for a, b in zip(up, out)) == pytest.approx(0, abs=1e-12)


def test_hip_to_wall_vertical():
    # Vertical wall 0.4 m in front of the hips (farther from the camera = +z).
    contacts = [(0.3, -0.6, 0.4), (-0.3, -0.6, 0.4), (0.2, 0.8, 0.4), (-0.2, 0.8, 0.4)]
    assert hip_to_wall_distance(contacts, 0) == pytest.approx(0.4)
    assert hip_to_wall_distance(contacts[:2], 0) is None


def test_hip_to_wall_overhang():
    # 40 deg overhang: build contacts on a plane 0.3 m from the hips.
    up, out = wall_vectors(40)
    base = tuple(-0.3 * n for n in out)
    contacts = [tuple(b + s * u for b, u in zip(base, up)) for s in (-0.7, -0.2, 0.5, 0.9)]
    assert hip_to_wall_distance(contacts, 40) == pytest.approx(0.3)


def test_up_wall_velocity():
    assert up_wall_velocity(1.0, 0) == pytest.approx(1.0)
    assert up_wall_velocity(1.0, 45) == pytest.approx(math.sqrt(2))
    assert up_wall_velocity(1.0, 70) is None
    assert up_wall_velocity(None, 10) is None


def test_wall_categories_and_thresholds():
    assert wall_category(-10) == "slab"
    assert wall_category(0) == "vertical"
    assert wall_category(20) == "slight overhang"
    assert wall_category(40) == "steep overhang"
    assert wall_category(60) == "very steep / roof"
    assert min_bend_duration(0) < min_bend_duration(20) < min_bend_duration(45)


def test_sanitize_movements_drops_and_clamps():
    raw = {"movements": [
        {"start_seconds": 4, "end_seconds": 30, "movement_category": "dynamic_move",
         "movement_type": "dyno", "body_parts": ["hips"], "observation": "jumps", "confidence": "high"},
        {"start_seconds": 1, "end_seconds": 2, "movement_category": "weird",
         "movement_type": "reach", "body_parts": ["left hand"], "observation": "reaches", "confidence": "low"},
        {"start_seconds": 3, "end_seconds": 2, "movement_category": "rest",
         "movement_type": "x", "body_parts": [], "observation": "x", "confidence": "high"},
        {"start_seconds": 1, "movement_category": "rest"},
    ]}
    result = sanitize_movements(raw, video_duration=10)
    assert result["dropped_movements"] == 2
    assert [m["start_seconds"] for m in result["movements"]] == [1, 4]
    assert result["movements"][0]["movement_category"] == "other"
    assert result["movements"][1]["end_seconds"] == 10


def test_one_sentence_keeps_first_sentence_only():
    assert one_sentence("Hips sag at 2.5s on the crimp. Also feet.") == "Hips sag at 2.5s on the crimp."
    assert one_sentence("  Keep   arms straight!  ") == "Keep arms straight!"
    assert one_sentence("") == ""
