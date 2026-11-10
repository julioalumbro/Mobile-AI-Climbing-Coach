import time

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app
from conftest import video

ADMIN = {"X-Admin-Token": "test-admin-token"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def new_tester(client, name="Tester"):
    response = client.post("/api/admin/testers", json={"name": name}, headers=ADMIN)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['invite_code']}"}


def upload(client, headers, path, wall=30.0):
    with path.open("rb") as file:
        return client.post(
            "/api/analyses", headers=headers,
            files={"file": (path.name, file, "video/mp4")},
            data={"wall_angle_deg": str(wall), "wall_label": "30°"},
        )


def wait_done(client, headers, analysis_id, timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/analyses/{analysis_id}", headers=headers).json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(1)
    raise AssertionError("analysis did not finish")


def test_auth_required(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer CLIMB-NOPE"}).status_code == 401
    assert client.post("/api/admin/testers", json={"name": "x"}).status_code == 401


def test_invite_code_is_case_and_space_insensitive(client):
    response = client.post("/api/admin/testers", json={"name": "Case"}, headers=ADMIN)
    code = response.json()["invite_code"]
    assert client.get("/api/me", headers={"Authorization": f"Bearer  {code.lower()} "}).status_code == 200


def test_full_flow(client, fake_gemini):
    headers = new_tester(client, "Flow")
    created = upload(client, headers, video("BadBeta.mp4"))
    assert created.status_code == 202, created.text
    analysis_id = created.json()["id"]

    done = wait_done(client, headers, analysis_id)
    assert done["status"] == "completed", done
    assert {k: v["status"] for k, v in done["stages"].items()} == {
        "normalize": "done", "pose": "done", "gemini": "done", "hybrid": "done",
    }

    pose = client.get(f"/api/analyses/{analysis_id}/pose", headers=headers).json()
    assert pose["overlay"]["fps"] == 30
    assert len(pose["overlay"]["frames"]) > 300
    first = next(f for f in pose["overlay"]["frames"] if f["p"])
    assert len(first["p"]) == 33 * 3

    hybrid = client.get(f"/api/analyses/{analysis_id}/hybrid", headers=headers).json()
    assert len(hybrid["movements"]) == 3  # the malformed one was dropped
    assert hybrid["movements"][-1]["end_seconds"] <= done["duration_seconds"] + 0.1
    categories = [h["movement_category"] for h in hybrid["hybrid_feedback"]]
    assert categories == ["hand_move", "foot_move", "dynamic_move"]
    metric_keys = [e["metric"] for e in hybrid["hybrid_feedback"][0]["metric_evaluations"]]
    assert metric_keys == ["left_elbow"]

    first_coaching = client.post(f"/api/analyses/{analysis_id}/coaching", headers=headers).json()
    second_coaching = client.post(f"/api/analyses/{analysis_id}/coaching", headers=headers).json()
    assert first_coaching["cached"] is False and second_coaching["cached"] is True
    assert set(first_coaching["coaching"]) == {"issue", "fix"}
    assert first_coaching["coaching"]["issue"] == "Your hips drift away from the wall at 3.0s while your right foot moves."
    assert first_coaching["coaching"]["fix"].endswith("over the foot.")
    assert [c[0] for c in fake_gemini.calls].count("coaching") == 1

    # Signed video link with a byte range, the way iOS Safari requests video.
    ranged = client.get(done["video_url"], headers={"Range": "bytes=0-1023"})
    assert ranged.status_code == 206 and len(ranged.content) == 1024
    assert client.get(done["video_url"].replace("sig=", "sig=0")).status_code == 403

    usage = client.get("/api/admin/usage", headers=ADMIN).json()
    assert usage["tokens_used_today"] >= 6100 + 2900

    # Another tester can't see this analysis.
    other = new_tester(client, "Other")
    assert client.get(f"/api/analyses/{analysis_id}", headers=other).status_code == 404
    assert len(client.get("/api/analyses", headers=headers).json()) == 1


def test_rejects_videos_over_20_seconds(client, long_video, fake_gemini):
    headers = new_tester(client, "Long")
    response = upload(client, headers, long_video, wall=0)
    assert response.status_code == 400
    assert "up to 20 seconds" in response.json()["detail"]
    assert fake_gemini.calls == []
    assert client.get("/api/analyses", headers=headers).json() == []


def test_rejects_bad_wall_angle_and_non_video(client, tmp_path):
    headers = new_tester(client, "Bad")
    assert upload(client, headers, video("BadBeta.mp4"), wall=95).status_code == 400
    text = tmp_path / "notes.mp4"
    text.write_text("not a video")
    response = upload(client, headers, text)
    assert response.status_code == 400 and "could not be read" in response.json()["detail"]


def test_per_tester_daily_limit(client, monkeypatch, fake_gemini):
    headers = new_tester(client, "Limited")
    monkeypatch.setattr(config, "PER_TESTER_DAILY_ANALYSES", 1)
    first = upload(client, headers, video("climbingTestDyno.MOV"))
    assert first.status_code == 202
    second = upload(client, headers, video("climbingTestDyno.MOV"))
    assert second.status_code == 429
    wait_done(client, headers, first.json()["id"])


def test_budget_exhausted_skips_gemini_but_keeps_pose(client, monkeypatch, fake_gemini):
    headers = new_tester(client, "Budget")
    monkeypatch.setattr(config, "DAILY_TOKEN_BUDGET", db.tokens_used_today() + 100)
    created = upload(client, headers, video("climbingTestDyno.MOV"), wall=45)
    done = wait_done(client, headers, created.json()["id"])
    assert done["status"] == "completed"
    assert done["stages"]["pose"]["status"] == "done"
    assert done["stages"]["gemini"]["status"] == "skipped"
    assert "budget" in done["stages"]["gemini"]["error"]
    assert ("video", config.GEMINI_MODEL) not in fake_gemini.calls

    coaching = client.post(f"/api/analyses/{done['id']}/coaching", headers=headers)
    assert coaching.status_code == 429
