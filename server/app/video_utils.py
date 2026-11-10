"""Video probing and normalization with FFmpeg.

Every upload is converted into one analysis copy before anything else runs:
- the shorter side is scaled down to 720 px (phones record 1080p-4K),
- it is re-timed to a constant 30 FPS (phones often record variable frame
  rate, which makes timestamps and the skeleton overlay drift),
- the rotation flag is applied to the pixels (portrait iPhone clips),
- audio is removed (fewer Gemini tokens, smaller file),
- it is H.264 + faststart so every phone browser can stream it.

MediaPipe, Gemini and the in-app player all use this same file, so their
timestamps line up exactly.
"""

import json
import shutil
import subprocess
from pathlib import Path

from app import config


class VideoError(ValueError):
    pass


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if path is None:
        raise RuntimeError(f"{binary} is not installed on the server.")
    return path


def probe_duration(video_path: Path) -> float:
    """Return the duration in seconds, or raise VideoError if unreadable."""
    command = [
        _require("ffprobe"), "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,duration",
        "-of", "json", str(video_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise VideoError("This file could not be read as a video.")

    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise VideoError("This file has no video track.")

    candidates = [data.get("format", {}).get("duration")]
    candidates += [s.get("duration") for s in streams if s.get("codec_type") == "video"]
    durations = []
    for value in candidates:
        try:
            durations.append(float(value))
        except (TypeError, ValueError):
            continue

    if not durations or max(durations) <= 0:
        raise VideoError("Could not determine the video length.")
    return max(durations)


def check_duration(duration: float) -> None:
    limit = config.MAX_VIDEO_SECONDS
    if duration > limit + config.DURATION_TOLERANCE_SECONDS:
        raise VideoError(
            f"Video is {duration:.1f} seconds long. "
            f"Please upload a video up to {limit:g} seconds long."
        )


def normalize_video(source: Path, destination: Path) -> None:
    partial = destination.with_name(destination.name + ".partial")
    short = config.NORMALIZED_SHORT_SIDE
    # Scale so the shorter side is at most `short` px, keeping even dimensions.
    scale = (
        f"scale='if(gt(iw,ih),-2,min({short},iw))':'if(gt(iw,ih),min({short},ih),-2)'"
    )
    command = [
        _require("ffmpeg"), "-y", "-v", "error",
        "-i", str(source),
        "-t", str(config.MAX_VIDEO_SECONDS + config.DURATION_TOLERANCE_SECONDS),
        "-vf", f"{scale},fps={config.NORMALIZED_FPS}",
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(partial),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode != 0 or not partial.is_file():
        partial.unlink(missing_ok=True)
        raise VideoError(
            "The video could not be converted. Try exporting it as MP4 and uploading again."
        )
    # Only a finished file ever appears under the final name, so the app
    # never starts streaming a half-written video.
    partial.replace(destination)
