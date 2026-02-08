#!/usr/bin/env python3
import time
import os
import sys
import threading
import requests
from pathlib import Path
from typing import Optional, Tuple

# Add repo root to path BEFORE internal imports
current_dir = Path(__file__).resolve().parent
repo_root = current_dir.parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage
from llm.graph.tools.reminders.weakup_tools import set_current_chat_id, reset_current_chat_id
from llm.graph.nodes.map_user import map_user
from llm.services.location_service import (
    LocationService,
    set_current_location_user_id,
    reset_current_location_user_id,
)

try:
    from llm.graph.graph import create_graph
    from integrations.telegram.send_telegram import send_message
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

location_service = LocationService()

TELEGRAM_MAX_MESSAGE_LENGTH = 4096


def load_env():
    load_dotenv(repo_root / ".env")


def _send_typing(token: str, chat_id) -> None:
    """Send 'typing...' indicator so the user knows we're working."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except Exception:
        pass  # non-critical


def _split_message(text: str, limit: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a long message into chunks that fit Telegram's 4096-char limit."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to split at last newline within limit
        split_at = text.rfind("\n", 0, limit)
        if split_at < limit // 2:
            # No good newline — split at last space
            split_at = text.rfind(" ", 0, limit)
        if split_at < limit // 4:
            # No good split point — hard split
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks

def get_updates(token, offset=None, timeout=2):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {
        "timeout": timeout,
        "allowed_updates": '["message","edited_message"]'
    }
    if offset:
        params["offset"] = offset
    
    try:
        response = requests.get(url, params=params, timeout=40)
        return response.json()
    except Exception as e:
        print(f"Error fetching updates: {e}")
        return None

def process_message(token, graph, message_data):
    chat_id = message_data["chat"]["id"]
    user_id = message_data["from"]["id"]
    username = message_data["from"].get("username", "Unknown")
    text = message_data.get("text", "") or message_data.get("caption", "")

    # Location updates can come as new messages or edited messages (live location ticks).
    if "location" in message_data:
        loc = message_data.get("location", {})
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        if lat is not None and lng is not None:
            print(f"Location update from {username} ({chat_id}): {lat}, {lng}")
            location_service.update_location(
                user_id=str(user_id),
                latitude=lat,
                longitude=lng,
                chat_id=str(chat_id),
            )
            # For live location edits, avoid triggering the LLM every movement.
            if "edit_date" in message_data and not text:
                return
            # For pure location share without text/caption, save silently.
            if not text:
                return
    
    if not text:
        return

    print(f"Received message from {username} ({chat_id}): {text}")

    token_ctx = None
    location_user_ctx = None
    mapped_user_name = map_user(str(user_id))

    # Show typing indicator immediately so user knows we're processing
    _send_typing(token, chat_id)

    # Invoke the graph
    try:
        token_ctx = set_current_chat_id(str(chat_id))
        location_user_ctx = set_current_location_user_id(str(user_id))
        inputs = {
            "messages": [HumanMessage(content=text)],
            "platform": "telegram",
            "thread_id": str(chat_id),
            "user_name": str(mapped_user_name),
            "user_id": str(user_id),
        }
        
        config = {"configurable": {"thread_id": str(chat_id)}}
        
        result = graph.invoke(inputs, config=config)
        
        messages = result.get("messages", [])
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if last_ai and last_ai.content:
            # Split long messages to respect Telegram's 4096-char limit
            for chunk in _split_message(last_ai.content):
                send_message(token, chat_id, chunk, None, False)
            print(f"Sent response to {username}: {last_ai.content[:120]}...")
            
    except Exception as e:
        error_msg = f"Error processing message: {e}"
        print(error_msg)
        try:
            send_message(token, chat_id, "Something broke on my end. Give me a sec and try again.", None, False)
        except Exception:
            pass
    finally:
        if token_ctx is not None:
            try:
                reset_current_chat_id(token_ctx)
            except Exception:
                pass
        if location_user_ctx is not None:
            try:
                reset_current_location_user_id(location_user_ctx)
            except Exception:
                pass

def _should_enable_bot() -> bool:
    flag = os.getenv("TELEGRAM_BOT_ENABLE", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def run_polling(graph=None, token: Optional[str] = None, stop_event: Optional[threading.Event] = None):
    load_env()
    if not _should_enable_bot():
        print("Telegram bot disabled via TELEGRAM_BOT_ENABLE.")
        return

    token = token or os.getenv("TELEGRAM_API_TOKEN")
    if not token:
        print("Error: TELEGRAM_API_TOKEN not found.")
        return

    if graph is None:
        print("Initializing Graph with PostgresSaver...")
        graph = create_graph()

    print("Telegram Bot Started. Polling for updates...")

    offset = None
    
    while True:
        if stop_event and stop_event.is_set():
            print("Telegram bot stopping...")
            break

        updates = get_updates(token, offset)
        
        if updates and updates.get("ok"):
            for update in updates["result"]:
                update_id = update["update_id"]
                offset = update_id + 1
                
                if "message" in update:
                    process_message(token, graph, update["message"])
                if "edited_message" in update:
                    edited = update["edited_message"]
                    if "location" in edited:
                        process_message(token, graph, edited)
        
        time.sleep(1)

def start_polling(graph=None, token: Optional[str] = None) -> Tuple[Optional[threading.Thread], Optional[threading.Event]]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_polling,
        kwargs={"graph": graph, "token": token, "stop_event": stop_event},
        daemon=True,
    )
    thread.start()
    return thread, stop_event


def main():
    run_polling()


if __name__ == "__main__":
    main()
