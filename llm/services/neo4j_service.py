"""
Neo4j People & Relationship Graph.

Stores people in Chinmay's life and their relationships.
Schema:
    (:Person {name, category})
    (:Person)-[:RELATES_TO {relation, notes, since}]->(:Person)

Env vars: NEO4J_URI, NEO4J_USER, NEO4J_PASS
"""

import logging
import os
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
    """Thin wrapper around Neo4j for managing people & relationships."""

    def __init__(self):
        self._driver = None
        if GraphDatabase is None:
            return
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASS")
        if not uri or not password:
            logger.warning("NEO4J_URI / NEO4J_PASS not set — PeopleGraph disabled")
            return
        try:
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
            self._driver.verify_connectivity()
            self._ensure_constraints()
            logger.info("Neo4j PeopleGraph connected (%s)", uri)
        except Exception as exc:
            logger.error("Neo4j connection failed: %s", exc)
            self._driver = None

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
            r.notes    = $notes
        RETURN p.name AS person
        """
        try:
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
        except Exception as exc:
            logger.error("add_person failed: %s", exc)
            return f"Failed to save person: {exc}"

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
            r.notes    = $notes
        RETURN a.name AS from_name, b.name AS to_name
        """
        try:
            with self._driver.session() as s:
                s.run(
                    cypher,
                    from_p=from_person.strip(),
                    to_p=to_person.strip(),
                    relation=relation.strip().lower(),
                    notes=notes.strip(),
                )
                return f"Saved: {from_person} --{relation}--> {to_person}"
        except Exception as exc:
            logger.error("add_relation failed: %s", exc)
            return f"Failed: {exc}"

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
        try:
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
        except Exception as exc:
            logger.error("get_person failed: %s", exc)
            return f"Error: {exc}"

    def get_chinmay_circle(self) -> str:
        """Get all people related to Chinmay — used for context injection."""
        if not self.available:
            return ""
        cypher = """
        MATCH (c:Person {name: 'Chinmay'})-[r:RELATES_TO]->(p:Person)
        RETURN p.name AS name, p.category AS category,
               r.relation AS relation, r.notes AS notes
        ORDER BY p.category, p.name
        """
        try:
            with self._driver.session() as s:
                records = list(s.run(cypher))
                if not records:
                    return ""
                lines = []
                for rec in records:
                    note = f" — {rec['notes']}" if rec["notes"] else ""
                    lines.append(
                        f"- {rec['name']} ({rec['category']}): {rec['relation']}{note}"
                    )
                return "People in Chinmay's life:\n" + "\n".join(lines)
        except Exception as exc:
            logger.error("get_chinmay_circle failed: %s", exc)
            return ""


# ── Module-level singleton ─────────────────────────────────────────────────

_instance: Optional[PeopleGraph] = None


def get_people_graph() -> PeopleGraph:
    global _instance
    if _instance is None:
        _instance = PeopleGraph()
    return _instance
