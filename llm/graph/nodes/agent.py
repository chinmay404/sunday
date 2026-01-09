from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from llm.graph.states.state import ChatState ,ActionDecided
from llm.graph.model.llm import get_llm ,get_llm_with_tools , get_thinking_llm
from llm.graph.tools.manager import get_all_tools

def gather_context(state: ChatState):
    pass



# Persona and profile that should always precede user/assistant turns.
PERSONA_MESSAGE = SystemMessage(
    content=(
        "You are Sunday, a proactive personal AI agent and true PA (not a chatbot). "
        "You keep responses concise, helpful, action-oriented, and time-aware. "
        "Speak naturally, like a capable teammate."
    )
)

USER_PROFILE_MESSAGE = SystemMessage(
    content=(
        "User: Sirius. Role: researcher working on a thesis. "
        "Prefers direct guidance, minimal fluff, and quick next steps."
    )
)


def decision_taker(state : ChatState):
    llm = get_thinking_llm(gemini=True)
    if not llm : 
        return {
            "Action_decided": ActionDecided(
                internal_feeling="Thinking not available",
                what_matters="Thinking not available",
                suggested_vibe="Thinking not available",
                conversation_direction="Thinking not available",
                how_to_show_up="Thinking not available"
            )
        }
    thinking_with_strctured_llm = llm.with_structured_output(ActionDecided)
    response = thinking_with_strctured_llm.invoke(state["messages"])
    return {"Action_decided": response}
        





def agent_node(state: ChatState):
    """
    The agent node that calls the LLM with tools.
    """
    llm = get_llm()
    if not llm:
        raise ValueError("Failed to initialize LLM") 
    tools = get_all_tools()
    llm_with_tools = llm.bind_tools(tools)
    
    messages = list(state["messages"]) # Create a copy to avoid modifying state directly if needed

    # Find the latest conversation summary if present.
    latest_summary = None
    for msg in reversed(messages):
        if isinstance(msg, SystemMessage) and msg.content.startswith("[Conversation Summary]"):
            latest_summary = msg
            break

    # Keep only the last 5 human/AI messages to reduce prompt bloat.
    human_ai = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]
    window = human_ai[-5:]

    # Rebuild message list: persona/profile, summary (if any), then window.
    rebuilt: list = []
    rebuilt.extend([PERSONA_MESSAGE, USER_PROFILE_MESSAGE])
    if latest_summary:
        rebuilt.append(latest_summary)
    rebuilt.extend(window)
    messages = rebuilt
    
    # Inject memory context while keeping persona/system prompts at the very front.
    memory_context = state.get("memory_context")
    if memory_context:
        context_msg = SystemMessage(content=f"You have access to the following past memories:\n{memory_context}")
        if messages and isinstance(messages[0], SystemMessage):
            messages.insert(1, context_msg)
        else:
            messages = [context_msg] + messages
        
    response = llm_with_tools.invoke(messages)
    
    return {"messages": [response]}
