import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict

DEFAULT_THREAD_ID = "default"
DB_PATH = Path(__file__).resolve().parent / "habits.db"


def _coerce_iso(ts: str) -> str:
    if ts.endswith("Z"):
        return ts
    if ts.endswith("+00:00"):
        return ts.replace("+00:00", "Z")
    return ts


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def init_db() -> None:
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL,
                commitment_made INTEGER NOT NULL,
                sentiment TEXT,
                status TEXT,
                source_text TEXT,
                thread_id TEXT NOT NULL,
                user_name TEXT
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_action_logs_time ON action_logs(timestamp)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_action_logs_thread ON action_logs(thread_id)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS habit_profile (
                thread_id TEXT PRIMARY KEY,
                profile TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS habit_synthesis_runs (
                thread_id TEXT PRIMARY KEY,
                last_run_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS last_seen (
                thread_id TEXT PRIMARY KEY,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def append_action_log(
    *,
    timestamp: Optional[str] = None,
    action_type: str,
    description: str,
    commitment_made: bool,
    sentiment: Optional[str] = None,
    status: Optional[str] = None,
    source_text: Optional[str] = None,
    thread_id: Optional[str] = None,
    user_name: Optional[str] = None,
) -> int:
    if not action_type or not description:
        raise ValueError("action_type and description are required")
    init_db()
    ts = _coerce_iso(timestamp or utc_now_iso())
    tid = thread_id or DEFAULT_THREAD_ID
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO action_logs
                (timestamp, action_type, description, commitment_made, sentiment, status, source_text, thread_id, user_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                action_type,
                description,
                1 if commitment_made else 0,
                sentiment,
                status,
                source_text,
                tid,
                user_name,
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_recent_actions(
    *,
    thread_id: Optional[str] = None,
    since_hours: float = 72,
    limit: int = 200,
) -> List[Dict[str, Optional[str]]]:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    cutoff_iso = cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT timestamp, action_type, description, commitment_made, sentiment, status, source_text, thread_id, user_name
            FROM action_logs
            WHERE thread_id = ? AND timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (tid, cutoff_iso, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "timestamp": r[0],
            "action_type": r[1],
            "description": r[2],
            "commitment_made": bool(r[3]),
            "sentiment": r[4],
            "status": r[5],
            "source_text": r[6],
            "thread_id": r[7],
            "user_name": r[8],
        }
        for r in rows
    ]


def get_last_action_time(thread_id: Optional[str] = None) -> Optional[datetime]:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT timestamp
            FROM action_logs
            WHERE thread_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (tid,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return _parse_iso(row[0])


def touch_last_seen(thread_id: Optional[str], timestamp: Optional[str] = None) -> None:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    ts = _coerce_iso(timestamp or utc_now_iso())
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO last_seen (thread_id, last_seen_at)
            VALUES (?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                last_seen_at = excluded.last_seen_at
            """,
            (tid, ts),
        )
        conn.commit()


def get_last_seen_time(thread_id: Optional[str] = None) -> Optional[datetime]:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT last_seen_at FROM last_seen WHERE thread_id = ?",
            (tid,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return _parse_iso(row[0])


def list_thread_ids() -> List[str]:
    init_db()
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT thread_id FROM action_logs")
        rows = cur.fetchall()
        cur.execute("SELECT DISTINCT thread_id FROM last_seen")
        rows_seen = cur.fetchall()
    thread_ids = [r[0] for r in rows if r and r[0]]
    thread_ids.extend([r[0] for r in rows_seen if r and r[0]])
    thread_ids = sorted(set(thread_ids))
    return thread_ids or [DEFAULT_THREAD_ID]


def get_habit_profile(thread_id: Optional[str] = None) -> Optional[str]:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT profile FROM habit_profile WHERE thread_id = ?",
            (tid,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def save_habit_profile(thread_id: Optional[str], profile: str) -> None:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    now_iso = utc_now_iso()
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO habit_profile (thread_id, profile, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                profile = excluded.profile,
                updated_at = excluded.updated_at
            """,
            (tid, profile, now_iso),
        )
        conn.commit()


def get_last_synthesis_run(thread_id: Optional[str] = None) -> Optional[datetime]:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT last_run_at FROM habit_synthesis_runs WHERE thread_id = ?",
            (tid,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return _parse_iso(row[0])


def set_last_synthesis_run(thread_id: Optional[str], timestamp: Optional[str] = None) -> None:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    ts = _coerce_iso(timestamp or utc_now_iso())
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO habit_synthesis_runs (thread_id, last_run_at)
            VALUES (?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                last_run_at = excluded.last_run_at
            """,
            (tid, ts),
        )
        conn.commit()
