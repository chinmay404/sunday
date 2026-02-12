"""
World Model — Sunday's persistent inner understanding of Chinmay's life.

This is NOT memory. This is Sunday's *interpretation* of reality.
It's freeform — the LLM decides what's worth tracking. No fixed keys.
Think of it as Sunday's private journal that it reads before every conversation.

Stored in Postgres. Updated after every conversation + by reflection cycles.
Read into agent context so Sunday always has its understanding available.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from llm.graph.db import get_connection

logger = logging.getLogger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS world_model (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source TEXT DEFAULT 'system',
    confidence FLOAT DEFAULT 1.0,
    ttl_hours FLOAT DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS sunday_inner_thoughts (
    id SERIAL PRIMARY KEY,
    thought TEXT NOT NULL,
    mood TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source TEXT DEFAULT 'reflection',
    expires_at TIMESTAMPTZ DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_inner_thoughts_created
    ON sunday_inner_thoughts(created_at DESC);
"""


def init_world_model():
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_SQL)
    finally:
        conn.close()


# ── World State CRUD ──────────────────────────────────────────────────────

def get_state(key: str) -> Optional[Dict]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value, updated_at, source, confidence FROM world_model WHERE key = %s",
                (key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "value": row[0],
                "updated_at": row[1].isoformat() if row[1] else None,
                "source": row[2],
                "confidence": row[3],
            }
    finally:
        conn.close()


def set_state(key: str, value: Any, source: str = "system", confidence: float = 1.0,
              ttl_hours: Optional[float] = None):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO world_model (key, value, updated_at, source, confidence, ttl_hours)
                    VALUES (%s, %s, NOW(), %s, %s, %s)
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = NOW(),
                        source = EXCLUDED.source,
                        confidence = EXCLUDED.confidence,
                        ttl_hours = COALESCE(EXCLUDED.ttl_hours, world_model.ttl_hours)
                """, (key, json.dumps(value), source, confidence, ttl_hours))
    finally:
        conn.close()


def delete_state(key: str):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM world_model WHERE key = %s", (key,))
    finally:
        conn.close()


def get_all_states() -> Dict[str, Any]:
    """Get entire world model, excluding expired entries."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT key, value, updated_at, source, confidence
                FROM world_model
                WHERE ttl_hours IS NULL
                   OR updated_at + (ttl_hours || ' hours')::INTERVAL > NOW()
                ORDER BY updated_at DESC
            """)
            rows = cur.fetchall()
            return {
                row[0]: {
                    "value": row[1],
                    "updated_at": row[1],
                    "source": row[3],
                    "confidence": row[4],
                }
                for row in rows
            }
    finally:
        conn.close()


def bulk_set(updates: Dict[str, Any], source: str = "system"):
    """Set multiple keys at once."""
    if not updates:
        return
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                for key, value in updates.items():
                    cur.execute("""
                        INSERT INTO world_model (key, value, updated_at, source)
                        VALUES (%s, %s, NOW(), %s)
                        ON CONFLICT (key) DO UPDATE SET
                            value = EXCLUDED.value,
                            updated_at = NOW(),
                            source = EXCLUDED.source
                    """, (key, json.dumps(value), source))
    finally:
        conn.close()


# ── Inner Thoughts (Sunday's private stream of consciousness) ─────────────

def add_thought(thought: str, mood: Optional[str] = None, source: str = "reflection",
                ttl_hours: Optional[float] = 72.0):
    """Store a private thought. These expire — Sunday's inner voice is ephemeral."""
    expires_at = None
    if ttl_hours:
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO sunday_inner_thoughts (thought, mood, source, expires_at)
                    VALUES (%s, %s, %s, %s)
                """, (thought, mood, source, expires_at))
    finally:
        conn.close()


def get_recent_thoughts(limit: int = 5) -> List[Dict]:
    """Get Sunday's recent inner thoughts (not expired)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT thought, mood, created_at, source
                FROM sunday_inner_thoughts
                WHERE expires_at IS NULL OR expires_at > NOW()
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            return [
                {
                    "thought": row[0],
                    "mood": row[1],
                    "created_at": row[2].isoformat() if row[2] else None,
                    "source": row[3],
                }
                for row in cur.fetchall()
            ]
    finally:
        conn.close()


def cleanup_expired():
    """Remove expired world model entries and old thoughts."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                # Expire world model entries with TTL
                cur.execute("""
                    DELETE FROM world_model
                    WHERE ttl_hours IS NOT NULL
                      AND updated_at + (ttl_hours || ' hours')::INTERVAL < NOW()
                """)
                wm_deleted = cur.rowcount
                # Expire old thoughts
                cur.execute("""
                    DELETE FROM sunday_inner_thoughts
                    WHERE expires_at IS NOT NULL AND expires_at < NOW()
                """)
                th_deleted = cur.rowcount
                if wm_deleted or th_deleted:
                    logger.info("🧹 World model cleanup: %d states, %d thoughts expired",
                                wm_deleted, th_deleted)
    finally:
        conn.close()


# ── Rendering for agent context ───────────────────────────────────────────

def render_for_prompt() -> str:
    """Render world model + inner thoughts as natural language for the system prompt.
    This is what makes Sunday 'aware' of its own understanding."""
    states = get_all_states()
    thoughts = get_recent_thoughts(limit=4)

    if not states and not thoughts:
        return ""

    parts = []

    if states:
        parts.append("# YOUR INNER UNDERSTANDING (private — don't quote these directly)")
        for key, entry in states.items():
            val = entry.get("value", "")
            if isinstance(val, (dict, list)):
                val = json.dumps(val, default=str)
            label = key.replace("_", " ")
            parts.append(f"- {label}: {val}")

    if thoughts:
        parts.append("\n# YOUR RECENT PRIVATE THOUGHTS")
        for t in thoughts:
            mood_tag = f" [{t['mood']}]" if t.get("mood") else ""
            parts.append(f"- {t['thought']}{mood_tag}")

    return "\n".join(parts)
