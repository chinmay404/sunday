from pathlib import Path
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from llm.graph.states.state import ChatState ,ActionDecided
from llm.graph.model.llm import get_llm ,get_llm_with_tools , get_thinking_llm
from llm.graph.tools.manager import get_all_tools
from llm.graph.nodes.map_user import map_user
def gather_context(state: ChatState):
    pass


# def decision_taker(state : ChatState):
#     llm = get_thinking_llm(gemini=True)
#     if not llm : 
#         return {
#             "Action_decided": ActionDecided(
#                 internal_feeling="Thinking not available",
#                 what_matters="Thinking not available",
#                 suggested_vibe="Thinking not available",
#                 conversation_direction="Thinking not available",
#                 how_to_show_up="Thinking not available"
#             )
#         }
#     thinking_with_strctured_llm = llm.with_structured_output(ActionDecided)
#     response = thinking_with_strctured_llm.invoke(state["messages"])
#     return {"Action_decided": response}
        

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"

def _render_prompt(template: str, **kwargs) -> str:
    try:
        return template.format(**kwargs)
    except Exception:
        return template


def _load_prompt(filename: str, **kwargs) -> str:
    path = PROMPT_DIR / filename
    try:
        template = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError
    except Exception as exc:
        print(f"Error reading prompt {path}: {exc}")
        raise FileNotFoundError
    return _render_prompt(template, **kwargs)




def agent_node(state: ChatState):
    """
    The agent node that calls the LLM with tools.
    """
    llm = get_llm()
    if not llm:
        raise ValueError("Failed to initialize LLM") 
    tools = get_all_tools()
    llm_with_tools = llm.bind_tools(tools)
    
    messages = list(state["messages"]) 

    # Find the latest conversation summary if present.
    latest_summary = None
    for msg in reversed(messages):
        if isinstance(msg, SystemMessage) and msg.content.startswith("[Conversation Summary]"):
            latest_summary = msg
            break

    # Keep only the last 5 human/AI messages to reduce prompt bloat.
    human_ai = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]
    window = human_ai[-5:]

    # Determine current speaker
    current_speaker = map_user("7173566704")
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
             if hasattr(m, "name") and m.name:
                 current_speaker = m.name
             break
    
    platform = state.get("platform", "Unknown Interface")

    if current_speaker.lower() in ["chinmay", "sirius", "admin"]:
        system_content = _load_prompt(
            "owner.md",
            platform=platform,
        )
    else:
        system_content = _load_prompt(
            "guest.md",
            platform=platform,
            current_speaker=current_speaker,
        )

    # 1. Add Default System Prompt
    system_messages = [SystemMessage(content=system_content)]

    # 2. Add Dynamic/Custom System Prompt from API if provided
    if state.get("system_prompt"):
        system_messages.append(SystemMessage(content=f"# Additional Instructions\n{state['system_prompt']}"))

    # 3. Add Memory Context
    if state.get("memory_context"):
        system_messages.append(SystemMessage(content=f"Here’s what you know about Chinmay right now:\n{state['memory_context']}"))
        
    # Rebuild message list: System Messages -> Summary (if any) -> Recent Chat Window
    rebuilt: list = []
    rebuilt.extend(system_messages)
    
    if latest_summary:
        rebuilt.append(latest_summary)
        
    rebuilt.extend(window)
    messages = rebuilt
    print(f"BUILT MESSAGES : {messages}")
    response = llm_with_tools.invoke(messages)
    
    return {"messages": [response]}
