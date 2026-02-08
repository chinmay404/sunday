"""Utility tools: memory management, URL reading."""

import os
import uuid
import logging
import httpx
from typing import Optional
from langchain_core.tools import tool

from llm.graph.memory.semantic_memory import SemanticMemory
from llm.graph.memory.episodic_memeory import EpisodicMemory

logger = logging.getLogger(__name__)

# Lazy singletons — created once on first use
_semantic: SemanticMemory | None = None
_episodic: EpisodicMemory | None = None


def _get_semantic() -> SemanticMemory:
    global _semantic
    if _semantic is None:
        _semantic = SemanticMemory()
    return _semantic


def _get_episodic() -> EpisodicMemory:
    global _episodic
    if _episodic is None:
        _episodic = EpisodicMemory()
    return _episodic


# ── Memory Tools ──────────────────────────────────────────────


@tool
def search_memory(query: str, memory_type: str = "both", limit: int = 5) -> str:
    """Search stored memories and knowledge. Use when user asks 'what do you know about X' or you need to recall something.
    memory_type: 'semantic' (facts/relationships), 'episodic' (past conversations), or 'both'."""
    try:
        parts: list[str] = []

        if memory_type in ("semantic", "both"):
            sem = _get_semantic()
            facts = sem.retrieve_relevant_knowledge(query, k=limit)
            if facts:
                lines = [f"• {f['content']} (confidence: {f['confidence']:.0%})" for f in facts]
                parts.append("**Knowledge graph:**\n" + "\n".join(lines))
            else:
                parts.append("No semantic facts found.")

        if memory_type in ("episodic", "both"):
            epi = _get_episodic()
            memories = epi.retrieve_memories(query, k=limit)
            if memories:
                lines = [f"• [{m['date']}] {m['content']}" for m in memories]
                parts.append("**Episodic memories:**\n" + "\n".join(lines))
            else:
                parts.append("No episodic memories found.")

        return "\n\n".join(parts) if parts else "Nothing found in memory."
    except Exception as e:
        logger.exception("search_memory failed")
        return f"Memory search error: {e}"


@tool
def forget_memory(query: str, confirm: bool = True) -> str:
    """Delete episodic memories matching a query. Use when user says 'forget that', 'delete memory about X'.
    Finds and removes the closest matching memories."""
    if not confirm:
        return "Aborted — set confirm=True to actually delete."
    try:
        epi = _get_episodic()
        # Find matching memories first
        matches = epi.retrieve_memories(query, k=3)
        if not matches:
            return "No matching memories found — nothing to forget."

        # Delete them by content match
        conn = epi._get_connection()
        conn.autocommit = True
        cur = conn.cursor()
        deleted = 0
        try:
            for m in matches:
                cur.execute(
                    "DELETE FROM episodic_memory WHERE content = %s",
                    (m["content"],),
                )
                deleted += cur.rowcount
        finally:
            cur.close()
            conn.close()

        forgotten = "\n".join(f"• {m['content']}" for m in matches)
        return f"Forgot {deleted} memory(s):\n{forgotten}"
    except Exception as e:
        logger.exception("forget_memory failed")
        return f"Forget error: {e}"


# ── Web Tools ─────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SundayBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,text/plain",
}


@tool
def read_webpage(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL and return its text content (stripped of HTML). Use for reading articles, docs, or links shared by user."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True, headers=_HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")

        # Plain text / JSON — return as-is
        if "text/plain" in content_type or "application/json" in content_type:
            return resp.text[:max_chars]

        # HTML — do a rough strip
        text = _strip_html(resp.text)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…[truncated]"
        return text if text.strip() else "Page fetched but no readable text found."
    except httpx.HTTPStatusError as e:
        return f"HTTP {e.response.status_code} fetching {url}"
    except Exception as e:
        return f"Failed to fetch URL: {e}"


def _strip_html(html: str) -> str:
    """Cheap HTML → text without requiring beautifulsoup."""
    import re
    # Remove script/style blocks
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Decode common entities
    for entity, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                          ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")]:
        text = text.replace(entity, char)
    return text.strip()
