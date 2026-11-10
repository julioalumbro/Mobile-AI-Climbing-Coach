# Shipping the AI Climbing Coach beta

Three parts:

| Part | Folder | Host | What testers see |
|---|---|---|---|
| API (Python, MediaPipe, Gemini) | `server/` | Railway | nothing directly |
| App (PWA) | `mobile/` | Vercel | the URL they open and add to their home screen |
| Invite codes | created through the API | — | one code per tester |

Do the steps in order. Total time is about 30 minutes.

## 0. Run it on your computer first (optional, recommended)

You need Python 3.12+, Node 20+ and FFmpeg (`winget install ffmpeg` on Windows).

**API** (PowerShell, from `server/`):
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env      # then edit .env: GEMINI_API_KEY, ADMIN_TOKEN, SECRET_KEY
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```
The first start downloads the MediaPipe model (~9 MB) into `server/models/`.
If you don't set `GEMINI_API_KEY`, the app still works with pose tracking only.

Run the tests (they use your sample clips in the project folder and a fake
Gemini client, so they cost nothing):
```powershell
.\.venv\Scripts\python.exe -m pytest
```

**App** (second terminal, from `mobile/`):
```powershell
npm install
npm run dev
```
Open http://localhost:5173. To try it on your phone, connect the phone to the
same Wi-Fi and open `http://<your-computer's-IP>:5173` (the terminal prints
the "Network" address). Camera recording needs HTTPS, so test **Record** on
the deployed version and use **Upload** locally.

Create an invite code for yourself (see step 3, with `http://127.0.0.1:8000`).

## 1. Put the code on GitHub

Commit and push the project as usual. `.env`, videos, `*.task` files,
`server/data/` and `node_modules/` are all gitignored.

## 2. Deploy the API on Railway

1. railway.com → New Project → **Deploy from GitHub repo** → pick this repo.
2. Open the service → **Settings**:
   - **Root Directory**: `server`
   - Railway will find `server/railway.json` and build the `Dockerfile`.
3. **Volumes** → Add volume → mount path **`/data`**. This is where the
   database, videos and results live. Without it everything is lost on each deploy.
4. **Variables**:
   | Name | Value |
   |---|---|
   | `GEMINI_API_KEY` | your key |
   | `ADMIN_TOKEN` | a long random string (keep it private) |
   | `SECRET_KEY` | another long random string |
   | `ALLOWED_ORIGINS` | fill in after step 4 (your Vercel URL) |

   Generate random strings with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
5. **Settings → Networking → Generate Domain**. You get something like
   `https://climbing-coach-production.up.railway.app`.
6. Check `https://<that domain>/api/health` returns `{"status":"ok",...}`.

Keep **one replica**: background jobs and SQLite live in the one process.

## 3. Create invite codes

One per tester. From any terminal (PowerShell shown):
```powershell
$api = "https://<your-railway-domain>"
$admin = @{ "X-Admin-Token" = "<your ADMIN_TOKEN>" }

# create
Invoke-RestMethod -Method Post "$api/api/admin/testers" -Headers $admin `
  -ContentType "application/json" -Body '{"name":"Sam"}'

# list testers + today's usage
Invoke-RestMethod "$api/api/admin/testers" -Headers $admin

# token usage per day
Invoke-RestMethod "$api/api/admin/usage" -Headers $admin

# revoke tester 3
Invoke-RestMethod -Method Post "$api/api/admin/testers/3/revoke" -Headers $admin
```
The code is shown **once** (only a hash is stored). Send it to the tester privately.

## 4. Deploy the app on Vercel

1. vercel.com → Add New → Project → import the same repo.
2. **Root Directory**: `mobile`. Framework is detected as Vite.
3. **Environment Variables**: `VITE_API_BASE_URL` = your Railway URL
   (no trailing slash).
4. Deploy. You get a URL like `https://climbing-coach.vercel.app`.
5. Back in Railway, set `ALLOWED_ORIGINS` to that URL and redeploy the API.

## 5. Send testers this

> Open **https://<your-vercel-url>** on your phone.
> iPhone: Safari → Share → **Add to Home Screen**. Android: Chrome → **Install app**.
> Open it from the home screen and enter your invite code.
> Keep clips to 20 seconds or less, filmed from behind with the phone level.

## Limits and knobs (Railway variables)

| Variable | Default | Meaning |
|---|---|---|
| `DAILY_TOKEN_BUDGET` | 1000000 | Shared Gemini tokens per UTC day (resets 7 PM Eastern) |
| `PER_TESTER_DAILY_ANALYSES` | 15 | Uploads per tester per UTC day |
| `MAX_VIDEO_SECONDS` | 20 | Longest clip accepted (checked on the server) |
| `GEMINI_VIDEO_FPS` | 1 | Frames/second Gemini samples. Raise to 2–3 to catch fast moves; costs more tokens |
| `RETENTION_DAYS` | 30 | Videos and results are deleted after this |
| `GEMINI_MODEL` | gemini-3.8-flash | Model for both Gemini calls |

When the budget runs out, uploads still get pose tracking and the skeleton;
only the Gemini movements and AI coaching pause until the reset.

## Updating

Push to GitHub. Railway and Vercel redeploy automatically. The app updates
itself on testers' phones the next time they open it.
