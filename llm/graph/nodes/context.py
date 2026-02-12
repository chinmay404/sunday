import concurrent.futures
import logging
import os
from langchain_core.messages import HumanMessage
from llm.graph.states.state import ChatState
from llm.graph.memory.episodic_memeory import EpisodicMemory
from llm.graph.memory.semantic_memory import SemanticMemory
from llm.services.time_manager import TimeManager
from llm.services.location_service import LocationService
from llm.graph.habits.action_log import get_recent_actions, get_habit_profile
from llm.services.neo4j_service import get_people_graph

logger = logging.getLogger(__name__)

# Initialize Services
try:
    episodic_memory = EpisodicMemory()
    semantic_memory = SemanticMemory()
    time_manager = TimeManager()
    location_service = LocationService()
except Exception as e:
    logger.warning("Could not initialize Services in context node: %s", e)
    episodic_memory = None
    semantic_memory = None
    time_manager = None
    location_service = None

# Reuse a single thread pool across all requests instead of creating one per message
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

DEFAULT_LOCATION_MAX_AGE_HOURS = 30.0


def _location_max_age_hours() -> float:
    raw = os.getenv("LOCATION_MAX_AGE_HOURS", str(DEFAULT_LOCATION_MAX_AGE_HOURS)).strip()
    try:
        return max(1.0, float(raw))
    except Exception:
        return DEFAULT_LOCATION_MAX_AGE_HOURS

def retrieve_semantic(query):
    if not semantic_memory:
        return ""
    try:
        # Use the new Graph-based retrieval
        knowledge = semantic_memory.retrieve_relevant_knowledge(query, k=10)
        if knowledge:
            # Format: "User works_at Climate KIC (Confidence: 1.0)"
            knowledge_strings = [f"- {k['content']} (Confidence: {k['confidence']})" for k in knowledge]
            return "Chinmay background::\n" + "\n".join(knowledge_strings)
    except Exception as e:
        logger.error("Error retrieving semantic knowledge: %s", e)
    return ""

def retrieve_episodic(query):
    if not episodic_memory:
        return ""
    try:
        memories = episodic_memory.retrieve_memories(query, k=5)
        if memories:
            mem_strings = [f"- {m['date']}: {m['content']}" for m in memories]
            return "Recent situation::\n" + "\n".join(mem_strings)
    except Exception as e:
        logger.error("Error retrieving episodic memories: %s", e)
    return ""

def context_gathering_node(state: ChatState):
    """
    Gather context from BOTH episodic and semantic memory in PARALLEL.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"memory_context": ""}
    
    # Find the last human message
    last_human_message = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_human_message = msg
            break
            
    if not last_human_message:
        return {"memory_context": ""}
        
    query = last_human_message.content
    if isinstance(query, list):
        query = " ".join([str(part) for part in query])
    
    context_parts = []
    
    # 1. Real-Time Context (Synchronous call to APIs)
    if time_manager:
        try:
            # This fetches from Google/Todoist APIs
            time_context = time_manager.get_time_context()
            context_parts.append(f"Current time context (Use naturally, do not explicitly mention unless relevant at the current time event or planned just after few time):\n{time_context}")
        except Exception as e:
            logger.error("Error retrieving time context: %s", e)

    # 1.5. Location context (Inject if available and recent, regardless of query keywords)
    if location_service and state.get("user_id"):
        try:
            loc = location_service.get_location_context(
                str(state.get("user_id")),
                max_age_hours=_location_max_age_hours(),
            )
            if loc:
                context_parts.append(f"User context:\n{loc}")
        except Exception as e:
            logger.error("Error retrieving location context: %s", e)
    
    # 2. Habit / action context (lightweight DB query)
    thread_id = state.get("thread_id", "default")
    try:
        habit_parts = []
        profile = get_habit_profile(thread_id)
        if profile:
            habit_parts.append(f"Habit profile: {profile}")
        recent = get_recent_actions(thread_id=thread_id, since_hours=24, limit=5)
        if recent:
            action_lines = [f"- {a['action_type']}: {a['description']}" for a in recent]
            habit_parts.append("Recent actions (24h):\n" + "\n".join(action_lines))
        if habit_parts:
            context_parts.append("\n".join(habit_parts))
    except Exception as e:
        logger.error("Error retrieving habits context: %s", e)

    # 2.5. People / relationship graph (Neo4j)
    try:
        pg = get_people_graph()
        if pg.available:
            people_ctx = pg.get_chinmay_circle()
            if people_ctx:
                context_parts.append(people_ctx)
    except Exception as e:
        logger.error("Error retrieving people graph: %s", e)

    # 3. Parallel Memory Retrieval (reuse module-level pool)
    future_semantic = _executor.submit(retrieve_semantic, query)
    future_episodic = _executor.submit(retrieve_episodic, query)

    semantic_result = future_semantic.result(timeout=10)
    episodic_result = future_episodic.result(timeout=10)

    if semantic_result:
        context_parts.append(semantic_result)
    if episodic_result:
        context_parts.append(episodic_result)

    # 4. World model (Sunday's persistent inner understanding + private thoughts)
    try:
        from llm.graph.memory.world_model import render_for_prompt
        world_ctx = render_for_prompt()
        if world_ctx:
            context_parts.append(world_ctx)
    except Exception as e:
        logger.error("Error loading world model: %s", e)

    final_context = "\n\n".join(context_parts)
    
    if final_context:
        logger.info("🔍 [Context] Injected:\n%s", final_context)
        
    return {"memory_context": final_context}
