
import cv2
import mediapipe as mp
from pathlib import Path
import json

# step 1: set up mediapipe classes
# reference the mediapipe tasks classes used to configure video-based pose detection
BaseOptions = mp.tasks.BaseOptions
PoseLandmarker = mp.tasks.vision.PoseLandmarker
PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

# step 2: set up file paths
# resolve paths relative to this script so it can run from different working directories
BASE_DIR = Path(__file__).resolve().parent

model_path = str(BASE_DIR / "pose_landmarker_full.task")
# the sample video is expected in the parent directory of this phase folder
video_path = str(BASE_DIR.parent / "climbingTestKilter.MOV")

# step 3: configure the pose landmarker
options = PoseLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=model_path),
    running_mode=VisionRunningMode.VIDEO,
    # process one climber at a time
    num_poses=1
)

# step 4: open the video
cap = cv2.VideoCapture(video_path)

if not cap.isOpened():
    raise RuntimeError(f"Could not open video: {video_path}")

# use the source video frame rate for accurate per-frame timestamps
fps = cap.get(cv2.CAP_PROP_FPS)

if fps <= 0:
    # use a fallback frame rate when the video does not report one
    fps = 30

frame_number = 0

# store metrics for each processed frame
metrics_log = []

# previous valid hip measurements
previous_hip_y = None
# retain the last valid hip position and its timestamp for velocity calculations
previous_timestamp = None

# step 5: create the pose landmarker
with PoseLandmarker.create_from_options(options) as landmarker:

    while cap.isOpened():
        success, frame = cap.read()

        if not success:
            break

        # convert opencv bgr image to rgb
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # convert image into mediapipe format
        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb_frame
        )

        # calculate timestamps
        # mediapipe expects timestamps in milliseconds; metrics use seconds
        timestamp_ms = int(frame_number * 1000 / fps)
        current_timestamp = frame_number / fps

        # detect pose landmarks
        result = landmarker.detect_for_video(
            mp_image,
            timestamp_ms
        )

        # debug: check frame 971 regardless of pose detection
        if frame_number == 971:
            print("Reached frame 971!")
            print(f"Pose detected: {bool(result.pose_landmarks)}")

        # initialize frame-specific variables
        # these reset every frame to prevent stale data
        # missing detections stay explicitly invalid rather than reusing earlier values
        tracking_valid = False

        hip_x = None
        hip_y = None
        hip_velocity_y = None

        left_hip_visibility = None
        right_hip_visibility = None

        # step 6: process pose landmarks
        if result.pose_landmarks:
            landmarks = result.pose_landmarks[0]

            # get left and right hip landmarks
            # mediapipe pose landmark indices 23 and 24 correspond to the hips
            left_hip = landmarks[23]
            right_hip = landmarks[24]

            # store visibility scores for json logging
            left_hip_visibility = left_hip.visibility
            right_hip_visibility = right_hip.visibility

            # check whether both hips are sufficiently visible
            left_visible = (
                left_hip_visibility is not None
                and left_hip_visibility >= 0.5
            )

            right_visible = (
                right_hip_visibility is not None
                and right_hip_visibility >= 0.5
            )

            # store hip coordinates in local variables
            left_x = left_hip.x
            left_y = left_hip.y
            right_x = right_hip.x
            right_y = right_hip.y

            # tracking is valid only if both hips are visible
            # and all four coordinates exist
            tracking_valid = (
                left_visible
                and right_visible
                # visibility alone is insufficient if the coordinates are missing
                and left_x is not None
                and left_y is not None
                and right_x is not None
                and right_y is not None
            )

            # debug: inspect hip landmarks at frame 971
            if frame_number == 971:
                print(f"Tracking valid: {tracking_valid}")
                print(f"Left hip: x={left_x}, y={left_y}")
                print(f"Right hip: x={right_x}, y={right_y}")
                print(f"Left visibility: {left_hip_visibility}")
                print(f"Right visibility: {right_hip_visibility}")

            # calculate metrics only for valid tracking
            # individual checks help pycharm narrow coordinate types
            if (
                left_visible
                and right_visible
                # visibility alone is insufficient if the coordinates are missing
                and left_x is not None
                and left_y is not None
                and right_x is not None
                and right_y is not None
            ):
                # calculate hip midpoint
                # average both hips to approximate the center of the pelvis
                hip_x = (left_x + right_x) / 2
                hip_y = (left_y + right_y) / 2

                # calculate vertical hip velocity
                if (
                    previous_hip_y is not None
                    and previous_timestamp is not None
                ):
                    # normalized image y increases downward, so velocity sign follows image coordinates
                    delta_y = hip_y - previous_hip_y
                    delta_t = current_timestamp - previous_timestamp

                    # divide by elapsed time since the last valid observation, including skipped frames
                    if delta_t > 0:
                        hip_velocity_y = delta_y / delta_t

                # update previous valid measurements
                previous_hip_y = hip_y
                previous_timestamp = current_timestamp

            # get frame dimensions for drawing
            height, width = frame.shape[:2]

            # draw landmark points
            # convert normalized coordinates into pixel positions for the overlay
            for landmark in landmarks:
                x = landmark.x
                y = landmark.y

                if x is None or y is None:
                    continue

                pixel_x = int(x * width)
                pixel_y = int(y * height)

                cv2.circle(
                    frame,
                    (pixel_x, pixel_y),
                    4,
                    (0, 0, 255),
                    -1
                )

            # draw skeleton connections
            # connect selected shoulders, arms, torso, and leg landmarks
            connections = [
                (11, 12),
                (11, 13), (13, 15),
                (12, 14), (14, 16),
                (11, 23), (12, 24),
                (23, 24),
                (23, 25), (25, 27),
                (24, 26), (26, 28)
            ]

            for start, end in connections:
                p1 = landmarks[start]
                p2 = landmarks[end]

                x1 = p1.x
                y1 = p1.y
                x2 = p2.x
                y2 = p2.y

                if (
                    x1 is None
                    or y1 is None
                    or x2 is None
                    or y2 is None
                ):
                    continue

                cv2.line(
                    frame,
                    (int(x1 * width), int(y1 * height)),
                    (int(x2 * width), int(y2 * height)),
                    (0, 255, 0),
                    2
                )

        # step 7: save metrics for every processed frame
        # this must remain outside if result.pose_landmarks
        # log one entry per frame, even when no pose is detected
        metrics_log.append({
            "frame": frame_number,
            "timestamp_seconds": current_timestamp,
            "hip_x": hip_x,
            "hip_y": hip_y,
            "hip_vertical_velocity": hip_velocity_y,
            "left_hip_visibility": left_hip_visibility,
            "right_hip_visibility": right_hip_visibility,
            "tracking_valid": tracking_valid
        })

        # step 8: display video
        height, width = frame.shape[:2]

        # resize video for display without changing aspect ratio
        # fit the preview inside 800 by 600 pixels without enlarging the source
        scale = min(800 / width, 600 / height, 1.0)

        display_frame = cv2.resize(
            frame,
            None,
            fx=scale,
            fy=scale
        )

        cv2.imshow(
            "AI Climbing Coach - Pose Detection",
            display_frame
        )

        # press q to exit
        if cv2.waitKey(1) & 0xFF == ord("q"):
            frame_number += 1
            break

        frame_number += 1

# step 9: release resources
cap.release()
cv2.destroyAllWindows()

# step 10: export metrics to json
# each run writes the collected frame metrics to this phase folder
output_path = BASE_DIR / "metrics.json"

# write mode replaces any existing metrics.json file
with open(output_path, "w") as f:
    json.dump(metrics_log, f, indent=4)

print(f"Saved {len(metrics_log)} frames of metrics to {output_path}")
print("Video processing complete!")
