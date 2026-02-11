import json
import logging
import os
import concurrent.futures
from typing import Optional, List
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator
from llm.graph.states.state import ChatState
from llm.graph.memory.episodic_memeory import EpisodicMemory
from llm.graph.memory.semantic_memory import SemanticMemory
from llm.graph.model.llm import get_cheap_llm, truncate_text, CHEAP_LLM_MAX_INPUT_CHARS
from llm.graph.nodes.helpers import extract_text
from llm.services.neo4j_service import get_people_graph

logger = logging.getLogger(__name__)

SUMMARY_TAG = "[Conversation Summary]"

SUMMARY_ENABLE = os.getenv("SUMMARY_ENABLE", "true").strip().lower() not in {"0", "false", "no", "off"}
SUMMARY_EVERY_TURNS = int(os.getenv("SUMMARY_EVERY_TURNS", "10"))
SUMMARY_CHAR_LIMIT = int(os.getenv("SUMMARY_CHAR_LIMIT", "4000"))
SUMMARY_WINDOW_TURNS = int(os.getenv("SUMMARY_WINDOW_TURNS", "10"))

# Reusable thread pool for background memory writes (avoid creating per-call)
_memory_executor = concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="memory")

# Initialize Memories
try:
    episodic_memory = EpisodicMemory()
    semantic_memory = SemanticMemory()
except Exception as e:
    logger.warning("Could not initialize Memories in processor: %s", e)
    episodic_memory = None
    semantic_memory = None

class EntityRelation(BaseModel):
    from_entity: str = Field(description="Name of the source entity (e.g., 'Chinmay', 'Climate KIC')")
    from_type: str = Field(description="Type: person, org, tool, location, project, concept, preference")
    relation: str = Field(description="Relationship (e.g., 'works_at', 'mother_of', 'prefers', 'likes', 'dislikes', 'located_in')")
    to_entity: str = Field(description="Name of the target entity (e.g., 'Berlin', 'Python', 'Mom')")
    to_type: str = Field(description="Type: person, org, tool, location, project, concept, preference")
    confidence: float = Field(description="0.0 to 1.0")


class PersonInfo(BaseModel):
    """A person mentioned in conversation and their relation to Chinmay."""
    name: str = Field(description="Person's name or role (e.g., 'Arjun', 'Mom', 'Dr. Shah')")
    relation_to_chinmay: str = Field(description="How they relate to Chinmay (e.g., 'mother', 'best friend', 'manager', 'sister', 'girlfriend', 'colleague')")
    category: str = Field(default="other", description="family | friend | colleague | other")
    notes: str = Field(default="", description="Any extra context mentioned about this person")


class PreferenceInfo(BaseModel):
    """A preference, like, dislike, or personal fact about Chinmay."""
    category: str = Field(description="Category: food, music, tech, habit, health, work, lifestyle, opinion, personality")
    key: str = Field(description="What the preference is about (e.g., 'favorite_cuisine', 'morning_routine', 'coffee_preference')")
    value: str = Field(description="The preference value (e.g., 'Italian', 'wakes up at 6am', 'black coffee')")
    sentiment: str = Field(default="positive", description="positive (likes/prefers), negative (dislikes/avoids), neutral (fact)")


class MemoryDecision(BaseModel):
    decision: str = Field(default="SKIP", description="SEMANTIC, EPISODIC, BOTH, PEOPLE, or SKIP")
    reason: str = Field(default="", description="Reasoning")
    
    # Entity relationships for semantic graph
    new_relationships: Optional[List[EntityRelation]] = Field(default_factory=list, description="List of new entity relationships to store.")

    @field_validator("new_relationships", mode="before")
    @classmethod
    def _coerce_null_relationships(cls, v):
        return v if v is not None else []

    # People — auto-extracted for Neo4j people graph
    people: Optional[List[PersonInfo]] = Field(default_factory=list, description="People mentioned with their relationship to Chinmay")

    @field_validator("people", mode="before")
    @classmethod
    def _coerce_null_people(cls, v):
        return v if v is not None else []

    # Preferences — auto-extracted
    preferences: Optional[List[PreferenceInfo]] = Field(default_factory=list, description="User preferences, likes, dislikes, personal facts")

    @field_validator("preferences", mode="before")
    @classmethod
    def _coerce_null_preferences(cls, v):
        return v if v is not None else []

    # Episodic
    episodic_content: Optional[str] = Field(default=None, description="Event summary")
    episodic_importance: Optional[float] = Field(default=None, description="Importance")
    episodic_tags: Optional[List[str]] = Field(default=None, description="Tags")
    episodic_expiry_days: Optional[float] = Field(default=None, description="Expiry in days")

def memory_processing_node(state: ChatState):
    messages = state.get("messages", [])
    if len(messages) < 2: return {}

    # Summarize periodically (human+AI turns) and append as a SystemMessage for continuity.
    # This summary is NOT stored in episodic memory; it just lives in conversation history.
    summary_msg = None
    if SUMMARY_ENABLE:
        last_summary_index = None
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if isinstance(msg, SystemMessage) and msg.content.startswith(SUMMARY_TAG):
                last_summary_index = idx
                break

        recent_messages = messages[last_summary_index + 1:] if last_summary_index is not None else messages
        recent_human_ai = [m for m in recent_messages if isinstance(m, (HumanMessage, AIMessage))]
        recent_char_count = sum(len(extract_text(m.content)) for m in recent_human_ai)

        if recent_human_ai and (
            len(recent_human_ai) >= SUMMARY_EVERY_TURNS or recent_char_count >= SUMMARY_CHAR_LIMIT
        ):
            window = recent_human_ai[-SUMMARY_WINDOW_TURNS:]
            window_text = "\n".join(
                [
                    ("User: " + extract_text(m.content)) if isinstance(m, HumanMessage) else ("Sunday: " + extract_text(m.content))
                    for m in window
                ]
            )
            # Truncate to stay within cheap LLM token limits
            window_text = truncate_text(window_text, CHEAP_LLM_MAX_INPUT_CHARS)
            llm = get_cheap_llm()
            if llm:
                try:
                    prompt = (
                        "Summarize the recent conversation concisely. Capture intents, decisions, and follow-ups. "
                        "Keep it short and actionable."
                    )
                    summary_text = extract_text(llm.invoke([
                        SystemMessage(content=prompt),
                        HumanMessage(content=window_text)
                    ]).content)
                    summary_msg = SystemMessage(content=f"{SUMMARY_TAG} {summary_text}")
                    logger.info("📝 [Summary] Generated conversation summary")
                except Exception as e:
                    logger.error("Error generating summary: %s", e)

    last_human = None
    last_ai = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and last_ai is None: last_ai = msg
        elif isinstance(msg, HumanMessage) and last_human is None: last_human = msg; break
    
    if not last_human or not last_ai: return {}

    interaction_text = f"User: {extract_text(last_human.content)}\nSunday: {extract_text(last_ai.content)}"
    # Truncate to stay within cheap LLM limits
    interaction_text = truncate_text(interaction_text, CHEAP_LLM_MAX_INPUT_CHARS // 2)
    
    # Retrieve existing knowledge to prevent duplicates
    existing_context = ""
    if semantic_memory:
        try:
            existing_facts = semantic_memory.retrieve_relevant_knowledge(interaction_text, k=5)
            if existing_facts:
                fact_strings = [f"- {f['content']}" for f in existing_facts]
                existing_context = truncate_text("\n".join(fact_strings), 1500)
        except Exception as e:
            logger.error("Error retrieving existing facts: %s", e)

    system_prompt = f"""You are the Memory Manager for Sunday, Chinmay's personal AI assistant.
Your job is to extract ALL meaningful information from conversations and store them.

EXISTING KNOWLEDGE (skip if already known — only skip EXACT duplicates):
{existing_context}

You MUST be AGGRESSIVE about extracting knowledge. NEVER skip personal information.

## WHAT TO ALWAYS EXTRACT:

### PEOPLE (CRITICAL — never miss these):
- ANY person mentioned by name or role (mom, dad, sister, friend, boss, girlfriend, etc.)
- Their relationship to Chinmay
- Any details about them (job, location, personality, birthday, etc.)
- Example: "my mom's name is Sunita" → person: Sunita, relation: mother, category: family
- Example: "Arjun got a new job" → person: Arjun (if relation known from context, include it)

### PREFERENCES (CRITICAL — never miss these):
- Food preferences (likes, dislikes, allergies, favorite restaurants)
- Music, movies, entertainment preferences
- Work style, productivity preferences
- Tech preferences (tools, languages, editors)
- Daily habits, routines
- Health info (sleep patterns, exercise, diet)
- Opinions on anything
- Example: "I hate mushrooms" → preference: food, key: mushroom, value: hates mushrooms, sentiment: negative
- Example: "I usually wake up at 6" → preference: habit, key: wake_time, value: 6am, sentiment: neutral

### RELATIONSHIPS (entity graph):
- Where someone works, lives, studies
- Project associations
- Tool/technology preferences
- Any factual connection between entities

### EVENTS (episodic):
- Plans, appointments, deadlines
- Things that happened today
- Decisions made
- Important moments

## DECISION RULES:
- SKIP ONLY for: pure greetings ("hi", "thanks"), small talk with ZERO factual content, or exact duplicates
- When in doubt, STORE IT. Better to over-remember than forget.
- If ANY person is mentioned → extract into "people" array AND create relationships
- If ANY preference/opinion/like/dislike → extract into "preferences" array
- Personal facts about Chinmay are HIGH VALUE — always store

You MUST return JSON with ALL these fields:
{{
  "decision": "SEMANTIC" | "EPISODIC" | "BOTH" | "SKIP",
  "reason": "why this decision",
  "new_relationships": [{{
    "from_entity": "Chinmay",
    "from_type": "person",
    "relation": "mother_is",
    "to_entity": "Sunita",
    "to_type": "person",
    "confidence": 1.0
  }}],
  "people": [{{
    "name": "Sunita",
    "relation_to_chinmay": "mother",
    "category": "family",
    "notes": "any extra context"
  }}],
  "preferences": [{{
    "category": "food",
    "key": "mushroom",
    "value": "dislikes mushrooms",
    "sentiment": "negative"
  }}],
  "episodic_content": "event summary or null",
  "episodic_importance": 0.7,
  "episodic_tags": ["tag"],
  "episodic_expiry_days": null
}}"""

    llm = get_cheap_llm() 
    if not llm: return {}
        
    structured_llm = llm.with_structured_output(MemoryDecision, method="json_mode")
    
    try:
        result = structured_llm.invoke([
            SystemMessage(content=system_prompt + "\n\nRespond with valid JSON matching the MemoryDecision schema."),
            HumanMessage(content=f"Analyze this interaction and extract ALL knowledge:\n{interaction_text}")
        ])
        
        executor = _memory_executor
        try:
            # ── 1. Store People in Neo4j Graph (ALWAYS, regardless of decision) ──
            if result.people:
                pg = get_people_graph()
                if pg.available:
                    for person in result.people:
                        logger.info("👤 [Neo4j] Adding person: %s (%s) - %s", 
                                   person.name, person.category, person.relation_to_chinmay)
                        executor.submit(
                            pg.add_person,
                            person.name,
                            person.relation_to_chinmay,
                            person.category,
                            person.notes
                        )
                        # Also store in semantic memory for vector search
                        if semantic_memory:
                            executor.submit(
                                semantic_memory.add_relationship,
                                "Chinmay", "person",
                                person.relation_to_chinmay,
                                person.name, "person",
                                1.0
                            )

            # ── 2. Store Preferences in Semantic Memory ──
            if result.preferences and semantic_memory:
                for pref in result.preferences:
                    logger.info("⭐ [Preference] %s: %s = %s (%s)", 
                               pref.category, pref.key, pref.value, pref.sentiment)
                    # Store as entity relationship: Chinmay --prefers/dislikes--> thing
                    relation = "prefers" if pref.sentiment == "positive" else (
                        "dislikes" if pref.sentiment == "negative" else "fact"
                    )
                    executor.submit(
                        semantic_memory.add_relationship,
                        "Chinmay", "person",
                        relation,
                        f"{pref.key}: {pref.value}", "preference",
                        0.95
                    )
                    # Also store as enriched entity with attributes
                    executor.submit(
                        _store_preference_entity,
                        pref.category, pref.key, pref.value, pref.sentiment
                    )

            # ── 3. Store Semantic Graph Relationships ──
            if result.new_relationships and semantic_memory:
                for rel in result.new_relationships:
                    logger.info("🧠 [Graph] %s --%s--> %s", rel.from_entity, rel.relation, rel.to_entity)
                    executor.submit(
                        semantic_memory.add_relationship,
                        rel.from_entity, rel.from_type,
                        rel.relation,
                        rel.to_entity, rel.to_type,
                        rel.confidence
                    )
            
            # ── 4. Store Episodic Memories ──
            if result.episodic_content and episodic_memory:
                expiry_msg = f"(Expires {result.episodic_expiry_days}d)" if result.episodic_expiry_days else "(Permanent)"
                logger.info("📖 [Episodic] %s %s", result.episodic_content, expiry_msg)
                executor.submit(
                    episodic_memory.add_memory,
                    result.episodic_content,
                    result.episodic_importance or 0.5,
                    "user",
                    result.episodic_tags or [],
                    result.episodic_expiry_days
                )
        except Exception as pool_exc:
            logger.error("Error submitting memory writes: %s", pool_exc)
            
        logger.info("💾 [Memory] decision=%s reason=%s people=%d prefs=%d rels=%d", 
                   result.decision, result.reason,
                   len(result.people or []),
                   len(result.preferences or []),
                   len(result.new_relationships or []))
    except Exception as e:
        logger.error("Error in memory processing: %s", e)

    # Return summary message (if created) to be stored in conversation history via LangGraph state.
    if summary_msg:
        return {"messages": [summary_msg]}

    return {}


def _store_preference_entity(category: str, key: str, value: str, sentiment: str):
    """Store a preference as a rich entity with attributes in semantic memory."""
    try:
        if not semantic_memory:
            return
        entity_name = f"{key}: {value}"
        entity_id = semantic_memory.get_or_create_entity(
            entity_name, "preference", f"{category} preference: {value}"
        )
        # Update attributes on the entity
        conn = semantic_memory._get_connection()
        conn.autocommit = True
        cur = conn.cursor()
        try:
            cur.execute("""
                UPDATE entities 
                SET attributes = attributes || %s::jsonb, 
                    last_updated = NOW()
                WHERE id = %s
            """, (
                json.dumps({
                    "category": category,
                    "key": key,
                    "value": value,
                    "sentiment": sentiment
                }),
                str(entity_id)
            ))
        finally:
            cur.close()
            conn.close()
        logger.info("⭐ [Preference Entity] Stored: %s = %s (%s)", key, value, sentiment)
    except Exception as e:
        logger.error("Error storing preference entity: %s", e)
