# AI Climbing Coach API
FROM python:3.13-slim

# ffmpeg: video normalization. libgl1/libglib2.0-0/libportaudio2: native libs
# that opencv-contrib-python and mediapipe load at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 libportaudio2 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# MediaPipe pose model (*.task files are gitignored, so download at build time).
RUN mkdir -p models && curl -fsSL -o models/pose_landmarker_full.task \
    https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task

COPY app ./app

ENV DATA_DIR=/data \
    PYTHONUNBUFFERED=1
# Persistent storage: attach a Railway volume at /data (Service -> Volumes).
# Railway doesn't support the Dockerfile VOLUME instruction.
RUN mkdir -p /data
EXPOSE 8000

# One worker: background jobs and SQLite live in this process.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
