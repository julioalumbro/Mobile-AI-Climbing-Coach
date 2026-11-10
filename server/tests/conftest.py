"""Test setup: isolated data folder, fake Gemini client (no paid calls).

Real-video tests need sample clips. Set TEST_VIDEO_DIR to a folder with
BadBeta.mp4 and climbingTestDyno.MOV (defaults to the project root).
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

_tmp = Path(tempfile.mkdtemp(prefix="climbing-coach-test-"))
os.environ["DATA_DIR"] = str(_tmp / "data")
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["GEMINI_API_KEY"] = "fake-key-for-tests"
os.environ["SECRET_KEY"] = "test-secret"

VIDEO_DIR = Path(os.getenv("TEST_VIDEO_DIR", SERVER_DIR.parent))


def video(name: str) -> Path:
    path = VIDEO_DIR / name
    if not path.is_file():
        pytest.skip(f"Sample video {name} not found in {VIDEO_DIR}")
    return path


class FakeGemini:
    """Mimics the parts of google.genai.Client the server uses."""

    def __init__(self):
        self.calls = []
        self.files = SimpleNamespace(
            upload=self._upload,
            get=lambda name: self._file,
            delete=lambda name: None,
        )
        self.models = SimpleNamespace(generate_content=self._generate)
        self._file = SimpleNamespace(
            name="files/fake", uri="https://fake/files/fake",
            mime_type="video/mp4", state=SimpleNamespace(name="ACTIVE"),
        )

    def _upload(self, file):
        self.calls.append(("upload", file))
        return self._file

    def _generate(self, model, contents, config):
        import json
        is_video = isinstance(contents, list)
        self.calls.append(("video" if is_video else "coaching", model))
        if is_video:
            body = {"movements": [
                {"start_seconds": 0.5, "end_seconds": 3.0, "movement_category": "hand_move",
                 "movement_type": "left hand reach", "body_parts": ["left hand", "left arm"],
                 "observation": "Reaches up with the left hand.", "confidence": "high"},
                {"start_seconds": 3.0, "end_seconds": 6.0, "movement_category": "foot_move",
                 "movement_type": "right foot high step", "body_parts": ["right foot"],
                 "observation": "Steps the right foot higher.", "confidence": "medium"},
                {"start_seconds": 6.0, "end_seconds": 99.0, "movement_category": "dynamic_move",
                 "movement_type": "deadpoint", "body_parts": ["hips", "both hands"],
                 "observation": "Moves dynamically to the top.", "confidence": "low"},
                {"start_seconds": 5.0, "end_seconds": 4.0, "movement_category": "rest",
                 "movement_type": "bad", "body_parts": [], "observation": "x", "confidence": "high"},
            ]}
            usage = SimpleNamespace(prompt_token_count=5200, candidates_token_count=600,
                                    thoughts_token_count=300, total_token_count=6100)
        else:
            # Two sentences in "issue" on purpose: the server must keep only the first.
            body = {"issue": "Your hips drift away from the wall at 3.0s while your right foot moves. "
                             "This is extra.",
                    "fix": "Turn your right hip into the wall as you step so your weight stays over the foot."}
            usage = SimpleNamespace(prompt_token_count=2500, candidates_token_count=400,
                                    thoughts_token_count=0, total_token_count=2900)
        return SimpleNamespace(text=json.dumps(body), usage_metadata=usage)


@pytest.fixture
def fake_gemini(monkeypatch):
    from app import gemini_service
    fake = FakeGemini()
    monkeypatch.setattr(gemini_service, "client_factory", lambda: fake)
    return fake


@pytest.fixture(scope="session")
def long_video(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("videos") / "long_25s.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=25:size=320x240:rate=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_tmp, ignore_errors=True)
