"""MediaPipe pose processing: per-frame metrics + skeleton overlay data.

Based on the phase02 video_processor.py. Changes for the mobile app:
- Uses pose_world_landmarks (3D, meters, hip-centered) for joint angles,
  the body-size scale (pixels -> meters) and the experimental hip-to-wall
  estimate. The 2D angles are kept
  alongside for comparison (*_angle_2d).
- Takes the wall angle and reports hip motion along the wall surface.
- Returns compact landmark data so the app draws the skeleton on top of the
  original video, instead of rendering a second annotated video with FFmpeg.
- Data-quality fix: on frames where MediaPipe is skipped, every measurement
  is None. Before, foot speed carried over the previous frame's value.
- Uses "inference_performed" consistently so downstream code can ignore
  skipped frames.
"""

import math
import statistics
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp

from app import config
from app.angle_utils import calculateAngle, calculateAngle3D, classifyElbowPosition
from app.duration_utils import summarizeDeepBendIntervals, trackDeepBendDuration
from app.velocity_utils import calculateFootSpeed, calculateFootVelocity
from app.wall_geometry import hip_to_wall_distance, up_wall_velocity, wall_category

TARGET_INFERENCE_FPS = 30.0
VISIBILITY_THRESHOLD = 0.5

BaseOptions = mp.tasks.BaseOptions
PoseLandmarker = mp.tasks.vision.PoseLandmarker
PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

# Landmark indices
L_SHOULDER, R_SHOULDER = 11, 12
L_ELBOW, R_ELBOW = 13, 14
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24
L_KNEE, R_KNEE = 25, 26
L_ANKLE, R_ANKLE = 27, 28
L_HEEL, R_HEEL = 29, 30
L_FOOT, R_FOOT = 31, 32


def ensure_model() -> Path:
    """Download the MediaPipe model on first run if it isn't present."""
    path = config.MODEL_PATH
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".download")
        urllib.request.urlretrieve(config.POSE_MODEL_URL, temp)
        temp.replace(path)
    return path


def _visible(point, threshold=VISIBILITY_THRESHOLD) -> bool:
    return (
        point is not None
        and point.visibility is not None
        and point.visibility >= threshold
        and point.x is not None
        and point.y is not None
        and math.isfinite(point.x)
        and math.isfinite(point.y)
    )


def _px(point, width, height):
    return (point.x * width, point.y * height)


def _xyz(point):
    return (point.x, point.y, point.z)


def _angle_2d(a, b, c, width, height):
    return calculateAngle(_px(a, width, height), _px(b, width, height), _px(c, width, height))


def _round(value, digits=4):
    return None if value is None else round(value, digits)


def _smoothed_velocity(times, values, window=2, max_gap=0.1):
    """Velocity from positions smoothed with a small centered moving average.

    Raw frame-to-frame differences at 30 FPS are very noisy, so positions are
    averaged over up to 5 neighboring frames (within `max_gap` seconds of
    each other) before a central difference is taken.
    """
    count = len(values)
    smoothed = [None] * count
    for i in range(count):
        if values[i] is None:
            continue
        nearby = [
            values[j]
            for j in range(max(0, i - window), min(count, i + window + 1))
            if values[j] is not None and abs(times[j] - times[i]) <= max_gap * window
        ]
        smoothed[i] = sum(nearby) / len(nearby)

    velocity = [None] * count
    for i in range(1, count - 1):
        a, b = smoothed[i - 1], smoothed[i + 1]
        if a is None or b is None:
            continue
        dt = times[i + 1] - times[i - 1]
        if 0 < dt <= max_gap * 2:
            velocity[i] = (b - a) / dt
    return velocity


def _rolling_median(values, window=2):
    result = [None] * len(values)
    for i, value in enumerate(values):
        if value is None:
            continue
        nearby = [
            v for v in values[max(0, i - window): i + window + 1] if v is not None
        ]
        result[i] = statistics.median(nearby)
    return result


def _distribution(values):
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return {"samples": 0, "median": None, "p10": None, "p90": None}

    def pct(p):
        return clean[min(len(clean) - 1, int(round(p * (len(clean) - 1))))]

    return {
        "samples": len(clean),
        "median": round(statistics.median(clean), 3),
        "p10": round(pct(0.1), 3),
        "p90": round(pct(0.9), 3),
    }


def process_climbing_video(video_path: str | Path, wall_angle_deg: float = 0.0) -> tuple[dict, dict]:
    """Process a video. Returns (metrics, overlay).

    metrics: per-frame measurements and summaries (saved as metrics.json)
    overlay: compact 2D landmarks per analyzed frame for drawing the skeleton
    """
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Video does not exist: {video_path}")
    model_path = ensure_model()

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open video: {video_path}")

    frames = []
    overlay_frames = []
    previous_hip_y = previous_hip_timestamp = None
    previous_left_foot_dx = previous_left_foot_dy = previous_left_foot_timestamp = None
    previous_right_foot_dx = previous_right_foot_dy = previous_right_foot_timestamp = None
    left_deep_bent_start = left_missing_start = None
    right_deep_bent_start = right_missing_start = None
    left_deep_bent_intervals = []
    right_deep_bent_intervals = []
    last_processed_timestamp = None
    meters_per_pixel_samples = []

    # Raw series (inference frames only) for the second pass.
    series_index = []      # index into `frames`
    series_t = []
    series_hip_px_y = []
    series_left_foot = []  # foot position relative to hips (pixels), or None
    series_right_foot = []
    series_hip_wall = []

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width <= 0 or height <= 0:
            raise RuntimeError("Video dimensions are invalid")

        inference_interval = max(1, round(fps / TARGET_INFERENCE_FPS))

        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=VisionRunningMode.VIDEO,
            num_poses=1,
        )

        frame_number = 0
        with PoseLandmarker.create_from_options(options) as landmarker:
            while True:
                success, image = cap.read()
                if not success:
                    break

                current_timestamp = frame_number / fps
                timestamp_ms = int(frame_number * 1000 / fps)
                last_processed_timestamp = current_timestamp
                should_infer = frame_number % inference_interval == 0

                # Every measurement starts as None on every frame, including
                # skipped ones. This is the data-quality fix: previously
                # left/right_foot_speed kept the last analyzed frame's value.
                row = {
                    "frame": frame_number,
                    "timestamp_seconds": current_timestamp,
                    "inference_performed": should_infer,
                    "pose_detected": False,
                    "hip_x": None, "hip_y": None,
                    "hip_vertical_velocity": None,
                    "hip_up_velocity_mps": None,
                    "hip_up_wall_velocity_mps": None,
                    "hip_to_wall_m": None,
                    "left_arm_valid": False, "right_arm_valid": False,
                    "left_elbow_angle": None, "right_elbow_angle": None,
                    "left_elbow_angle_2d": None, "right_elbow_angle_2d": None,
                    "left_elbow_angle_3d": None, "right_elbow_angle_3d": None,
                    "left_elbow_position": None, "right_elbow_position": None,
                    "left_leg_tracking_valid": False, "right_leg_tracking_valid": False,
                    "left_knee_angle": None, "right_knee_angle": None,
                    "left_knee_angle_2d": None, "right_knee_angle_2d": None,
                    "left_hip_angle": None, "right_hip_angle": None,
                    "left_foot_dx": None, "left_foot_dy": None,
                    "right_foot_dx": None, "right_foot_dy": None,
                    "left_foot_vx": None, "left_foot_vy": None,
                    "right_foot_vx": None, "right_foot_vy": None,
                    "left_foot_speed": None, "right_foot_speed": None,
                    "left_foot_speed_mps": None, "right_foot_speed_mps": None,
                }

                landmarks = world = None
                if should_infer:
                    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    result = landmarker.detect_for_video(
                        mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp_ms
                    )
                    if result.pose_landmarks:
                        landmarks = result.pose_landmarks[0]
                    if result.pose_world_landmarks:
                        world = result.pose_world_landmarks[0]

                    overlay_frames.append({
                        "t": round(current_timestamp, 3),
                        "p": None if landmarks is None else [
                            value
                            for lm in landmarks
                            for value in (
                                round(lm.x, 4), round(lm.y, 4),
                                round(lm.visibility or 0.0, 2),
                            )
                        ],
                    })

                hip_px_y = None
                left_foot_world = right_foot_world = None
                hip_wall = None

                if landmarks is not None:
                    row["pose_detected"] = True
                    lm = landmarks
                    has_world = world is not None

                    # Arms: 3D angle is primary, 2D kept for comparison.
                    for side, s, e, w in (
                        ("left", L_SHOULDER, L_ELBOW, L_WRIST),
                        ("right", R_SHOULDER, R_ELBOW, R_WRIST),
                    ):
                        valid = all(_visible(lm[i]) for i in (s, e, w))
                        row[f"{side}_arm_valid"] = valid
                        if not valid:
                            continue
                        angle_2d = _angle_2d(lm[s], lm[e], lm[w], width, height)
                        angle_3d = (
                            calculateAngle3D(_xyz(world[s]), _xyz(world[e]), _xyz(world[w]))
                            if has_world else None
                        )
                        best = angle_3d if angle_3d is not None else angle_2d
                        row[f"{side}_elbow_angle_2d"] = _round(angle_2d, 2)
                        row[f"{side}_elbow_angle_3d"] = _round(angle_3d, 2)
                        row[f"{side}_elbow_angle"] = _round(best, 2)
                        row[f"{side}_elbow_position"] = classifyElbowPosition(best)

                    # Hips (screen position, legacy normalized velocity)
                    if _visible(lm[L_HIP]) and _visible(lm[R_HIP]):
                        hip_x = (lm[L_HIP].x + lm[R_HIP].x) / 2
                        hip_y = (lm[L_HIP].y + lm[R_HIP].y) / 2
                        row["hip_x"], row["hip_y"] = _round(hip_x, 5), _round(hip_y, 5)
                        hip_px_y = hip_y * height
                        if previous_hip_y is not None and previous_hip_timestamp is not None:
                            dt = current_timestamp - previous_hip_timestamp
                            if dt > 0:
                                row["hip_vertical_velocity"] = _round((hip_y - previous_hip_y) / dt)
                        previous_hip_y = hip_y
                        previous_hip_timestamp = current_timestamp

                        # Pixel -> meter scale from torso length (world 3D vs. image 2D).
                        if has_world and _visible(lm[L_SHOULDER]) and _visible(lm[R_SHOULDER]):
                            torso_px = statistics.mean([
                                math.dist(_px(lm[L_SHOULDER], width, height), _px(lm[L_HIP], width, height)),
                                math.dist(_px(lm[R_SHOULDER], width, height), _px(lm[R_HIP], width, height)),
                            ])
                            torso_m = statistics.mean([
                                math.dist(_xyz(world[L_SHOULDER]), _xyz(world[L_HIP])),
                                math.dist(_xyz(world[R_SHOULDER]), _xyz(world[R_HIP])),
                            ])
                            if torso_px > 5 and torso_m > 0.1:
                                meters_per_pixel_samples.append(torso_m / torso_px)

                    # Legs
                    for side, hip_i, knee_i, ankle_i, heel_i, foot_i, shoulder_i in (
                        ("left", L_HIP, L_KNEE, L_ANKLE, L_HEEL, L_FOOT, L_SHOULDER),
                        ("right", R_HIP, R_KNEE, R_ANKLE, R_HEEL, R_FOOT, R_SHOULDER),
                    ):
                        valid = all(_visible(lm[i]) for i in (hip_i, knee_i, ankle_i, heel_i, foot_i))
                        row[f"{side}_leg_tracking_valid"] = valid
                        if not valid:
                            continue
                        knee_2d = _angle_2d(lm[hip_i], lm[knee_i], lm[ankle_i], width, height)
                        knee_3d = (
                            calculateAngle3D(_xyz(world[hip_i]), _xyz(world[knee_i]), _xyz(world[ankle_i]))
                            if has_world else None
                        )
                        row[f"{side}_knee_angle_2d"] = _round(knee_2d, 2)
                        row[f"{side}_knee_angle"] = _round(knee_3d if knee_3d is not None else knee_2d, 2)
                        if row[f"{side}_arm_valid"]:
                            hip_angle = (
                                calculateAngle3D(_xyz(world[shoulder_i]), _xyz(world[hip_i]), _xyz(world[knee_i]))
                                if has_world
                                else _angle_2d(lm[shoulder_i], lm[hip_i], lm[knee_i], width, height)
                            )
                            row[f"{side}_hip_angle"] = _round(hip_angle, 2)
                        if row["hip_x"] is not None:
                            row[f"{side}_foot_dx"] = _round(lm[foot_i].x - row["hip_x"], 5)
                            row[f"{side}_foot_dy"] = _round(lm[foot_i].y - row["hip_y"], 5)
                        # Foot position relative to the hips in image pixels.
                        # (World-landmark feet jitter 2-4 cm per frame on every
                        # axis, which reads as ~1 m/s of fake motion, so foot
                        # speed uses the steadier 2D landmarks scaled to meters.)
                        if row["hip_x"] is not None:
                            point = (
                                (lm[foot_i].x - row["hip_x"]) * width,
                                (lm[foot_i].y - row["hip_y"]) * height,
                            )
                            if side == "left":
                                left_foot_world = point
                            else:
                                right_foot_world = point

                    # Hip-to-wall estimate from hands and feet (world coords).
                    if has_world:
                        contacts = [
                            _xyz(world[i]) for i in (L_WRIST, R_WRIST, L_FOOT, R_FOOT)
                            if _visible(lm[i])
                        ]
                        hip_wall = hip_to_wall_distance(contacts, wall_angle_deg)

                # Legacy normalized foot velocity (hip-relative), analyzed frames only.
                if should_infer:
                    (row["left_foot_vx"], row["left_foot_vy"],
                     previous_left_foot_dx, previous_left_foot_dy,
                     previous_left_foot_timestamp) = calculateFootVelocity(
                        row["left_foot_dx"], row["left_foot_dy"], current_timestamp,
                        previous_left_foot_dx, previous_left_foot_dy, previous_left_foot_timestamp,
                    )
                    (row["right_foot_vx"], row["right_foot_vy"],
                     previous_right_foot_dx, previous_right_foot_dy,
                     previous_right_foot_timestamp) = calculateFootVelocity(
                        row["right_foot_dx"], row["right_foot_dy"], current_timestamp,
                        previous_right_foot_dx, previous_right_foot_dy, previous_right_foot_timestamp,
                    )
                    row["left_foot_speed"] = calculateFootSpeed(row["left_foot_vx"], row["left_foot_vy"])
                    row["right_foot_speed"] = calculateFootSpeed(row["right_foot_vx"], row["right_foot_vy"])

                    left_deep_bent_start, left_missing_start = trackDeepBendDuration(
                        row["left_elbow_position"], current_timestamp,
                        left_deep_bent_start, left_missing_start, left_deep_bent_intervals,
                    )
                    right_deep_bent_start, right_missing_start = trackDeepBendDuration(
                        row["right_elbow_position"], current_timestamp,
                        right_deep_bent_start, right_missing_start, right_deep_bent_intervals,
                    )

                    series_index.append(len(frames))
                    series_t.append(current_timestamp)
                    series_hip_px_y.append(hip_px_y)
                    series_left_foot.append(left_foot_world)
                    series_right_foot.append(right_foot_world)
                    series_hip_wall.append(hip_wall)

                frames.append(row)
                frame_number += 1
    finally:
        cap.release()

    for start, missing, intervals in (
        (left_deep_bent_start, left_missing_start, left_deep_bent_intervals),
        (right_deep_bent_start, right_missing_start, right_deep_bent_intervals),
    ):
        if start is not None and last_processed_timestamp is not None:
            end = missing if missing is not None else last_processed_timestamp
            intervals.append({
                "start": start, "end": end, "duration": max(0.0, end - start),
                "status": "interrupted" if missing is not None else "video_ended",
            })

    # Second pass: metric (m/s) velocities and smoothed wall distance.
    meters_per_pixel = (
        statistics.median(meters_per_pixel_samples) if meters_per_pixel_samples else None
    )

    if meters_per_pixel is not None:
        # Image y grows downward, so negate to make "up" positive.
        hip_up_px = [None if y is None else -y for y in series_hip_px_y]
        hip_up_velocity = _smoothed_velocity(series_t, hip_up_px)
        for k, velocity_px in enumerate(hip_up_velocity):
            if velocity_px is None:
                continue
            mps = velocity_px * meters_per_pixel
            row = frames[series_index[k]]
            row["hip_up_velocity_mps"] = _round(mps)
            row["hip_up_wall_velocity_mps"] = _round(up_wall_velocity(mps, wall_angle_deg))

    if meters_per_pixel is not None:
        for side, series in (("left", series_left_foot), ("right", series_right_foot)):
            vx_px = _smoothed_velocity(series_t, [None if p is None else p[0] for p in series])
            vy_px = _smoothed_velocity(series_t, [None if p is None else p[1] for p in series])
            for k in range(len(series_t)):
                if vx_px[k] is None or vy_px[k] is None:
                    continue
                speed = math.hypot(vx_px[k], vy_px[k]) * meters_per_pixel
                frames[series_index[k]][f"{side}_foot_speed_mps"] = _round(speed)

    for k, value in enumerate(_rolling_median(series_hip_wall)):
        frames[series_index[k]]["hip_to_wall_m"] = _round(value, 3)

    inference_rows = [f for f in frames if f["inference_performed"]]
    detected = sum(1 for f in inference_rows if f["pose_detected"])
    duration = (frames[-1]["timestamp_seconds"] + 1 / fps) if frames else 0.0

    metrics = {
        "metrics_version": 2,
        "video": {
            "fps": fps, "width": width, "height": height,
            "frame_count": len(frames), "duration_seconds": round(duration, 3),
            "inference_interval": inference_interval,
        },
        "wall": {
            "angle_deg": wall_angle_deg,
            "category": wall_category(wall_angle_deg),
        },
        "scale": {
            "meters_per_pixel": _round(meters_per_pixel, 6),
            "samples": len(meters_per_pixel_samples),
            "method": "median torso length (world landmarks) / torso length (pixels)",
        },
        "tracking": {
            "inference_frames": len(inference_rows),
            "pose_detected_frames": detected,
            "pose_coverage": round(detected / len(inference_rows), 3) if inference_rows else None,
        },
        "wall_metrics": {
            "hip_to_wall_m": _distribution(f["hip_to_wall_m"] for f in inference_rows),
            "note": (
                "Experimental. Estimated from hand and foot positions using "
                "MediaPipe depth, which is its least accurate axis."
            ),
        },
        "frames": frames,
        "left_arm": {
            "deep_bend_intervals": left_deep_bent_intervals,
            "summary": summarizeDeepBendIntervals(left_deep_bent_intervals),
        },
        "right_arm": {
            "deep_bend_intervals": right_deep_bent_intervals,
            "summary": summarizeDeepBendIntervals(right_deep_bent_intervals),
        },
    }

    overlay = {
        "fps": fps,
        "width": width,
        "height": height,
        "landmark_count": 33,
        "values_per_landmark": 3,
        "frames": overlay_frames,
    }
    return metrics, overlay
