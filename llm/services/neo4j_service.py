"""
Neo4j People & Relationship Graph.

Stores people in Chinmay's life and their relationships, preferences, and attributes.
Schema:
    (:Person {name, category, attributes})
    (:Person)-[:RELATES_TO {relation, notes, since}]->(:Person)
    (:Person)-[:HAS_PREFERENCE {category, sentiment}]->(:Preference {key, value})

Env vars: NEO4J_URI, NEO4J_USER, NEO4J_PASS
"""

import logging
import os
import time
import threading
from functools import wraps
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None
    logger.warning("neo4j package not installed — PeopleGraph disabled")


class PeopleGraph:
    """Thin wrapper around Neo4j for managing people & relationships.
    
    Features:
      - Auto-reconnect on connection failures (ConnectionResetError, etc.)
      - Retry with backoff for transient errors
      - Thread-safe reconnection via lock
    """

    _MAX_RETRIES = 2
    _RECONNECT_LOCK = threading.Lock()

    def __init__(self):
        self._driver = None
        self._uri = None
        self._auth = None
        if GraphDatabase is None:
            return
        self._uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASS")
        if not self._uri or not password:
            logger.warning("NEO4J_URI / NEO4J_PASS not set — PeopleGraph disabled")
            return
        self._auth = (user, password)
        self._connect()

    def _connect(self):
        """Establish (or re-establish) Neo4j connection."""
        try:
            if self._driver:
                try:
                    self._driver.close()
                except Exception:
                    pass
            self._driver = GraphDatabase.driver(self._uri, auth=self._auth)
            self._driver.verify_connectivity()
            self._ensure_constraints()
            logger.info("Neo4j PeopleGraph connected (%s)", self._uri)
        except Exception as exc:
            logger.error("Neo4j connection failed: %s", exc)
            self._driver = None

    def _reconnect(self):
        """Thread-safe reconnection."""
        with self._RECONNECT_LOCK:
            # Double-check: another thread might have reconnected already
            try:
                if self._driver:
                    self._driver.verify_connectivity()
                    return  # already reconnected
            except Exception:
                pass
            logger.info("Neo4j reconnecting...")
            self._connect()

    def _run_with_retry(self, operation_name: str, fn, *args, **kwargs):
        """Execute a Neo4j operation with auto-reconnect on transient failures."""
        last_exc = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                err_msg = str(exc).lower()
                is_transient = any(s in err_msg for s in (
                    "connection reset", "defunct", "broken pipe", "connection refused",
                    "session expired", "not connected", "failed to read",
                    "service unavailable", "connection closed",
                ))
                if not is_transient:
                    logger.error("%s failed: %s", operation_name, exc)
                    return None
                if attempt < self._MAX_RETRIES:
                    wait = 2 ** attempt
                    logger.warning("%s transient error (attempt %d/%d), reconnecting in %ds: %s",
                                   operation_name, attempt + 1, self._MAX_RETRIES + 1, wait,
                                   str(exc)[:120])
                    time.sleep(wait)
                    self._reconnect()
                else:
                    logger.error("%s failed after %d retries: %s",
                                 operation_name, self._MAX_RETRIES + 1, exc)
        return None

    @property
    def available(self) -> bool:
        return self._driver is not None

    def close(self):
        if self._driver:
            self._driver.close()

    # ── Schema ─────────────────────────────────────────────────────────────

    def _ensure_constraints(self):
        with self._driver.session() as s:
            s.run(
                "CREATE CONSTRAINT IF NOT EXISTS "
                "FOR (p:Person) REQUIRE p.name IS UNIQUE"
            )

    # ── Write ──────────────────────────────────────────────────────────────

    def add_person(
        self,
        name: str,
        relation_to_chinmay: str,
        category: str = "other",
        notes: str = "",
    ) -> str:
        """Add a person and their relationship to Chinmay.

        Args:
            name: Person's name (e.g. "Mom", "Arjun").
            relation_to_chinmay: e.g. "mother", "best friend", "manager".
            category: family | friend | colleague | other.
            notes: Optional free-text context.

        Returns:
            Confirmation string.
        """
        if not self.available:
            return "People graph not available."
        cypher = """
        MERGE (c:Person {name: 'Chinmay'})
        SET c.category = 'self'
        MERGE (p:Person {name: $name})
        SET p.category = $category
        MERGE (c)-[r:RELATES_TO]->(p)
        SET r.relation = $relation,
            r.notes    = CASE WHEN r.notes IS NULL OR r.notes = '' THEN $notes 
                         WHEN $notes = '' THEN r.notes
                         ELSE r.notes + ' | ' + $notes END,
            r.updated_at = datetime()
        RETURN p.name AS person
        """
        def _do():
            with self._driver.session() as s:
                result = s.run(
                    cypher,
                    name=name.strip(),
                    category=category.strip().lower(),
                    relation=relation_to_chinmay.strip().lower(),
                    notes=notes.strip(),
                )
                record = result.single()
                return f"Saved: {record['person']} ({relation_to_chinmay})"
        result = self._run_with_retry("add_person", _do)
        return result if result else f"Failed to save person: {name}"

    def add_relation(
        self,
        from_person: str,
        to_person: str,
        relation: str,
        notes: str = "",
    ) -> str:
        """Add a relationship between any two people (not just to Chinmay)."""
        if not self.available:
            return "People graph not available."
        cypher = """
        MERGE (a:Person {name: $from_p})
        MERGE (b:Person {name: $to_p})
        MERGE (a)-[r:RELATES_TO]->(b)
        SET r.relation = $relation,
            r.notes    = $notes,
            r.updated_at = datetime()
        RETURN a.name AS from_name, b.name AS to_name
        """
        def _do():
            with self._driver.session() as s:
                s.run(
                    cypher,
                    from_p=from_person.strip(),
                    to_p=to_person.strip(),
                    relation=relation.strip().lower(),
                    notes=notes.strip(),
                )
                return f"Saved: {from_person} --{relation}--> {to_person}"
        result = self._run_with_retry("add_relation", _do)
        return result if result else f"Failed to save relation: {from_person} -> {to_person}"

    def update_person_attributes(
        self,
        name: str,
        attributes: dict,
    ) -> str:
        """Update attributes/details on a person node (birthday, job, location, etc.).

        Args:
            name: Person's name.
            attributes: Dict of key-value pairs to set (e.g. {"birthday": "March 15", "job": "engineer"}).
        """
        if not self.available:
            return "People graph not available."
        # Build dynamic SET clause
        set_parts = []
        params = {"name": name.strip()}
        for key, value in attributes.items():
            safe_key = key.replace(" ", "_").replace("-", "_").lower()
            param_name = f"attr_{safe_key}"
            set_parts.append(f"p.{safe_key} = ${param_name}")
            params[param_name] = str(value)
        
        if not set_parts:
            return "No attributes provided."
        
        set_clause = ", ".join(set_parts)
        cypher = f"""
        MERGE (p:Person {{name: $name}})
        SET {set_clause}, p.updated_at = datetime()
        RETURN p.name AS person
        """
        def _do():
            with self._driver.session() as s:
                result = s.run(cypher, **params)
                record = result.single()
                attr_str = ", ".join(f"{k}={v}" for k, v in attributes.items())
                return f"Updated {record['person']}: {attr_str}"
        result = self._run_with_retry("update_person_attributes", _do)
        return result if result else f"Failed to update attributes for: {name}"

    def add_preference(
        self,
        category: str,
        key: str,
        value: str,
        sentiment: str = "positive",
    ) -> str:
        """Store a preference for Chinmay in the graph.

        Args:
            category: food, music, tech, habit, health, work, lifestyle, opinion.
            key: What the preference is about.
            value: The preference value.
            sentiment: positive (likes), negative (dislikes), neutral (fact).
        """
        if not self.available:
            return "People graph not available."
        cypher = """
        MERGE (c:Person {name: 'Chinmay'})
        MERGE (pref:Preference {key: $key})
        SET pref.value = $value,
            pref.category = $category,
            pref.updated_at = datetime()
        MERGE (c)-[r:HAS_PREFERENCE]->(pref)
        SET r.sentiment = $sentiment,
            r.category = $category,
            r.updated_at = datetime()
        RETURN pref.key AS pref_key
        """
        def _do():
            with self._driver.session() as s:
                result = s.run(
                    cypher,
                    category=category.strip().lower(),
                    key=key.strip().lower(),
                    value=value.strip(),
                    sentiment=sentiment.strip().lower(),
                )
                record = result.single()
                return f"Preference saved: {record['pref_key']} = {value} ({sentiment})"
        result = self._run_with_retry("add_preference", _do)
        return result if result else f"Failed to save preference: {key}"

    def get_all_preferences(self) -> str:
        """Get all of Chinmay's stored preferences."""
        if not self.available:
            return ""
        cypher = """
        MATCH (c:Person {name: 'Chinmay'})-[r:HAS_PREFERENCE]->(pref:Preference)
        RETURN pref.key AS key, pref.value AS value, 
               pref.category AS category, r.sentiment AS sentiment
        ORDER BY pref.category, pref.key
        """
        def _do():
            with self._driver.session() as s:
                records = list(s.run(cypher))
                if not records:
                    return ""
                lines = []
                for rec in records:
                    sentiment_icon = "👍" if rec["sentiment"] == "positive" else (
                        "👎" if rec["sentiment"] == "negative" else "📌"
                    )
                    lines.append(
                        f"- {sentiment_icon} [{rec['category']}] {rec['key']}: {rec['value']}"
                    )
                return "Chinmay's preferences:\n" + "\n".join(lines)
        result = self._run_with_retry("get_all_preferences", _do)
        return result if result is not None else ""

    # ── Read ───────────────────────────────────────────────────────────────

    def get_person(self, name: str) -> str:
        """Get everything known about a specific person."""
        if not self.available:
            return "People graph not available."
        cypher = """
        MATCH (p:Person {name: $name})
        OPTIONAL MATCH (p)-[r:RELATES_TO]-(other:Person)
        RETURN p.name AS name, p.category AS category,
               collect({
                   other: other.name,
                   relation: r.relation,
                   notes: r.notes,
                   direction: CASE WHEN startNode(r) = p THEN 'outgoing' ELSE 'incoming' END
               }) AS relations
        """
        def _do():
            with self._driver.session() as s:
                record = s.run(cypher, name=name.strip()).single()
                if not record:
                    return f"No info about '{name}' in the people graph."
                lines = [f"{record['name']} ({record['category'] or 'unknown'})"]
                for rel in record["relations"]:
                    if rel["other"]:
                        direction = "→" if rel["direction"] == "outgoing" else "←"
                        note = f" ({rel['notes']})" if rel.get("notes") else ""
                        lines.append(
                            f"  {direction} {rel['relation']} {rel['other']}{note}"
                        )
                return "\n".join(lines)
        result = self._run_with_retry("get_person", _do)
        return result if result else f"Error fetching person: {name}"

    def get_chinmay_circle(self) -> str:
        """Get all people related to Chinmay + preferences — used for context injection."""
        if not self.available:
            return ""
        
        parts = []
        
        # People
        cypher_people = """
        MATCH (c:Person {name: 'Chinmay'})-[r:RELATES_TO]->(p:Person)
        RETURN p.name AS name, p.category AS category,
               r.relation AS relation, r.notes AS notes
        ORDER BY p.category, p.name
        """
        # Preferences
        cypher_prefs = """
        MATCH (c:Person {name: 'Chinmay'})-[r:HAS_PREFERENCE]->(pref:Preference)
        RETURN pref.key AS key, pref.value AS value,
               pref.category AS category, r.sentiment AS sentiment
        ORDER BY pref.category, pref.key
        """
        def _do():
            with self._driver.session() as s:
                # People
                records = list(s.run(cypher_people))
                if records:
                    lines = []
                    for rec in records:
                        note = f" — {rec['notes']}" if rec["notes"] else ""
                        lines.append(
                            f"- {rec['name']} ({rec['category']}): {rec['relation']}{note}"
                        )
                    parts.append("People in Chinmay's life:\n" + "\n".join(lines))
                
                # Preferences
                pref_records = list(s.run(cypher_prefs))
                if pref_records:
                    pref_lines = []
                    for rec in pref_records:
                        sentiment_icon = "👍" if rec["sentiment"] == "positive" else (
                            "👎" if rec["sentiment"] == "negative" else "📌"
                        )
                        pref_lines.append(
                            f"- {sentiment_icon} [{rec['category']}] {rec['key']}: {rec['value']}"
                        )
                    parts.append("Chinmay's preferences:\n" + "\n".join(pref_lines))
                
                return "\n\n".join(parts) if parts else ""
        result = self._run_with_retry("get_chinmay_circle", _do)
        return result if result else ""


# ── Module-level singleton ─────────────────────────────────────────────────

_instance: Optional[PeopleGraph] = None


def get_people_graph() -> PeopleGraph:
    global _instance
    if _instance is None:
        _instance = PeopleGraph()
    return _instance
