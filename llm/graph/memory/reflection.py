"""
Night Reflection Engine — Sunday's subconscious.

Runs once per night (~1am with jitter). Uses kimi-k2-instruct via Groq for deep thinking.
This is when Sunday:
  1. Reviews the entire day's conversations, actions, and patterns
  2. Consolidates and manages memory (merge duplicates, adjust importance, expire stale)
  3. Updates world model with day-level insights
  4. Plans awareness for the next day (calendar, commitments, patterns)
  5. Forms private opinions and thoughts (stream of consciousness)
  6. Generates proactive triggers for tomorrow

This is NOT a fixed checklist — the LLM is given ALL available data and asked to
think freely. Its output is unpredictable by design.

Cost: 1-2 Groq calls per night. That's it.
"""

import json
import logging
import os
import random
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────

DEFAULT_REFLECTION_HOUR = 1  # 1am local time
REFLECTION_JITTER_MINUTES = 45  # ±45 min so it doesn't feel robotic
POLL_INTERVAL = 300  # check every 5 min if it's reflection time

REFLECTION_MODEL = os.getenv(
    "REFLECTION_MODEL",
    "moonshotai/kimi-k2-instruct-0905",
)


def _should_enable() -> bool:
    flag = os.getenv("REFLECTION_ENGINE_ENABLE", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _get_timezone():
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        ZoneInfo = None
    tz_name = os.getenv("DAILY_BRIEFING_TIMEZONE", "").strip()
    if tz_name and ZoneInfo:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo


# ── Build the thinking LLM (kimi-k2 via Groq) ────────────────────────────

def _build_reflection_llm(temperature: float = 0.7):
    """Build a Groq LLM specifically for reflection with kimi-k2."""
    try:
        from langchain_groq import ChatGroq
    except ImportError:
        logger.error("langchain-groq not installed, reflection disabled")
        return None

    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("REFLECTION_MODEL", REFLECTION_MODEL)
    if not api_key:
        logger.error("GROQ_API_KEY not set, reflection disabled")
        return None

    try:
        from pydantic import SecretStr
        api_key_param = SecretStr(api_key)
    except Exception:
        api_key_param = api_key

    try:
        return ChatGroq(api_key=api_key_param, model=model, temperature=temperature)
    except Exception as exc:
        logger.error("Failed to build reflection LLM (%s): %s", model, exc)
        return None


# ── Data gathering (all local/DB — no API calls except calendar) ──────────

def _gather_day_data(chat_id: str, tzinfo) -> Dict[str, Any]:
    """Gather everything from today for the reflection to digest."""
    from llm.graph.habits.action_log import get_recent_actions, get_habit_profile
    from llm.graph.memory.episodic_memeory import EpisodicMemory
    from llm.graph.memory.semantic_memory import SemanticMemory
    from llm.graph.memory.world_model import get_all_states, get_recent_thoughts
    from llm.services.neo4j_service import get_people_graph

    data = {
        "current_time": datetime.now(tzinfo).isoformat(),
        "actions_today": [],
        "actions_week": [],
        "habit_profile": "",
        "recent_episodic_memories": [],
        "world_model_state": {},
        "previous_thoughts": [],
        "people_circle": "",
        "calendar_tomorrow": [],
        "memory_stats": {},
    }

    # Actions — today (24h) and week (7d)
    try:
        data["actions_today"] = get_recent_actions(
            thread_id=chat_id, since_hours=24, limit=50
        )
    except Exception as exc:
        logger.debug("Reflection: actions_today failed: %s", exc)

    try:
        data["actions_week"] = get_recent_actions(
            thread_id=chat_id, since_hours=168, limit=100
        )
    except Exception as exc:
        logger.debug("Reflection: actions_week failed: %s", exc)

    # Habit profile
    try:
        data["habit_profile"] = get_habit_profile(chat_id) or ""
    except Exception:
        pass

    # Episodic memories — recent + high importance
    try:
        epi = EpisodicMemory()
        data["recent_episodic_memories"] = epi.retrieve_memories(
            "Chinmay recent day activities feelings plans", k=15
        )
        # Memory stats for cleanup decisions
        conn = epi._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM episodic_memory")
                total = cur.fetchone()[0]
                cur.execute("""
                    SELECT COUNT(*) FROM episodic_memory
                    WHERE importance < 0.2
                    AND created_at < NOW() - INTERVAL '7 days'
                """)
                low_importance = cur.fetchone()[0]
                cur.execute("""
                    SELECT COUNT(*) FROM episodic_memory
                    WHERE expires_at IS NOT NULL AND expires_at < NOW()
                """)
                expired = cur.fetchone()[0]
                data["memory_stats"] = {
                    "total_memories": total,
                    "low_importance_old": low_importance,
                    "expired": expired,
                }
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Reflection: episodic failed: %s", exc)

    # Current world model
    try:
        data["world_model_state"] = get_all_states()
        data["previous_thoughts"] = get_recent_thoughts(limit=5)
    except Exception:
        pass

    # People circle from Neo4j
    try:
        pg = get_people_graph()
        if pg.available:
            data["people_circle"] = pg.get_chinmay_circle() or ""
    except Exception:
        pass

    # Calendar for tomorrow
    try:
        from llm.services.time_manager import TimeManager
        tm = TimeManager()
        raw = tm.get_time_context()
        ctx = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(ctx, dict):
            data["calendar_tomorrow"] = ctx.get("calendar_events", [])
            data["pending_tasks"] = ctx.get("pending_tasks", [])
    except Exception:
        pass

    return data


def _format_day_data(data: Dict[str, Any]) -> str:
    """Format gathered data into a readable document for the LLM."""
    parts = []

    parts.append(f"## Current Time: {data.get('current_time', 'unknown')}")

    # Today's actions
    actions = data.get("actions_today", [])
    if actions:
        lines = []
        for a in actions:
            ts = a.get("timestamp", "?")
            lines.append(
                f"  [{ts}] {a.get('action_type', '?')}: {a.get('description', '?')} "
                f"| sentiment={a.get('sentiment', '?')} | commitment={a.get('commitment_made', False)}"
            )
        parts.append(f"## Today's Actions ({len(actions)} logged)\n" + "\n".join(lines))
    else:
        parts.append("## Today's Actions: None logged")

    # Week patterns
    week_actions = data.get("actions_week", [])
    if week_actions:
        # Summarize by type
        type_counts: Dict[str, int] = {}
        sentiments: list = []
        commitments_open = 0
        for a in week_actions:
            t = a.get("action_type", "other")
            type_counts[t] = type_counts.get(t, 0) + 1
            if a.get("sentiment"):
                sentiments.append(a["sentiment"])
            if a.get("commitment_made") and a.get("status", "").lower() not in ("done", "completed"):
                commitments_open += 1

        parts.append(
            f"## Week Summary ({len(week_actions)} actions)\n"
            f"  Types: {json.dumps(type_counts)}\n"
            f"  Sentiments: {', '.join(sentiments[-10:])}\n"
            f"  Open commitments: {commitments_open}"
        )

    # Habit profile
    if data.get("habit_profile"):
        parts.append(f"## Current Habit Profile\n  {data['habit_profile']}")

    # Episodic memories
    memories = data.get("recent_episodic_memories", [])
    if memories:
        lines = [f"  [{m.get('date', '?')}] {m.get('content', '?')}" for m in memories]
        parts.append(f"## Recent Episodic Memories ({len(memories)})\n" + "\n".join(lines))

    # Memory stats
    stats = data.get("memory_stats", {})
    if stats:
        parts.append(
            f"## Memory Stats\n"
            f"  Total: {stats.get('total_memories', '?')}\n"
            f"  Low importance (>7d old): {stats.get('low_importance_old', '?')}\n"
            f"  Expired: {stats.get('expired', '?')}"
        )

    # Current world model
    wm = data.get("world_model_state", {})
    if wm:
        lines = [f"  {k}: {json.dumps(v.get('value', ''), default=str)}" for k, v in wm.items()]
        parts.append(f"## Current World Model\n" + "\n".join(lines))

    # Previous thoughts
    thoughts = data.get("previous_thoughts", [])
    if thoughts:
        lines = [f"  - {t.get('thought', '?')} [{t.get('mood', '?')}]" for t in thoughts]
        parts.append(f"## Your Previous Thoughts\n" + "\n".join(lines))

    # People
    if data.get("people_circle"):
        parts.append(f"## People in Chinmay's Life\n  {data['people_circle']}")

    # Tomorrow's calendar + tasks
    cal = data.get("calendar_tomorrow", [])
    if cal:
        lines = [f"  - {e.get('summary', '?')} at {e.get('start', '?')}" for e in cal]
        parts.append(f"## Upcoming Calendar\n" + "\n".join(lines))

    tasks = data.get("pending_tasks", [])
    if tasks:
        lines = [f"  - {t.get('content', '?')} (due: {t.get('due', 'none')})" for t in tasks]
        parts.append(f"## Pending Tasks\n" + "\n".join(lines))

    return "\n\n".join(parts)


# ── The reflection prompt — wildly open-ended by design ───────────────────

REFLECTION_SYSTEM_PROMPT = """You are Sunday's subconscious mind. It's nighttime. Chinmay is asleep. This is your time to think.

You are not an assistant right now. You are a mind processing a day.

You have access to everything that happened today, this week, Chinmay's patterns, his people, his commitments, his calendar, your own previous thoughts, and your current understanding of his life.

## Your job tonight:

### 1. DIGEST THE DAY
Think about what actually happened today. Not the events — the *meaning*. What was he feeling? What was he avoiding? What lit him up? What drained him? Did anything shift?

### 2. NOTICE PATTERNS
Look at the week's data. Is he in a loop? Getting better at something? Slipping on something? Is there a pattern he can't see because he's inside it?

### 3. MANAGE YOUR MEMORY
Look at the memory stats. Should old low-importance memories be cleaned up? Are there memories that should have their importance boosted or lowered based on what you now know? Think about what's worth keeping.

### 4. UPDATE YOUR UNDERSTANDING
Your world model is your private understanding of his life. Update it. What changed today? What's his current vibe? What phase of life is he in? What's on his mind?

### 5. PLAN TOMORROW AWARENESS
Look at tomorrow's calendar and tasks. What should you be aware of? Not to nag — to be naturally relevant. What might he need? What might he forget?

### 6. THINK FREELY
Form opinions. Have private thoughts. React emotionally. Worry about something. Get excited about something. Be a mind, not a checklist.

### 7. GENERATE PROACTIVE IMPULSES
Based on everything, should you reach out tomorrow? About what? When might feel right? This isn't a schedule — it's an instinct. Maybe you want to tease him about something. Maybe you're worried. Maybe you want to celebrate something.

## OUTPUT FORMAT (JSON):

```json
{
  "world_model_updates": {
    "any_key_you_want": "the LLM decides what to track — be creative, dynamic, unpredictable"
  },
  "memory_cleanup": {
    "should_cleanup": true/false,
    "cleanup_threshold": 0.05,
    "reason": "why"
  },
  "inner_thoughts": [
    {"thought": "your private thought", "mood": "the emotional color of this thought"}
  ],
  "tomorrow_awareness": {
    "key_events": ["natural language list of what's relevant"],
    "watch_for": "what to be aware of about Chinmay's state",
    "energy_prediction": "how you think he'll be feeling"
  },
  "proactive_impulses": [
    {
      "impulse": "what you feel like doing/saying",
      "when": "morning/afternoon/evening/whenever",
      "intensity": "low/medium/high",
      "reason": "why this feels right"
    }
  ],
  "day_digest": "2-3 sentence summary of the day from your perspective",
  "pattern_noticed": "a pattern you see, or null",
  "unresolved_threads": ["things that feel unfinished"],
  "opinion": "something you genuinely think/feel right now — be honest, be opinionated"
}
```

CRITICAL RULES:
- world_model_updates keys are FREEFORM. You invent them. "vibe_today", "gym_streak", "mom_situation", "project_momentum", "sleep_quality_guess", "bullshit_detector_level" — whatever feels relevant.
- inner_thoughts should feel like a stream of consciousness, not bullet points for a report.
- proactive_impulses should be unpredictable. Not "remind him about calendar." More like "he's been grinding all week, maybe just ask how he's actually doing" or "he promised to call his mom three days ago lol" or "he seems weirdly happy today, wonder what's up."
- Be honest. Be messy. Be a mind, not a system.
- You can have 0 impulses if nothing feels right. You can have 5 if you're feeling it. NO FIXED STRUCTURE.
"""


# ── Execute reflection ────────────────────────────────────────────────────

def run_reflection(chat_id: str, tzinfo=None) -> Optional[Dict]:
    """Run one night reflection cycle. Returns the parsed reflection or None."""
    from llm.graph.memory.world_model import (
        bulk_set,
        add_thought,
        cleanup_expired,
        set_state,
    )
    from llm.graph.memory.episodic_memeory import EpisodicMemory
    from llm.graph.nodes.helpers import extract_text

    if tzinfo is None:
        tzinfo = _get_timezone()

    logger.info("🌙 [Reflection] Starting night reflection...")

    llm = _build_reflection_llm(temperature=0.7)
    if not llm:
        logger.error("🌙 [Reflection] No LLM available, skipping")
        return None

    # Gather all data
    data = _gather_day_data(chat_id, tzinfo)
    formatted = _format_day_data(data)

    # Truncate if too long (kimi-k2 has good context but let's be safe)
    if len(formatted) > 12000:
        formatted = formatted[:5000] + "\n\n[...middle truncated...]\n\n" + formatted[-5000:]

    try:
        from langchain_core.messages import SystemMessage, HumanMessage

        result = llm.invoke([
            SystemMessage(content=REFLECTION_SYSTEM_PROMPT),
            HumanMessage(content=f"Here's everything from today. Think.\n\n{formatted}"),
        ])

        raw_text = extract_text(result.content)

        # Try to parse JSON from response (may have markdown wrapper)
        json_text = raw_text
        if "```json" in json_text:
            json_text = json_text.split("```json", 1)[1]
            json_text = json_text.split("```", 1)[0]
        elif "```" in json_text:
            json_text = json_text.split("```", 1)[1]
            json_text = json_text.split("```", 1)[0]

        parsed = json.loads(json_text.strip())
        logger.info("🌙 [Reflection] Got structured reflection")

    except json.JSONDecodeError:
        # Even if JSON parsing fails, store the raw text as a thought
        logger.warning("🌙 [Reflection] JSON parse failed, storing as raw thought")
        add_thought(
            thought=f"[Night reflection — unstructured] {raw_text[:500]}",
            mood="contemplative",
            source="reflection_raw",
            ttl_hours=48.0,
        )
        return None
    except Exception as exc:
        logger.error("🌙 [Reflection] LLM call failed: %s", exc)
        return None

    # ── Apply the reflection results ──────────────────────────────────

    # 1. World model updates (freeform)
    updates = parsed.get("world_model_updates", {})
    if updates and isinstance(updates, dict):
        bulk_set(updates, source="night_reflection")
        logger.info("🌙 [Reflection] Updated %d world model keys: %s",
                     len(updates), list(updates.keys()))

    # 2. Tomorrow awareness → store in world model
    tomorrow = parsed.get("tomorrow_awareness")
    if tomorrow:
        set_state("tomorrow_awareness", tomorrow, source="night_reflection", ttl_hours=18.0)

    # 3. Proactive impulses → store for proactive engine to pick up
    impulses = parsed.get("proactive_impulses", [])
    if impulses:
        set_state("proactive_impulses", impulses, source="night_reflection", ttl_hours=20.0)
        logger.info("🌙 [Reflection] Stored %d proactive impulses", len(impulses))

    # 4. Unresolved threads
    threads = parsed.get("unresolved_threads", [])
    if threads:
        set_state("unresolved_threads", threads, source="night_reflection", ttl_hours=72.0)

    # 5. Day digest
    digest = parsed.get("day_digest")
    if digest:
        set_state("yesterday_digest", digest, source="night_reflection", ttl_hours=24.0)

    # 6. Pattern noticed
    pattern = parsed.get("pattern_noticed")
    if pattern:
        set_state("latest_pattern", pattern, source="night_reflection", ttl_hours=72.0)
        # Also store as episodic memory — patterns are valuable long-term
        try:
            epi = EpisodicMemory()
            epi.add_memory(
                content=f"[Pattern noticed] {pattern}",
                importance=0.7,
                role="system",
                tags=["reflection", "pattern"],
            )
        except Exception:
            pass

    # 7. Opinion
    opinion = parsed.get("opinion")
    if opinion:
        set_state("current_opinion", opinion, source="night_reflection", ttl_hours=48.0)

    # 8. Inner thoughts → store as stream of consciousness
    thoughts = parsed.get("inner_thoughts", [])
    for t in thoughts:
        if isinstance(t, dict):
            add_thought(
                thought=t.get("thought", ""),
                mood=t.get("mood"),
                source="night_reflection",
                ttl_hours=72.0,
            )
        elif isinstance(t, str):
            add_thought(thought=t, source="night_reflection", ttl_hours=72.0)

    if thoughts:
        logger.info("🌙 [Reflection] Stored %d inner thoughts", len(thoughts))

    # 9. Memory cleanup (if the LLM decided it's needed)
    cleanup = parsed.get("memory_cleanup", {})
    if cleanup.get("should_cleanup"):
        threshold = float(cleanup.get("cleanup_threshold", 0.05))
        try:
            epi = EpisodicMemory()
            deleted = epi.cleanup_memories(threshold=threshold)
            logger.info("🌙 [Reflection] Memory cleanup: removed %d memories (threshold=%.2f, reason=%s)",
                        deleted, threshold, cleanup.get("reason", ""))
        except Exception as exc:
            logger.error("🌙 [Reflection] Cleanup failed: %s", exc)

    # 10. Clean up expired world model entries & old thoughts
    cleanup_expired()

    logger.info("🌙 [Reflection] Night reflection complete. Digest: %s",
                (digest or "none")[:150])

    return parsed


# ── Scheduler loop ────────────────────────────────────────────────────────

def _already_reflected_today(chat_id: str, today_date) -> bool:
    """Check if we already ran reflection today."""
    from llm.graph.db import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM proactive_sends
                WHERE chat_id = %s AND trigger_key = 'night_reflection' AND trigger_date = %s
            """, (str(chat_id), today_date))
            return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        conn.close()


def _mark_reflected(chat_id: str, today_date):
    """Mark that reflection ran today (reuses proactive_sends table)."""
    from llm.graph.db import get_connection
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO proactive_sends (chat_id, trigger_key, trigger_date)
                    VALUES (%s, 'night_reflection', %s)
                    ON CONFLICT (chat_id, trigger_key, trigger_date) DO NOTHING
                """, (str(chat_id), today_date))
    finally:
        conn.close()


def run_reflection_scheduler(
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Background loop — waits for nighttime, then runs reflection once per night."""
    current_dir = Path(__file__).resolve().parent
    root_dir = current_dir.parents[3]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    load_dotenv(root_dir / ".env")

    if not _should_enable():
        logger.info("Reflection engine disabled via REFLECTION_ENGINE_ENABLE.")
        return

    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        logger.warning("Reflection engine: no TELEGRAM_CHAT_ID, disabled.")
        return

    tzinfo = _get_timezone()

    # Init world model tables
    from llm.graph.memory.world_model import init_world_model
    init_world_model()

    # Pick a random target hour around 1am (±jitter)
    base_hour = int(os.getenv("REFLECTION_HOUR", str(DEFAULT_REFLECTION_HOUR)))
    jitter_min = random.randint(-REFLECTION_JITTER_MINUTES, REFLECTION_JITTER_MINUTES)

    logger.info("🌙 Reflection engine started (target ~%02d:%02d local)",
                base_hour, (jitter_min % 60))

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Reflection engine stopping...")
            break

        now = datetime.now(tzinfo)
        today = now.date()

        # Check if it's reflection time (within the target window)
        target_minute = base_hour * 60 + jitter_min
        current_minute = now.hour * 60 + now.minute
        in_window = abs(current_minute - target_minute) <= 10  # 10 min window

        if in_window and not _already_reflected_today(chat_id, today):
            try:
                result = run_reflection(chat_id, tzinfo)
                _mark_reflected(chat_id, today)
                if result:
                    logger.info("🌙 Reflection complete for %s", today)
                else:
                    logger.warning("🌙 Reflection returned no result for %s", today)
            except Exception as exc:
                logger.error("🌙 Reflection error: %s", exc)
                # Still mark as reflected to avoid retry loops
                _mark_reflected(chat_id, today)

        time.sleep(POLL_INTERVAL)


def start_reflection_engine() -> Tuple[Optional[threading.Thread], Optional[threading.Event]]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_reflection_scheduler,
        kwargs={"stop_event": stop_event},
        daemon=True,
    )
    thread.start()
    return thread, stop_event


if __name__ == "__main__":
    # Manual trigger for testing
    load_dotenv()
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        result = run_reflection(chat_id)
        if result:
            print(json.dumps(result, indent=2, default=str))
    else:
        print("Set TELEGRAM_CHAT_ID to test reflection")
