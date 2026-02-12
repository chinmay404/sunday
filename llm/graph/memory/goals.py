"""
Goal / Plan Manager — Sunday's directional intelligence.

Tracks objectives, plan steps, blockers, and next actions.
Not just a to-do list — this is about life direction.
Reflection reviews progress at night. Proactive engine nudges on deadlines.

Goal status: active, paused, completed, abandoned
Step status: pending, in_progress, done, blocked
Priority: 1 (critical/life-changing) → 10 (someday/maybe)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from llm.graph.db import get_connection

logger = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS goals (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    priority INT DEFAULT 5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_date TIMESTAMPTZ DEFAULT NULL,
    completed_at TIMESTAMPTZ DEFAULT NULL,
    source TEXT DEFAULT 'conversation'
);
CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);

CREATE TABLE IF NOT EXISTS goal_steps (
    id SERIAL PRIMARY KEY,
    goal_id INT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    step_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    blocker TEXT DEFAULT '',
    order_num INT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_goal_steps_goal ON goal_steps(goal_id);
"""


def init_goals():
    """Create the goals + steps tables if they don't exist."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_SQL)
        logger.info("Goal manager tables initialized")
    finally:
        conn.close()


# ── Goals CRUD ────────────────────────────────────────────────────────────

def create_goal(
    title: str,
    description: str = "",
    priority: int = 5,
    target_date: Optional[str] = None,
    source: str = "conversation",
) -> Dict[str, Any]:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                target = None
                if target_date:
                    try:
                        target = datetime.fromisoformat(target_date)
                    except ValueError:
                        pass
                cur.execute(
                    """INSERT INTO goals (title, description, priority, target_date, source)
                       VALUES (%s, %s, %s, %s, %s)
                       RETURNING id, created_at""",
                    (title, description, priority, target, source),
                )
                row = cur.fetchone()
                return {"id": row[0], "title": title, "priority": priority, "created_at": str(row[1])}
    finally:
        conn.close()


def update_goal(
    goal_id: int,
    status: Optional[str] = None,
    title: Optional[str] = None,
    priority: Optional[int] = None,
    description: Optional[str] = None,
) -> bool:
    conn = get_connection()
    try:
        updates = []
        values: list = []
        if status:
            updates.append("status = %s")
            values.append(status)
            if status in ("completed", "abandoned"):
                updates.append("completed_at = NOW()")
        if title:
            updates.append("title = %s")
            values.append(title)
        if priority is not None:
            updates.append("priority = %s")
            values.append(priority)
        if description:
            updates.append("description = %s")
            values.append(description)
        if not updates:
            return False
        updates.append("updated_at = NOW()")
        values.append(goal_id)
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE goals SET {', '.join(updates)} WHERE id = %s", values
                )
                return cur.rowcount > 0
    finally:
        conn.close()


# ── Steps CRUD ────────────────────────────────────────────────────────────

def add_step(goal_id: int, step_text: str, order_num: int = 0) -> Dict[str, Any]:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                if order_num == 0:
                    cur.execute(
                        "SELECT COALESCE(MAX(order_num), 0) + 1 FROM goal_steps WHERE goal_id = %s",
                        (goal_id,),
                    )
                    order_num = cur.fetchone()[0]
                cur.execute(
                    """INSERT INTO goal_steps (goal_id, step_text, order_num)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (goal_id, step_text, order_num),
                )
                return {"step_id": cur.fetchone()[0], "goal_id": goal_id, "step": step_text}
    finally:
        conn.close()


def update_step(
    step_id: int,
    status: Optional[str] = None,
    blocker: Optional[str] = None,
) -> bool:
    conn = get_connection()
    try:
        updates = []
        values: list = []
        if status:
            updates.append("status = %s")
            values.append(status)
        if blocker is not None:
            updates.append("blocker = %s")
            values.append(blocker)
        if not updates:
            return False
        updates.append("updated_at = NOW()")
        values.append(step_id)
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE goal_steps SET {', '.join(updates)} WHERE id = %s", values
                )
                return cur.rowcount > 0
    finally:
        conn.close()


# ── Queries ───────────────────────────────────────────────────────────────

def list_goals(status: str = "active", limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, title, description, status, priority, created_at, target_date
                       FROM goals WHERE status = %s
                       ORDER BY priority ASC, created_at DESC LIMIT %s""",
                    (status, limit),
                )
                goals = []
                for r in cur.fetchall():
                    goal: Dict[str, Any] = {
                        "id": r[0],
                        "title": r[1],
                        "description": r[2],
                        "status": r[3],
                        "priority": r[4],
                        "created_at": str(r[5]),
                        "target_date": str(r[6]) if r[6] else None,
                        "steps": [],
                    }
                    cur.execute(
                        """SELECT id, step_text, status, blocker, order_num
                           FROM goal_steps WHERE goal_id = %s
                           ORDER BY order_num ASC""",
                        (r[0],),
                    )
                    for s in cur.fetchall():
                        goal["steps"].append(
                            {
                                "step_id": s[0],
                                "step": s[1],
                                "status": s[2],
                                "blocker": s[3] if s[3] else None,
                                "order": s[4],
                            }
                        )
                    goals.append(goal)
                return goals
    finally:
        conn.close()


def get_next_actions() -> List[Dict[str, Any]]:
    """Get the first pending/in_progress step for each active goal."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT DISTINCT ON (g.id)
                           g.id as goal_id, g.title as goal_title, g.priority,
                           gs.id as step_id, gs.step_text, gs.blocker
                       FROM goals g
                       JOIN goal_steps gs ON g.id = gs.goal_id
                       WHERE g.status = 'active' AND gs.status IN ('pending', 'in_progress')
                       ORDER BY g.id, gs.order_num ASC"""
                )
                return [
                    {
                        "goal_id": r[0],
                        "goal": r[1],
                        "priority": r[2],
                        "step_id": r[3],
                        "next_action": r[4],
                        "blocker": r[5] if r[5] else None,
                    }
                    for r in cur.fetchall()
                ]
    finally:
        conn.close()


def get_goal_summary() -> str:
    """Brief summary for injection into reflection/proactive context."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM goals WHERE status = 'active'")
                total = cur.fetchone()[0]
                if total == 0:
                    return "No active goals."

                cur.execute(
                    """SELECT g.title, g.priority, g.target_date,
                              COUNT(gs.id) FILTER (WHERE gs.status = 'done') as done,
                              COUNT(gs.id) as total_steps
                       FROM goals g
                       LEFT JOIN goal_steps gs ON g.id = gs.goal_id
                       WHERE g.status = 'active'
                       GROUP BY g.id, g.title, g.priority, g.target_date
                       ORDER BY g.priority ASC"""
                )
                lines = [f"Active goals ({total}):"]
                for r in cur.fetchall():
                    progress = f" ({r[3]}/{r[4]} steps)" if r[4] > 0 else ""
                    deadline = f" due {r[2].strftime('%b %d')}" if r[2] else ""
                    lines.append(f"  - [P{r[1]}] {r[0]}{progress}{deadline}")

                # Next actions
                next_acts = get_next_actions()
                if next_acts:
                    lines.append("Next actions:")
                    for na in next_acts[:5]:
                        blocker = f" [BLOCKED: {na['blocker']}]" if na.get("blocker") else ""
                        lines.append(f"  → {na['goal']}: {na['next_action']}{blocker}")

                return "\n".join(lines)
    finally:
        conn.close()
