"""Tools for managing people & relationships in Neo4j."""

from langchain_core.tools import tool
from llm.services.neo4j_service import get_people_graph


@tool
def add_person_relation(
    person_name: str,
    relation: str,
    category: str = "other",
    notes: str = "",
) -> str:
    """Save a person and their relationship to Chinmay.

    Args:
        person_name: Name (e.g. "Arjun", "Mom").
        relation: How they relate to Chinmay (e.g. "mother", "best friend", "manager").
        category: family | friend | colleague | other.
        notes: Extra context about this person.
    """
    pg = get_people_graph()
    return pg.add_person(person_name, relation, category, notes)


@tool
def get_person_info(person_name: str) -> str:
    """Look up everything known about a person — relationships, category, notes.

    Args:
        person_name: Name to look up.
    """
    pg = get_people_graph()
    return pg.get_person(person_name)


@tool
def list_people() -> str:
    """List all people in Chinmay's circle and their relationships."""
    pg = get_people_graph()
    result = pg.get_chinmay_circle()
    return result if result else "No people stored yet."
