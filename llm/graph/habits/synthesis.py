from typing import List, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from llm.graph.model.llm import get_llm
from llm.graph.habits.action_log import (
    get_recent_actions,
    get_habit_profile,
    save_habit_profile,
    set_last_synthesis_run,
)


class HabitSynthesis(BaseModel):
    updated_habit_profile: str = Field(description="Updated habit profile summary")
    habit_shift: str = Field(description="Concise description of changes detected")
    missed_actions: List[str] = Field(description="List of notable missing actions")
    high_priority_reminder: Optional[str] = Field(description="One high-priority reminder or null")


DEFAULT_PROFILE = "No habit profile yet."


def _format_actions(actions: List[dict]) -> str:
    if not actions:
        return "No actions logged."
    lines = []
    for a in actions:
        status = a.get("status") or "unspecified"
        sentiment = a.get("sentiment") or "unspecified"
        commitment = "true" if a.get("commitment_made") else "false"
        lines.append(
            f"{a.get('timestamp')} | {status} | {a.get('action_type')} | {a.get('description')} | "
            f"sentiment={sentiment} | commitment={commitment}"
        )
    return "\n".join(lines)


def run_habit_synthesis(
    *,
    thread_id: str,
    user_name: Optional[str] = None,
    lookback_hours: float = 24 * 7,
    max_actions: int = 200,
) -> Optional[HabitSynthesis]:
    actions = get_recent_actions(
        thread_id=thread_id, since_hours=lookback_hours, limit=max_actions
    )
    profile = get_habit_profile(thread_id) or DEFAULT_PROFILE
    formatted_actions = _format_actions(actions)

    llm = get_llm(temperature=0.2)
    if not llm:
        return None

    structured_llm = llm.with_structured_output(HabitSynthesis)
    system_prompt = (
        "You are the Habit Analyzer. Your job is to update a user's habit profile based ONLY on "
        "the provided action logs. Do not invent actions. If the logs are sparse, keep the profile "
        "stable and say so. Identify shifts in timing or frequency, and list any notable missing "
        "actions implied by the existing profile or repeated past actions.\n\n"
        "Return JSON only with:\n"
        "- updated_habit_profile: concise updated profile\n"
        "- habit_shift: short sentence describing the change or 'No change'\n"
        "- missed_actions: list of missing habits/tasks (empty list if none)\n"
        "- high_priority_reminder: one short reminder sentence or null\n"
    )

    user_label = user_name or "User"
    prompt = (
        f"Old Habit Profile:\n{profile}\n\n"
        f"Recent Action Logs:\n{formatted_actions}\n\n"
        f"User: {user_label}"
    )

    try:
        result = structured_llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ]
        )
    except Exception as exc:
        print(f"Error running habit synthesis: {exc}")
        return None

    save_habit_profile(thread_id, result.updated_habit_profile)
    set_last_synthesis_run(thread_id)
    return result
