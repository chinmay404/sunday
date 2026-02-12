import logging
from pathlib import Path
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from llm.graph.states.state import ChatState
from llm.graph.model.llm import get_llm
from llm.graph.tools.manager import ALL_TOOLS
from llm.graph.nodes.map_user import map_user
from llm.graph.nodes.helpers import extract_text

logger = logging.getLogger(__name__)


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

    # Keep the last 15 human/AI/tool messages to preserve context.
    # ToolMessages MUST be kept alongside the AIMessage that triggered them,
    # otherwise the LLM sees a tool_call with no result and hallucinates.
    human_ai = [m for m in messages if isinstance(m, (HumanMessage, AIMessage, ToolMessage))]
    window = human_ai[-15:]

    # ── Sanitize message window ──────────────────────────────────────
    # Fix issues that crash both Gemini and Groq:
    # 1. ToolMessages with null/empty content → replace with "(no output)"
    # 2. AIMessage with tool_calls but missing ToolMessage responses → strip tool_calls
    # 3. Orphaned ToolMessages (no matching AIMessage tool_call) → remove
    # 4. Window must start with HumanMessage (Gemini requirement)
    sanitized: list = []
    for msg in window:
        if isinstance(msg, ToolMessage):
            # Fix empty content — LLMs require non-empty string
            content = msg.content
            if content is None or (isinstance(content, str) and not content.strip()):
                msg = ToolMessage(
                    content="(no output)",
                    tool_call_id=getattr(msg, "tool_call_id", ""),
                    name=getattr(msg, "name", ""),
                )
            elif isinstance(content, list):
                # Some tools return list content — stringify it
                msg = ToolMessage(
                    content=str(content) if content else "(no output)",
                    tool_call_id=getattr(msg, "tool_call_id", ""),
                    name=getattr(msg, "name", ""),
                )
        sanitized.append(msg)

    # Ensure every AI tool_call has a matching ToolMessage response
    final_window: list = []
    i = 0
    while i < len(sanitized):
        msg = sanitized[i]
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            expected_ids = {tc["id"] for tc in msg.tool_calls if "id" in tc}
            # Collect following ToolMessages
            j = i + 1
            found_ids = set()
            while j < len(sanitized) and isinstance(sanitized[j], ToolMessage):
                tid = getattr(sanitized[j], "tool_call_id", "")
                found_ids.add(tid)
                j += 1
            if expected_ids and not found_ids:
                # No tool responses at all → strip tool_calls, keep text content only
                text = extract_text(getattr(msg, "content", ""))
                if text.strip():
                    final_window.append(AIMessage(content=text))
                # Skip this AI message entirely if no text content
                i = j
                continue
            # Keep the AI message and its tool responses
            final_window.append(msg)
            for k in range(i + 1, j):
                final_window.append(sanitized[k])
            i = j
            continue
        elif isinstance(msg, ToolMessage):
            # Orphaned ToolMessage — check if previous message has matching tool_call
            if final_window and isinstance(final_window[-1], AIMessage):
                tc_ids = {tc["id"] for tc in getattr(final_window[-1], "tool_calls", []) if "id" in tc}
                if getattr(msg, "tool_call_id", "") in tc_ids:
                    final_window.append(msg)
                    i += 1
                    continue
            # No matching AI message → skip orphan
            i += 1
            continue
        else:
            final_window.append(msg)
        i += 1

    # Ensure window starts with HumanMessage (Gemini requires user turn first)
    while final_window and not isinstance(final_window[0], HumanMessage):
        final_window.pop(0)

    window = final_window

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

    # Log full prompt assembly
    logger.info("🤖 [Agent] speaker=%s platform=%s msgs=%d tools=%d", current_speaker, platform, len(rebuilt), len(ALL_TOOLS))
    for i, msg in enumerate(rebuilt):
        tag = type(msg).__name__
        raw = extract_text(msg.content)
        preview = raw[:200].replace("\n", " ")
        logger.debug("  [%d] %s: %s%s", i, tag, preview, "…" if len(raw) > 200 else "")

    response = llm_with_tools.invoke(rebuilt)
    logger.info("🤖 [Agent] Response: %s", extract_text(response.content)[:150])
    return {"messages": [response]}
