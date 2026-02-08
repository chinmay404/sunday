import concurrent.futures
import os
from langchain_core.messages import HumanMessage
from llm.graph.states.state import ChatState
from llm.graph.memory.episodic_memeory import EpisodicMemory
from llm.graph.memory.semantic_memory import SemanticMemory
from llm.services.time_manager import TimeManager
from llm.services.location_service import LocationService

# Initialize Services
try:
    episodic_memory = EpisodicMemory()
    semantic_memory = SemanticMemory()
    # This will trigger Auth flows if credentials exist
    time_manager = TimeManager()
    location_service = LocationService()
except Exception as e:
    print(f"Warning: Could not initialize Services in context node: {e}")
    episodic_memory = None
    semantic_memory = None
    time_manager = None
    location_service = None

DEFAULT_LOCATION_MAX_AGE_HOURS = 30.0
LOCATION_KEYWORDS = (
    "where",
    "address",
    "place",
    "location",
    "home",
    "office",
    "work",
    "near",
    "nearby",
    "around me",
    "distance",
    "closest",
    "nearest",
    "route",
    "directions",
    "coffee shop",
    "restaurant",
    "gym",
)


def _location_context_enabled_for_query(query: str) -> bool:
    mode = os.getenv("LOCATION_CONTEXT_MODE", "on_demand").strip().lower()
    if mode in {"always", "all"}:
        return True
    lowered = (query or "").lower()
    return any(keyword in lowered for keyword in LOCATION_KEYWORDS)


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
        print(f"Error retrieving semantic knowledge: {e}")
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
        print(f"Error retrieving episodic memories: {e}")
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
            print(f"Error retrieving time context: {e}")

    # 1.5. Location context (only when query is location-relevant unless configured otherwise)
    if location_service and state.get("user_id") and _location_context_enabled_for_query(str(query)):
        try:
            loc = location_service.get_location_context(
                str(state.get("user_id")),
                max_age_hours=_location_max_age_hours(),
            )
            if loc:
                context_parts.append(f"User context:\n{loc}")
        except Exception as e:
            print(f"Error retrieving location context: {e}")
    
    # 2. Parallel Memory Retrieval
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_semantic = executor.submit(retrieve_semantic, query)
        future_episodic = executor.submit(retrieve_episodic, query)
        
        semantic_result = future_semantic.result()
        episodic_result = future_episodic.result()
        
        if semantic_result:
            context_parts.append(semantic_result)
        if episodic_result:
            context_parts.append(episodic_result)
            
    final_context = "\n\n".join(context_parts)
    
    # Debug print to see what's being injected
    if final_context:
        print(f"🔍 [Context] Injected:\n{final_context}")
        
    return {"memory_context": final_context}
