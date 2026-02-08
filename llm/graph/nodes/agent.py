from pathlib import Path
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from llm.graph.states.state import ChatState
from llm.graph.model.llm import get_llm
from llm.graph.tools.manager import ALL_TOOLS
from llm.graph.nodes.map_user import map_user


PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"

# Cache prompts in memory — read once, reuse forever (restart to reload)
_prompt_cache: dict[str, str] = {}


def _render_prompt(template: str, **kwargs) -> str:
    try:
        return template.format(**kwargs)
    except Exception:
        return template


def _load_prompt(filename: str, **kwargs) -> str:
    # Read from disk once, then cache the raw template
    if filename not in _prompt_cache:
        path = PROMPT_DIR / filename
        try:
            _prompt_cache[filename] = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise
        except Exception as exc:
            print(f"Error reading prompt {path}: {exc}")
            raise FileNotFoundError
    return _render_prompt(_prompt_cache[filename], **kwargs)


def agent_node(state: ChatState):
    """
    The agent node that calls the LLM with tools.
    Tools are cached at module level via ALL_TOOLS.
    """
    llm = get_llm()
    if not llm:
        raise ValueError("Failed to initialize LLM")
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

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

    # Determine current speaker from state (set by Telegram/API layer)
    current_speaker = state.get("user_name") or ""
    if not current_speaker or current_speaker == "User Not in List Ask for Further Information":
        # Fallback: try to read from message name attribute
        for m in reversed(messages):
            if isinstance(m, HumanMessage) and hasattr(m, "name") and m.name:
                current_speaker = m.name
                break
        if not current_speaker or current_speaker == "User Not in List Ask for Further Information":
            current_speaker = "Unknown"

    platform = state.get("platform", "Unknown Interface")

    if current_speaker.lower() in ["chinmay", "sirius", "admin"]:
        system_content = _load_prompt("owner.md", platform=platform)
    else:
        system_content = _load_prompt(
            "guest.md",
            platform=platform,
            current_speaker=current_speaker,
        )

    # 1. System prompt
    system_messages = [SystemMessage(content=system_content)]

    # 2. Additional instructions from API caller
    if state.get("system_prompt"):
        system_messages.append(
            SystemMessage(content=f"# Additional Instructions\n{state['system_prompt']}")
        )

    # 3. Memory context (time, location, semantic graph, episodic memories)
    if state.get("memory_context"):
        system_messages.append(
            SystemMessage(
                content=f"Here's what you know about Chinmay right now:\n{state['memory_context']}"
            )
        )

    # Rebuild: System → Summary → Recent chat window
    rebuilt: list = []
    rebuilt.extend(system_messages)
    if latest_summary:
        rebuilt.append(latest_summary)
    rebuilt.extend(window)

    response = llm_with_tools.invoke(rebuilt)
    return {"messages": [response]}
