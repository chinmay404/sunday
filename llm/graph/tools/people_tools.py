"""Tools for managing people, relationships & preferences in Neo4j."""

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
        person_name: Name (e.g. "Arjun", "Mom", "Sunita").
        relation: How they relate to Chinmay (e.g. "mother", "best friend", "manager").
        category: family | friend | colleague | other.
        notes: Extra context about this person.
    """
    pg = get_people_graph()
    return pg.add_person(person_name, relation, category, notes)


@tool
def add_relation_between_people(
    from_person: str,
    to_person: str,
    relation: str,
    notes: str = "",
) -> str:
    """Add a relationship between any two people (not necessarily involving Chinmay).

    Args:
        from_person: Source person name.
        to_person: Target person name.
        relation: How they relate (e.g. "married_to", "colleague_of", "sibling").
        notes: Extra context.
    """
    pg = get_people_graph()
    return pg.add_relation(from_person, to_person, relation, notes)


@tool
def update_person_details(
    person_name: str,
    birthday: str = "",
    job: str = "",
    location: str = "",
    phone: str = "",
    email: str = "",
    extra_notes: str = "",
) -> str:
    """Update details/attributes about a person (birthday, job, location, contact info, etc.).

    Args:
        person_name: Name of the person to update.
        birthday: Birthday (e.g. "March 15", "1995-03-15").
        job: Job title or occupation.
        location: Where they live/work.
        phone: Phone number.
        email: Email address.
        extra_notes: Any additional info.
    """
    pg = get_people_graph()
    attrs = {}
    if birthday: attrs["birthday"] = birthday
    if job: attrs["job"] = job
    if location: attrs["location"] = location
    if phone: attrs["phone"] = phone
    if email: attrs["email"] = email
    if extra_notes: attrs["notes_extra"] = extra_notes
    if not attrs:
        return "No attributes provided to update."
    return pg.update_person_attributes(person_name, attrs)


@tool
def save_preference(
    category: str,
    key: str,
    value: str,
    sentiment: str = "positive",
) -> str:
    """Store a preference, like, or dislike for Chinmay.

    Args:
        category: food | music | tech | habit | health | work | lifestyle | opinion.
        key: What the preference is about (e.g. "coffee", "programming_language", "wake_time").
        value: The preference value (e.g. "black coffee", "Python", "6am").
        sentiment: positive (likes/prefers) | negative (dislikes/avoids) | neutral (fact).
    """
    pg = get_people_graph()
    return pg.add_preference(category, key, value, sentiment)


@tool
def get_person_info(person_name: str) -> str:
    """Look up everything known about a person — relationships, category, notes, attributes.

    Args:
        person_name: Name to look up.
    """
    pg = get_people_graph()
    return pg.get_person(person_name)


@tool
def list_people() -> str:
    """List all people in Chinmay's circle and their relationships, plus stored preferences."""
    pg = get_people_graph()
    result = pg.get_chinmay_circle()
    return result if result else "No people or preferences stored yet."


@tool
def get_preferences() -> str:
    """Get all of Chinmay's stored preferences, likes, and dislikes."""
    pg = get_people_graph()
    result = pg.get_all_preferences()
    return result if result else "No preferences stored yet."
