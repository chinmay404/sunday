import os
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage

from llm.graph.states.state import ChatState
from llm.graph.model.llm import get_llm
from llm.graph.habits.action_log import append_action_log, utc_now_iso, touch_last_seen


ACTION_LOG_ENABLE = os.getenv("ACTION_LOG_ENABLE", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


class ActionItem(BaseModel):
    action_type: str = Field(description="Type/category of action (e.g., project_work, study, admin)")
    description: str = Field(description="Short, specific description of the action")
    commitment_made: bool = Field(description="True if user committed to a future action")
    sentiment: str = Field(description="Overall tone of the action (e.g., focused, neutral, stressed)")
    status: Optional[str] = Field(default=None, description="Status if explicitly stated")


class ActionExtraction(BaseModel):
    has_action: bool = Field(description="True only if a concrete action is present")
    action: Optional[ActionItem] = Field(default=None, description="Extracted action details")


def _last_human_message(state: ChatState) -> Optional[str]:
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, list):
                content = " ".join(str(part) for part in content)
            return str(content).strip() if content else None
    return None


def action_analyzer_node(state: ChatState):
    if not ACTION_LOG_ENABLE or state.get("skip_action_log"):
        return {}

    text = _last_human_message(state)
    if not text or len(text) < 20:
        return {}

    thread_id = state.get("thread_id") or "default"
    user_name = state.get("user_name")
    try:
        touch_last_seen(thread_id)
    except Exception as exc:
        print(f"Failed to update last_seen: {exc}")

    llm = get_llm(temperature=0.2)
    if not llm:
        return {}

    structured_llm = llm.with_structured_output(ActionExtraction)
    system_prompt = (
        "You are an Action Extractor. Read the user's single message and decide if it "
        "contains a concrete action, habit, or completed task. Do NOT infer actions. "
        "If there is no concrete action, set has_action=false.\n\n"
        "Guidelines:\n"
        "- Log completed actions (e.g., 'finished my German vocab')\n"
        "- Log in-progress or planned actions only if explicitly stated\n"
        "- Ignore questions, vague desires, and small talk\n"
        "- Keep description short and specific\n"
    )

    try:
        result = structured_llm.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=text)]
        )
    except Exception as exc:
        print(f"Error in action analyzer: {exc}")
        return {}

    if not result.has_action or not result.action:
        return {}

    action = result.action
    description = action.description.strip()
    if len(description) > 240:
        description = description[:240].rstrip() + "..."

    try:
        append_action_log(
            timestamp=utc_now_iso(),
            action_type=action.action_type.strip() or "other",
            description=description,
            commitment_made=bool(action.commitment_made),
            sentiment=action.sentiment,
            status=action.status,
            source_text=text,
            thread_id=thread_id,
            user_name=user_name,
        )
    except Exception as exc:
        print(f"Failed to append action log: {exc}")

    return {}
