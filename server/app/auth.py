"""Invite-code authentication and signed video links."""

import hashlib
import hmac
import secrets
import time

from fastapi import Header, HTTPException

from app import config, db

# Readable alphabet: no 0/O or 1/I/L confusion when a tester types it.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_invite_code() -> str:
    groups = ["".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "CLIMB-" + "-".join(groups)


def normalize_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


def hash_code(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()


def require_tester(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: the request must carry a valid invite code."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing invite code.")

    tester = db.find_tester_by_hash(hash_code(authorization[7:]))
    if tester is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked invite code.")
    return tester


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not config.ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN is not configured.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid admin token.")


# Signed video links
# A <video src> request can't send an Authorization header, so the video
# endpoint accepts a short-lived signature in the URL instead.

VIDEO_LINK_SECONDS = 6 * 60 * 60


def _signature(analysis_id: str, expires: int) -> str:
    message = f"{analysis_id}:{expires}".encode("utf-8")
    return hmac.new(config.SECRET_KEY.encode("utf-8"), message, hashlib.sha256).hexdigest()


def sign_video_link(analysis_id: str) -> str:
    expires = int(time.time()) + VIDEO_LINK_SECONDS
    return f"/api/analyses/{analysis_id}/video?expires={expires}&sig={_signature(analysis_id, expires)}"


def verify_video_link(analysis_id: str, expires: int, sig: str) -> bool:
    if expires < time.time():
        return False
    return hmac.compare_digest(sig, _signature(analysis_id, expires))
