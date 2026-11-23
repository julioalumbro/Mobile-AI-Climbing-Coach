# AI Climbing Coach

[![CI](https://github.com/julioalumbro/Mobile-AI-Climbing-Coach/actions/workflows/ci.yml/badge.svg)](https://github.com/julioalumbro/Mobile-AI-Climbing-Coach/actions/workflows/ci.yml)

**Live demo (private beta, invite code required):** https://mobile-ai-climbing-coach.vercel.app

A mobile web app (PWA) that analyzes bouldering videos. It combines **MediaPipe pose estimation** with **Google Gemini video analysis** to measure how a climber moves and to produce coaching that is checked against those measurements.

Record or upload a clip (20 seconds max). The app draws a pose skeleton over the original video, reports joint angles and hip speed along the wall, lists the moves Gemini identified with timestamps, and labels each piece of feedback with how well the measurements support it.

<!-- TODO: add a screenshot or short GIF of the analysis screen here, e.g. docs/demo.gif -->

---

## Architecture

```text
 Phone (PWA: React + TypeScript, Vercel)
        |  invite-code auth, upload, status polling
        v
 FastAPI API (Python, Docker on Railway, persistent volume at /data)
        |
        |  POST /api/analyses  ->  202 Accepted, job queued in a thread pool
        v
   normalize (FFmpeg) --+--> pose: MediaPipe world landmarks + rule feedback --+
                        |                                                       +--> hybrid: match Gemini moves
                        +--> gemini: video movement analysis (JSON schema) -----+    to pose measurements
        |
        v
 SQLite (WAL): testers, per-stage job status, token usage   |   files: normalized video + JSON results
```

- **Parallel stages.** Pose tracking and Gemini both need only the normalized video, so they run at the same time. Each stage reports its status (`running` / `done` / `failed` / `skipped`). The app polls and shows each result as soon as it is ready, so the skeleton and metrics usually appear before Gemini finishes.
- **Graceful degradation.** If Gemini is unavailable or the daily budget is used up, the analysis still finishes with pose tracking, metrics, and rule-based feedback.
- **Single process by design.** Jobs run in a thread pool inside the API process, with no Redis or Celery to host. That is enough for a small beta and keeps deployment to one Docker service.

## Engineering highlights

| Area | What it does | Where |
|---|---|---|
| Concurrency | Background job pipeline: MediaPipe and Gemini run in parallel threads, with per-stage status in SQLite and a last-resort guard so a job never dies silently | `server/app/jobs.py` |
| LLM cost control | Thread-safe token **reservation** before each Gemini call, so concurrent requests can't overspend a 1M-token daily budget. Afterwards it records actual reported usage, or the estimate when usage metadata is missing | `server/app/budget.py` |
| Rate limiting | Per-tester daily analysis limit, server-side 20 s video limit, upload size cap | `server/app/main.py`, `config.py` |
| Auth & security | Invite codes stored only as SHA-256 hashes. Constant-time admin-token check. **HMAC-signed, expiring video URLs** (a `<video>` tag can't send an `Authorization` header). CORS restricted to the app's origin | `server/app/auth.py` |
| Data lifecycle | Videos and results are deleted automatically after 30 days. Atomic JSON writes (temp file + replace) | `server/app/jobs.py` |
| Structured LLM output | Gemini responses are constrained to a JSON schema, then sanitized (timestamps clamped to the video length, invalid intervals dropped) | `server/app/gemini_service.py` |
| Caching | Coaching is cached under a SHA-256 fingerprint of its inputs and model, so identical requests never call the API twice | `server/app/coaching_cache.py` |
| 3D measurements | Joint angles from MediaPipe **world landmarks**. The tester's wall angle is used to report hip speed along the wall, set bent-arm thresholds, and inform both Gemini prompts | `server/app/pose_processor.py`, `wall_geometry.py` |
| Testing | pytest suite (API, data quality, geometry) with a **fake Gemini client**, so tests cost nothing and never call the paid API. Runs in CI on every push | `server/tests/` |
| LLM evaluation | Phase 05 harness: deterministic checks that recommendations cite supported evidence and acknowledge uncertainty, plus Gemini-graded scoring (5 dimensions, out of 25) used to compare prompt versions (21 -> 23/25 and 24 -> 25/25) | `legacy/phase05/` |

## Tech stack

| Layer | Technologies |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, vite-plugin-pwa |
| Backend | Python 3.13, FastAPI, Uvicorn |
| Computer vision | MediaPipe Pose Landmarker, OpenCV |
| Generative AI | Google Gemini API (`google-genai`) |
| Video | FFmpeg / ffprobe |
| Storage | SQLite (WAL mode) + files on a persistent volume |
| Deployment | Docker on Railway (API), Vercel (PWA), GitHub Actions (CI) |

## Repository layout

```text
Mobile-AI-Climbing-Coach/
|-- server/     FastAPI + MediaPipe + Gemini API (Dockerfile, deploys to Railway)
|   |-- app/        jobs, auth, budget, pose processing, Gemini service, SQLite
|   |-- tests/      pytest suite (fake Gemini client)
|-- mobile/     React + TypeScript PWA (deploys to Vercel)
|-- legacy/     phase01-phase07: how the pipeline was built, step by step
|-- DEPLOY.md   run locally, deploy, create invite codes
```

## Run it locally

Full instructions are in [DEPLOY.md](DEPLOY.md). In short (Python 3.12+, Node 20+, FFmpeg):

```bash
# API
cd server
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                               # set GEMINI_API_KEY, ADMIN_TOKEN, SECRET_KEY
uvicorn app.main:app --reload
pytest                                             # no API key or credits needed

# App (second terminal)
cd mobile
npm install
npm run dev
```

Without `GEMINI_API_KEY`, the app still works with pose tracking only.

## API overview

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Health check |
| `GET /api/me` | Current tester and daily limits |
| `POST /api/analyses` | Upload a clip and queue an analysis job (202) |
| `GET /api/analyses/{id}` | Job status, per stage |
| `GET /api/analyses/{id}/pose` / `metrics` / `hybrid` | Results as each stage finishes |
| `POST /api/analyses/{id}/coaching` | Gemini coaching from the metrics summary (cached) |
| `GET /api/analyses/{id}/video` | Signed, expiring video link |
| `POST/GET /api/admin/testers`, `/revoke`, `GET /api/admin/usage` | Admin: invite codes and token usage |

## How it was built

The project grew in phases, each kept in `legacy/`. The web version it started from is at
[AI-Climbing-Project](https://github.com/julioalumbro/AI-Climbing-Project).

| Phase | Focus |
|---|---|
| 01 | Video loading with OpenCV. MediaPipe Pose Landmarker. Hip position and vertical velocity. Tracking-validity checks |
| 02 | Joint angles from vector math (dot product + arccos, with zero-length and floating-point safeguards). Elbow bend duration tracking |
| 03 | Movement events, coordination analysis, rule-based technique feedback |
| 04 | Gemini analysis of selected frames. Reconciling visual observations with measurements (`supported` / `contradicted` / `insufficient_evidence` / `not_independently_verified`) |
| 05 | Coaching evaluation harness and robustness tests (missing or conflicting evidence, recommendation safety) |
| 06 | Full-stack web app: FastAPI backend, React frontend, hybrid Gemini + MediaPipe feedback |
| 07 | Metrics summaries, LLM service and coaching cache, carried into the mobile server |
| Mobile beta | Background jobs, parallel stages, invite-code auth, token budget, 3D world landmarks, PWA. Video processing time cut by 57% (255.74 s -> 110.09 s) with FFmpeg normalization and processing optimizations |

## Communicating uncertainty

A Gemini observation is not automatically confirmed by the measurements, so hybrid feedback labels **measurement coverage**:

- **Measurement supported:** relevant measurements are available.
- **Partially supported:** some relevant measurements are available.
- **Insufficient measurement data:** available measurements can't support an evaluation.

These labels describe how much measurement evidence exists, not whether Gemini's visual interpretation is correct.

## Limitations

- **Single camera.** World landmarks are 3D estimates from one viewpoint, so depth and rotation remain approximate.
- **Occlusion and unusual positions.** Holds, the wall, lighting, and clothing can hide or distort landmarks.
- **Threshold sensitivity.** Movement classifications depend on configured thresholds.
- **Generative AI uncertainty.** Gemini can produce incomplete or incorrect observations. Feedback states its evidence limits rather than hiding them.
- **Not professional coaching.** This is an experimental tool, not a substitute for instruction, medical advice, or safety guidance.

## Motivation

Bouldering is an important personal interest of mine. I wanted to see whether AI could do more than detect body positions: could computer vision measurements and generative AI work together to give interpretable, honest feedback about climbing technique? Building it took me end to end through computer vision, video processing, LLM integration and evaluation, backend and frontend development, security, and deployment.

## Author

**Julio Gabriel (Gabe) Alumbro**, Computer Science, University of Maryland ([LinkedIn](https://linkedin.com/in/jgalumbro))
