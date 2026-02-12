"""
Thread Tracker — Sunday's executive function.

Tracks open loops: commitments, worries, questions, follow-ups, waiting-on items.
Every loose end Chinmay mentions or Sunday notices gets tracked here.
Reflection reviews them at night. Proactive engine nudges about stale ones.

Thread types: commitment, worry, question, follow_up, waiting_on, idea
Status: open, waiting, resolved, abandoned
Priority: 1 (urgent) → 10 (low/someday)
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from llm.graph.db import get_connection

logger = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS open_threads (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    thread_type TEXT NOT NULL DEFAULT 'follow_up',
    context TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    priority INT DEFAULT 5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    due_date TIMESTAMPTZ DEFAULT NULL,
    resolved_at TIMESTAMPTZ DEFAULT NULL,
    resolution TEXT DEFAULT '',
    source TEXT DEFAULT 'conversation'
);
CREATE INDEX IF NOT EXISTS idx_threads_status ON open_threads(status);
CREATE INDEX IF NOT EXISTS idx_threads_updated ON open_threads(updated_at DESC);
"""


def init_threads():
    """Create the threads table if it doesn't exist."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_SQL)
        logger.info("Thread tracker tables initialized")
    finally:
        conn.close()


# ── CRUD ──────────────────────────────────────────────────────────────────

def create_thread(
    title: str,
    thread_type: str = "follow_up",
    context: str = "",
    priority: int = 5,
    due_date: Optional[str] = None,
    source: str = "conversation",
) -> Dict[str, Any]:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                due = None
                if due_date:
                    try:
                        due = datetime.fromisoformat(due_date)
                    except ValueError:
                        pass
                cur.execute(
                    """INSERT INTO open_threads (title, thread_type, context, priority, due_date, source)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       RETURNING id, created_at""",
                    (title, thread_type, context, priority, due, source),
                )
                row = cur.fetchone()
                return {
                    "id": row[0],
                    "title": title,
                    "type": thread_type,
                    "priority": priority,
                    "created_at": str(row[1]),
                }
    finally:
        conn.close()


def update_thread(
    thread_id: int,
    status: Optional[str] = None,
    context: Optional[str] = None,
    priority: Optional[int] = None,
    resolution: Optional[str] = None,
) -> bool:
    conn = get_connection()
    try:
        updates = []
        values: list = []
        if status:
            updates.append("status = %s")
            values.append(status)
            if status in ("resolved", "abandoned"):
                updates.append("resolved_at = NOW()")
        if context:
            updates.append("context = context || E'\\n' || %s")
            values.append(context)
        if priority is not None:
            updates.append("priority = %s")
            values.append(priority)
        if resolution:
            updates.append("resolution = %s")
            values.append(resolution)
        if not updates:
            return False
        updates.append("updated_at = NOW()")
        values.append(thread_id)
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE open_threads SET {', '.join(updates)} WHERE id = %s",
                    values,
                )
                return cur.rowcount > 0
    finally:
        conn.close()


def resolve_thread(thread_id: int, resolution: str = "") -> bool:
    return update_thread(thread_id, status="resolved", resolution=resolution)


def list_threads(
    status: str = "open",
    thread_type: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                query = (
                    "SELECT id, title, thread_type, context, status, priority, "
                    "created_at, updated_at, due_date "
                    "FROM open_threads WHERE status = %s"
                )
                params: list = [status]
                if thread_type:
                    query += " AND thread_type = %s"
                    params.append(thread_type)
                query += " ORDER BY priority ASC, updated_at DESC LIMIT %s"
                params.append(limit)
                cur.execute(query, params)
                return [
                    {
                        "id": r[0],
                        "title": r[1],
                        "type": r[2],
                        "context": r[3][:200] if r[3] else "",
                        "status": r[4],
                        "priority": r[5],
                        "created_at": str(r[6]),
                        "updated_at": str(r[7]),
                        "due_date": str(r[8]) if r[8] else None,
                    }
                    for r in cur.fetchall()
                ]
    finally:
        conn.close()


def get_stale_threads(stale_days: int = 3) -> List[Dict[str, Any]]:
    """Threads that haven't been touched in N days."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
                cur.execute(
                    """SELECT id, title, thread_type, context, priority, updated_at, due_date
                       FROM open_threads
                       WHERE status IN ('open', 'waiting') AND updated_at < %s
                       ORDER BY priority ASC, updated_at ASC
                       LIMIT 10""",
                    (cutoff,),
                )
                return [
                    {
                        "id": r[0],
                        "title": r[1],
                        "type": r[2],
                        "context": r[3][:150] if r[3] else "",
                        "priority": r[4],
                        "last_updated": str(r[5]),
                        "days_stale": (datetime.now(timezone.utc) - r[5].replace(tzinfo=timezone.utc)).days
                            if r[5] else 0,
                        "due_date": str(r[6]) if r[6] else None,
                    }
                    for r in cur.fetchall()
                ]
    finally:
        conn.close()


def get_overdue_threads() -> List[Dict[str, Any]]:
    """Threads past their due date."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, title, thread_type, context, priority, due_date
                       FROM open_threads
                       WHERE status IN ('open', 'waiting')
                         AND due_date IS NOT NULL AND due_date < NOW()
                       ORDER BY due_date ASC LIMIT 10"""
                )
                return [
                    {
                        "id": r[0],
                        "title": r[1],
                        "type": r[2],
                        "context": r[3][:150] if r[3] else "",
                        "priority": r[4],
                        "due_date": str(r[5]),
                    }
                    for r in cur.fetchall()
                ]
    finally:
        conn.close()


def get_thread_summary() -> str:
    """Brief summary for injection into reflection/proactive context."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT thread_type, COUNT(*) FROM open_threads "
                    "WHERE status IN ('open','waiting') GROUP BY thread_type"
                )
                counts = {r[0]: r[1] for r in cur.fetchall()}
                if not counts:
                    return "No open threads."

                cur.execute(
                    """SELECT title, thread_type, priority,
                              EXTRACT(EPOCH FROM (NOW() - updated_at))/3600 as hours_stale,
                              due_date
                       FROM open_threads WHERE status IN ('open','waiting')
                       ORDER BY priority ASC, updated_at ASC LIMIT 10"""
                )
                threads = cur.fetchall()

                total = sum(counts.values())
                lines = [f"Open threads ({total} — {dict(counts)}):"]
                for t in threads:
                    stale_h = int(t[3]) if t[3] else 0
                    stale_tag = f" ⚠️ {stale_h}h stale" if stale_h > 72 else ""
                    due_tag = f" (due {t[4].strftime('%b %d')})" if t[4] else ""
                    lines.append(f"  - [P{t[2]}] {t[0]} ({t[1]}){due_tag}{stale_tag}")
                return "\n".join(lines)
    finally:
        conn.close()
