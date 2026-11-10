"""SQLite storage for testers, analyses and Gemini token usage.

SQLite is enough for a small invite-only beta: one server process, a few
writes per analysis. Each call opens its own short-lived connection so the
API threads and background job threads never share one.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from app import config

_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS testers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    code_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    tester_id INTEGER NOT NULL REFERENCES testers(id),
    created_at TEXT NOT NULL,
    day TEXT NOT NULL,
    original_filename TEXT,
    wall_angle_deg REAL NOT NULL,
    wall_label TEXT,
    duration_seconds REAL,
    status TEXT NOT NULL,
    stages TEXT NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_analyses_tester_day ON analyses(tester_id, day);

CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    day TEXT NOT NULL,
    tester_id INTEGER,
    analysis_id TEXT,
    kind TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_usage_day ON token_usage(day);
"""

STAGE_NAMES = ("normalize", "pose", "gemini", "hybrid")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@contextmanager
def connect():
    connection = sqlite3.connect(config.DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _write_lock, connect() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)


# Testers

def create_tester(name: str, code_hash: str) -> int:
    with _write_lock, connect() as connection:
        cursor = connection.execute(
            "INSERT INTO testers (name, code_hash, created_at) VALUES (?, ?, ?)",
            (name, code_hash, utc_now()),
        )
        return int(cursor.lastrowid)


def find_tester_by_hash(code_hash: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM testers WHERE code_hash = ? AND revoked = 0",
            (code_hash,),
        ).fetchone()
        return dict(row) if row else None


def list_testers() -> list[dict]:
    day = utc_day()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT t.id, t.name, t.created_at, t.revoked,
                (SELECT COUNT(*) FROM analyses a
                    WHERE a.tester_id = t.id AND a.day = ?) AS analyses_today,
                (SELECT COALESCE(SUM(u.total_tokens), 0) FROM token_usage u
                    WHERE u.tester_id = t.id AND u.day = ?) AS tokens_today,
                (SELECT COALESCE(SUM(u.total_tokens), 0) FROM token_usage u
                    WHERE u.tester_id = t.id) AS tokens_all_time
            FROM testers t ORDER BY t.id
            """,
            (day, day),
        ).fetchall()
        return [dict(row) for row in rows]


def revoke_tester(tester_id: int) -> bool:
    with _write_lock, connect() as connection:
        cursor = connection.execute(
            "UPDATE testers SET revoked = 1 WHERE id = ?", (tester_id,)
        )
        return cursor.rowcount > 0


# Analyses

def _decode_analysis(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    analysis = dict(row)
    analysis["stages"] = json.loads(analysis["stages"])
    return analysis


def create_analysis(
    analysis_id: str,
    tester_id: int,
    original_filename: str,
    wall_angle_deg: float,
    wall_label: str | None,
    duration_seconds: float,
) -> dict:
    stages = {name: {"status": "pending", "error": None} for name in STAGE_NAMES}
    with _write_lock, connect() as connection:
        connection.execute(
            """
            INSERT INTO analyses (id, tester_id, created_at, day, original_filename,
                wall_angle_deg, wall_label, duration_seconds, status, stages)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
            """,
            (
                analysis_id, tester_id, utc_now(), utc_day(), original_filename,
                wall_angle_deg, wall_label, duration_seconds, json.dumps(stages),
            ),
        )
    return get_analysis(analysis_id)


def get_analysis(analysis_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
        return _decode_analysis(row)


def list_analyses(tester_id: int, limit: int = 50) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM analyses WHERE tester_id = ? ORDER BY created_at DESC LIMIT ?",
            (tester_id, limit),
        ).fetchall()
        return [_decode_analysis(row) for row in rows]


def count_analyses_today(tester_id: int) -> int:
    with connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM analyses WHERE tester_id = ? AND day = ?",
            (tester_id, utc_day()),
        ).fetchone()
        return int(row[0])


def set_stage(analysis_id: str, stage: str, status: str, error: str | None = None) -> None:
    with _write_lock, connect() as connection:
        row = connection.execute(
            "SELECT stages FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
        if row is None:
            return
        stages = json.loads(row["stages"])
        stages[stage] = {"status": status, "error": error}
        connection.execute(
            "UPDATE analyses SET stages = ? WHERE id = ?",
            (json.dumps(stages), analysis_id),
        )


def set_status(analysis_id: str, status: str, error: str | None = None) -> None:
    with _write_lock, connect() as connection:
        connection.execute(
            "UPDATE analyses SET status = ?, error = ? WHERE id = ?",
            (status, error, analysis_id),
        )


def fail_interrupted_analyses() -> int:
    """Mark analyses that were mid-run when the server restarted as failed."""
    with _write_lock, connect() as connection:
        rows = connection.execute(
            "SELECT id, stages FROM analyses WHERE status IN ('queued', 'processing')"
        ).fetchall()
        for row in rows:
            stages = json.loads(row["stages"])
            for stage in stages.values():
                if stage["status"] in ("pending", "running"):
                    stage["status"] = "failed"
                    stage["error"] = "Server restarted before this step finished."
            connection.execute(
                "UPDATE analyses SET status = 'failed', error = ?, stages = ? WHERE id = ?",
                ("The server restarted during analysis. Please upload again.",
                 json.dumps(stages), row["id"]),
            )
        return len(rows)


def list_analyses_older_than(cutoff_iso: str) -> list[str]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT id FROM analyses WHERE created_at < ? AND status != 'expired'",
            (cutoff_iso,),
        ).fetchall()
        return [row["id"] for row in rows]


# Token usage

def record_usage(
    kind: str,
    model: str,
    prompt_tokens: int,
    output_tokens: int,
    total_tokens: int,
    tester_id: int | None,
    analysis_id: str | None,
) -> None:
    with _write_lock, connect() as connection:
        connection.execute(
            """
            INSERT INTO token_usage (created_at, day, tester_id, analysis_id, kind,
                model, prompt_tokens, output_tokens, total_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (utc_now(), utc_day(), tester_id, analysis_id, kind, model,
             prompt_tokens, output_tokens, total_tokens),
        )


def tokens_used_today() -> int:
    with connect() as connection:
        row = connection.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) FROM token_usage WHERE day = ?",
            (utc_day(),),
        ).fetchone()
        return int(row[0])


def usage_by_day(days: int = 14) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT day, kind, COUNT(*) AS calls, SUM(total_tokens) AS total_tokens,
                ROUND(AVG(total_tokens)) AS avg_tokens_per_call
            FROM token_usage GROUP BY day, kind ORDER BY day DESC, kind LIMIT ?
            """,
            (days * 4,),
        ).fetchall()
        return [dict(row) for row in rows]
