from typing import TypedDict, Annotated, List, Dict, Optional, Literal
from langgraph.graph.message import add_messages
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing_extensions import NotRequired
from langchain_core.messages import AnyMessage

def keep_last_message(left, right):
    """Reducer that keeps only the most recent message."""
    combined = add_messages(left, right)
    if isinstance(combined, list):
        return combined[-1:]
    return combined


class ActionDecided(BaseModel):
    internal_feeling: str = Field(
        description="How Sunday genuinely feels about this situation right now")
    what_matters: str = Field(
        description="What Sunday's intuition says is most important in this moment")
    suggested_vibe: str = Field(
        description="The emotional energy that feels right for this conversation")
    conversation_direction: str = Field(
        description="What Sunday naturally wants to bring up or focus on")
    how_to_show_up: str = Field(
        description="How Sunday should come across in this moment (as a friend would)")


class ChatState(TypedDict):
    messages:  Annotated[list[AnyMessage],add_messages]
    Action_decided: NotRequired[Optional[ActionDecided]]
    memory_context: NotRequired[Optional[str]]
    system_prompt: NotRequired[str]
    platform: NotRequired[str]


