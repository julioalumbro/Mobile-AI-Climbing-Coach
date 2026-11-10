"""The stale-value bug: frames where MediaPipe was skipped must carry no
measurements, and the coaching summary must only sample analyzed frames."""

from app.metrics_summary import summarize_metrics
from app.pose_processor import process_climbing_video
from conftest import video

MEASUREMENT_FIELDS = (
    "left_foot_speed", "right_foot_speed", "left_foot_vx", "right_foot_vy",
    "left_foot_speed_mps", "right_foot_speed_mps", "left_elbow_angle",
    "right_elbow_angle", "hip_vertical_velocity", "hip_up_velocity_mps", "hip_x",
)


def test_skipped_frames_have_no_stale_values():
    # Raw 60 FPS iPhone clip (not normalized), so MediaPipe skips every other frame.
    metrics, overlay = process_climbing_video(video("climbingTestDyno.MOV"), wall_angle_deg=30)
    assert metrics["video"]["inference_interval"] == 2

    skipped = [f for f in metrics["frames"] if not f["inference_performed"]]
    analyzed = [f for f in metrics["frames"] if f["inference_performed"]]
    assert skipped and analyzed
    for frame in skipped:
        for field in MEASUREMENT_FIELDS:
            assert frame[field] is None, (frame["frame"], field)
    assert any(f["left_foot_speed"] is not None for f in analyzed)
    assert len(overlay["frames"]) == len(analyzed)

    summary = summarize_metrics(metrics, 30)
    analyzed_times = {round(f["timestamp_seconds"], 2) for f in analyzed if f["pose_detected"]}
    assert summary["movement_samples"]
    for sample in summary["movement_samples"]:
        assert sample["timestamp_seconds"] in analyzed_times
        assert sample["left_elbow_angle"] is not None or sample["right_elbow_angle"] is not None
