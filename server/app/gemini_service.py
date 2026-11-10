"""All Gemini calls: video movement analysis and metric-based coaching.

From phase06 gemini_video_service.py and phase07 llm_service.py. Changes:
- Every call goes through the daily token budget and records the real
  token usage Gemini reports.
- Prompts include the wall angle.
- The video schema has a fixed movement_category so hybrid feedback no
  longer guesses metrics from free text.
- Out-of-range or malformed movements are dropped (and counted) instead
  of failing the whole analysis; end times are clamped to the video length.
- Coaching now also receives Gemini's video observations, so the two
  Gemini paths inform each other.
"""

import json
import re
import time
from pathlib import Path

from app import budget, config

MOVEMENT_CATEGORIES = ["hand_move", "foot_move", "dynamic_move", "body_position", "rest", "other"]

VIDEO_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "movements": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "start_seconds": {"type": "NUMBER"},
                    "end_seconds": {"type": "NUMBER"},
                    "movement_category": {"type": "STRING", "enum": MOVEMENT_CATEGORIES},
                    "movement_type": {"type": "STRING"},
                    "body_parts": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "observation": {"type": "STRING"},
                    "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
                },
                "required": [
                    "start_seconds", "end_seconds", "movement_category", "movement_type",
                    "body_parts", "observation", "confidence",
                ],
            },
        }
    },
    "required": ["movements"],
}

# Coaching is deliberately short: one problem, one fix.
COACHING_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "issue": {"type": "STRING"},
        "fix": {"type": "STRING"},
    },
    "required": ["issue", "fix"],
}

COACHING_PROMPT_VERSION = "mobile-coaching-v2-issue-fix"


class GeminiUnavailable(RuntimeError):
    pass


def _make_client():
    from google import genai

    if not config.GEMINI_API_KEY:
        raise GeminiUnavailable("GEMINI_API_KEY is not configured on the server.")
    return genai.Client(api_key=config.GEMINI_API_KEY)


# Tests replace this to avoid real (paid) API calls.
client_factory = _make_client


def sanitize_movements(result: dict, video_duration: float) -> dict:
    """Keep well-formed movements, clamp times to the video, sort them."""
    raw = result.get("movements") if isinstance(result, dict) else None
    if not isinstance(raw, list):
        raise ValueError("Gemini response has no movements list.")

    kept, dropped = [], 0
    for movement in raw:
        try:
            start = float(movement["start_seconds"])
            end = min(float(movement["end_seconds"]), video_duration)
            category = movement.get("movement_category")
            if category not in MOVEMENT_CATEGORIES:
                category = "other"
            body_parts = [str(p) for p in movement.get("body_parts", []) if str(p).strip()]
            label = str(movement["movement_type"]).strip()
            observation = str(movement["observation"]).strip()
            confidence = movement["confidence"]
            if not (0 <= start < end) or not label or not observation:
                raise ValueError
            if confidence not in ("high", "medium", "low"):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            dropped += 1
            continue
        kept.append({
            "start_seconds": round(start, 2),
            "end_seconds": round(end, 2),
            "movement_category": category,
            "movement_type": label,
            "body_parts": body_parts,
            "observation": observation,
            "confidence": confidence,
        })

    kept.sort(key=lambda m: m["start_seconds"])
    return {"movements": kept, "dropped_movements": dropped}


def _video_prompt(wall_description: str) -> str:
    return (
        "Analyze this bouldering video and identify observable climbing "
        "movements in chronological order. "
        f"The climber reports the wall is {wall_description}. Take the wall "
        "angle into account: on overhangs, bent arms and hips close to the wall "
        "are often deliberate. "
        "For each movement give approximate start and end timestamps in seconds, "
        "a movement_category (hand_move, foot_move, dynamic_move for dynos and "
        "deadpoints, body_position for hip/body repositioning, rest, or other), "
        "a short movement_type label, the relevant body parts (say left or right "
        "when you can tell), a concise observation, and a confidence level. "
        "Only describe movements that are visible. Do not assume a movement is "
        "inefficient because an arm is bent or the climber pauses. Do not invent "
        "holds, movements, or force measurements. Use low confidence when the "
        "movement is partly hidden or uncertain. If nothing can be identified "
        "reliably, return an empty movements list."
    )


def analyze_video(
    video_path: Path,
    video_duration: float,
    wall_description: str,
    tester_id: int | None,
    analysis_id: str | None,
) -> dict:
    from google.genai import types

    estimate = config.ESTIMATED_VIDEO_ANALYSIS_TOKENS
    with budget.reserve(estimate):
        client = client_factory()
        uploaded = client.files.upload(file=str(video_path))
        try:
            deadline = time.monotonic() + 180
            while uploaded.state.name == "PROCESSING":
                if time.monotonic() > deadline:
                    raise RuntimeError("Gemini took too long to process the video.")
                time.sleep(2)
                uploaded = client.files.get(name=uploaded.name)
            if uploaded.state.name != "ACTIVE":
                raise RuntimeError(f"Gemini video processing failed: {uploaded.state.name}")

            video_part = types.Part(
                file_data=types.FileData(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
                video_metadata=types.VideoMetadata(fps=config.GEMINI_VIDEO_FPS),
            )
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[video_part, types.Part.from_text(text=_video_prompt(wall_description))],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=VIDEO_SCHEMA,
                ),
            )
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

        tokens = budget.record_response_usage(
            response, "video_analysis", tester_id, analysis_id, estimate
        )

    if not response.text:
        raise RuntimeError("Gemini returned no text response.")
    try:
        parsed = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gemini returned invalid JSON.") from exc

    result = sanitize_movements(parsed, video_duration)
    result["tokens_used"] = tokens
    return result


def _coaching_prompt(summary: dict) -> str:
    return f"""
You are an AI climbing coach. The data below was extracted from a bouldering
video: MediaPipe pose measurements, plus movements a vision model observed in
the same video. The climber reports the wall is {summary['wall']['description']}.

{json.dumps(summary, indent=2)}

Reply with exactly two fields:
- issue: ONE sentence naming the single most important thing the climber is
  doing wrong in this climb. Include a timestamp if one applies.
- fix: ONE sentence telling the climber how to fix that issue, as a concrete
  instruction they can try on their next attempt.

Rules:
- Each field is a single sentence of at most 30 words. No lists, no extra sentences.
- Base the issue on the supplied data. Do not claim you watched the video.
- Do not invent movements, timestamps, or measurements.
- Take the wall angle into account. On overhangs, bent arms and long lock-offs
  are often necessary; on slabs and vertical walls, straight arms and weight
  over the feet matter more. Do not call a bent elbow a mistake by itself.
- Foot speeds are noisy; treat them as relative within this climb, not absolute.
- If the data is too limited to identify a problem, say so in the issue
  sentence, and use the fix sentence to say how to film a clearer clip.
"""


_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def one_sentence(text: str) -> str:
    """Keep only the first sentence, in case the model adds more."""
    cleaned = " ".join(str(text).split())
    return _SENTENCE_BREAK.split(cleaned, maxsplit=1)[0] if cleaned else ""


def generate_coaching(summary: dict, tester_id: int | None, analysis_id: str | None) -> dict:
    from google.genai import types

    estimate = config.ESTIMATED_COACHING_TOKENS
    with budget.reserve(estimate):
        client = client_factory()
        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=_coaching_prompt(summary),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=COACHING_SCHEMA,
            ),
        )
        budget.record_response_usage(response, "coaching", tester_id, analysis_id, estimate)

    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")
    parsed = json.loads(response.text)
    result = {"issue": one_sentence(parsed.get("issue", "")), "fix": one_sentence(parsed.get("fix", ""))}
    if not result["issue"] or not result["fix"]:
        raise RuntimeError("Gemini returned incomplete coaching.")
    return result
