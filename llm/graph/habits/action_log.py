from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
from llm.graph.db import get_connection

DEFAULT_THREAD_ID = "default"


def _parse_iso_to_dt(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dt_to_iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def init_db() -> None:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS action_logs (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMPTZ NOT NULL,
                        action_type TEXT NOT NULL,
                        description TEXT NOT NULL,
                        commitment_made BOOLEAN NOT NULL,
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
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS habit_synthesis_runs (
                        thread_id TEXT PRIMARY KEY,
                        last_run_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS last_seen (
                        thread_id TEXT PRIMARY KEY,
                        last_seen_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
    finally:
        conn.close()


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
    ts = _parse_iso_to_dt(timestamp) if timestamp else _parse_iso_to_dt(utc_now_iso())
    tid = thread_id or DEFAULT_THREAD_ID
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO action_logs
                        (timestamp, action_type, description, commitment_made, sentiment, status, source_text, thread_id, user_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        ts,
                        action_type,
                        description,
                        bool(commitment_made),
                        sentiment,
                        status,
                        source_text,
                        tid,
                        user_name,
                    ),
                )
                return cur.fetchone()[0]
    finally:
        conn.close()


def get_recent_actions(
    *,
    thread_id: Optional[str] = None,
    since_hours: float = 72,
    limit: int = 200,
) -> List[Dict[str, Optional[str]]]:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    cutoff_dt = cutoff.replace(microsecond=0)
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT timestamp, action_type, description, commitment_made, sentiment, status, source_text, thread_id, user_name
                    FROM action_logs
                    WHERE thread_id = %s AND timestamp >= %s
                    ORDER BY timestamp ASC
                    LIMIT %s
                    """,
                    (tid, cutoff_dt, limit),
                )
                rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "timestamp": _dt_to_iso(r[0]) if r and r[0] else None,
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
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT timestamp
                    FROM action_logs
                    WHERE thread_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (tid,),
                )
                row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    ts = row[0]
    if ts and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def touch_last_seen(thread_id: Optional[str], timestamp: Optional[str] = None) -> None:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    ts = _parse_iso_to_dt(timestamp) if timestamp else _parse_iso_to_dt(utc_now_iso())
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO last_seen (thread_id, last_seen_at)
                    VALUES (%s, %s)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        last_seen_at = excluded.last_seen_at
                    """,
                    (tid, ts),
                )
    finally:
        conn.close()


def get_last_seen_time(thread_id: Optional[str] = None) -> Optional[datetime]:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT last_seen_at FROM last_seen WHERE thread_id = %s",
                    (tid,),
                )
                row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    ts = row[0]
    if ts and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def list_thread_ids() -> List[str]:
    init_db()
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT thread_id FROM action_logs
                    UNION
                    SELECT DISTINCT thread_id FROM last_seen
                    """
                )
                rows = cur.fetchall()
    finally:
        conn.close()
    thread_ids = [r[0] for r in rows if r and r[0]]
    thread_ids = sorted(set(thread_ids))
    return thread_ids or [DEFAULT_THREAD_ID]


def get_habit_profile(thread_id: Optional[str] = None) -> Optional[str]:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT profile FROM habit_profile WHERE thread_id = %s",
                    (tid,),
                )
                row = cur.fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def save_habit_profile(thread_id: Optional[str], profile: str) -> None:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    now_dt = _parse_iso_to_dt(utc_now_iso())
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO habit_profile (thread_id, profile, updated_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        profile = excluded.profile,
                        updated_at = excluded.updated_at
                    """,
                    (tid, profile, now_dt),
                )
    finally:
        conn.close()


def get_last_synthesis_run(thread_id: Optional[str] = None) -> Optional[datetime]:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT last_run_at FROM habit_synthesis_runs WHERE thread_id = %s",
                    (tid,),
                )
                row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    ts = row[0]
    if ts and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def set_last_synthesis_run(thread_id: Optional[str], timestamp: Optional[str] = None) -> None:
    init_db()
    tid = thread_id or DEFAULT_THREAD_ID
    ts = _parse_iso_to_dt(timestamp) if timestamp else _parse_iso_to_dt(utc_now_iso())
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO habit_synthesis_runs (thread_id, last_run_at)
                    VALUES (%s, %s)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        last_run_at = excluded.last_run_at
                    """,
                    (tid, ts),
                )
    finally:
        conn.close()
