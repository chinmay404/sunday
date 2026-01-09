import json
import concurrent.futures
from typing import Optional, List
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from pydantic import BaseModel, Field
from llm.graph.states.state import ChatState
from llm.graph.memory.episodic_memeory import EpisodicMemory
from llm.graph.memory.semantic_memory import SemanticMemory
from llm.graph.model.llm import get_llm

SUMMARY_TAG = "[Conversation Summary]"

# Initialize Memories
try:
    episodic_memory = EpisodicMemory()
    semantic_memory = SemanticMemory()
except Exception as e:
    print(f"Warning: Could not initialize Memories in processor: {e}")
    episodic_memory = None
    semantic_memory = None

class EntityRelation(BaseModel):
    from_entity: str = Field(description="Name of the source entity (e.g., 'User', 'Climate KIC')")
    from_type: str = Field(description="Type: person, org, tool, location, project, concept")
    relation: str = Field(description="Relationship (e.g., 'works_at', 'located_in', 'uses')")
    to_entity: str = Field(description="Name of the target entity (e.g., 'Berlin', 'Python')")
    to_type: str = Field(description="Type: person, org, tool, location, project, concept")
    confidence: float = Field(description="0.0 to 1.0")

class MemoryDecision(BaseModel):
    decision: str = Field(description="SEMANTIC, EPISODIC, BOTH, or SKIP")
    reason: str = Field(description="Reasoning")
    
    # New Graph Structure
    new_relationships: List[EntityRelation] = Field(default_factory=list, description="List of new entity relationships to store.")

    # Episodic
    episodic_content: Optional[str] = Field(default=None, description="Event summary")
    episodic_importance: Optional[float] = Field(default=None, description="Importance")
    episodic_tags: Optional[List[str]] = Field(default=None, description="Tags")
    episodic_expiry_days: Optional[float] = Field(default=None, description="Expiry in days")

def memory_processing_node(state: ChatState):
    messages = state.get("messages", [])
    if len(messages) < 2: return {}

    # Summarize every 5 messages (human+AI turns) and append as a SystemMessage for continuity.
    # This summary is NOT stored in episodic memory; it just lives in conversation history.
    human_ai_messages = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]
    summary_msg = None
    if len(human_ai_messages) % 5 == 0:
        # Take the last 5 human/AI messages for the summary window
        window = human_ai_messages[-5:]
        window_text = "\n".join(
            [
                ("User: " + m.content) if isinstance(m, HumanMessage) else ("Sunday: " + m.content)
                for m in window
            ]
        )
        llm = get_llm()
        if llm:
            try:
                prompt = (
                    "Summarize the last 5 turns concisely. Capture intents, decisions, and follow-ups. "
                    "Keep it short and actionable."
                )
                summary_text = llm.invoke([
                    SystemMessage(content=prompt),
                    HumanMessage(content=window_text)
                ]).content
                summary_msg = SystemMessage(content=f"{SUMMARY_TAG} {summary_text}")
            except Exception as e:
                print(f"Error generating summary: {e}")

    last_human = None
    last_ai = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and last_ai is None: last_ai = msg
        elif isinstance(msg, HumanMessage) and last_human is None: last_human = msg; break
    
    if not last_human or not last_ai: return {}

    interaction_text = f"User: {last_human.content}\nSunday: {last_ai.content}"
    
    # Retrieve existing knowledge to prevent duplicates
    existing_context = ""
    if semantic_memory:
        try:
            existing_facts = semantic_memory.retrieve_relevant_knowledge(interaction_text, k=5)
            if existing_facts:
                fact_strings = [f"- {f['content']}" for f in existing_facts]
                existing_context = "\n".join(fact_strings)
        except Exception as e:
            print(f"Error retrieving existing facts: {e}")

    system_prompt = f"""
    You are the Memory Manager. Extract Entities and Relationships.
    
    EXISTING KNOWLEDGE (Do not re-save these unless updated):
    {existing_context}
    
    1. SEMANTIC (Entity-Graph):
       - "I work at Climate KIC in Amsterdam"
       -> (User, person) works_at (Climate KIC, org)
       -> (Climate KIC, org) located_in (Amsterdam, location)
       
    2. EPISODIC (Events):
       - "Meeting tomorrow" -> Expire 1 day.
    """

    llm = get_llm() 
    if not llm: return {}
        
    structured_llm = llm.with_structured_output(MemoryDecision)
    
    try:
        result = structured_llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Analyze:\n{interaction_text}")
        ])
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Store Semantic Graph
            if (result.decision in ["SEMANTIC", "BOTH"]) and result.new_relationships and semantic_memory:
                for rel in result.new_relationships:
                    print(f"🧠 [Graph] Linking: {rel.from_entity} --{rel.relation}--> {rel.to_entity}")
                    executor.submit(
                        semantic_memory.add_relationship,
                        rel.from_entity, rel.from_type,
                        rel.relation,
                        rel.to_entity, rel.to_type,
                        rel.confidence
                    )
            
            # Store Episodic
            if (result.decision in ["EPISODIC", "BOTH"]) and result.episodic_content and episodic_memory:
                expiry_msg = f"(Expires {result.episodic_expiry_days}d)" if result.episodic_expiry_days else "(Permanent)"
                print(f"📖 [Episodic] Storing: {result.episodic_content} {expiry_msg}")
                executor.submit(
                    episodic_memory.add_memory,
                    result.episodic_content,
                    result.episodic_importance or 0.5,
                    "user",
                    result.episodic_tags or [],
                    result.episodic_expiry_days
                )
            
    except Exception as e:
        print(f"Error in memory processing: {e}")

    # Return summary message (if created) to be stored in conversation history via LangGraph state.
    if summary_msg:
        return {"messages": [summary_msg]}

    return {}
