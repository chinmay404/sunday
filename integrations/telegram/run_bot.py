#!/usr/bin/env python3
import time
import os
import sys
import threading
import requests
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage
from llm.graph.tools.reminders.weakup_tools import set_current_chat_id, reset_current_chat_id
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import Optional, Tuple

# Add repo root to path
current_dir = Path(__file__).resolve().parent
repo_root = current_dir.parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from llm.graph.graph import create_graph
    from integrations.telegram.send_telegram import send_message
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def load_env():
    load_dotenv(repo_root / ".env")

def get_updates(token, offset=None, timeout=2):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"timeout": timeout}
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
    text = message_data.get("text", "")
    user_id = message_data["from"]["id"]
    username = message_data["from"].get("username", "Unknown")
    
    if not text:
        return

    print(f"Received message from {username} ({chat_id}): {text}")

    token_ctx = None
    # Invoke the graph
    try:
        token_ctx = set_current_chat_id(str(chat_id))
        inputs = {
            "messages": [HumanMessage(content=text)],
            "platform": "telegram",
            "system_prompt": f"User is {username}. Respond concisely.", # Optional contextual info
        }
        
        # We use a thread_id based on chat_id to maintain conversation history per user
        config = {"configurable": {"thread_id": str(chat_id)}}
        
        # Invoke graph
        result = graph.invoke(inputs, config=config)
        
        # Extract response from the last AI message
        messages = result.get("messages", [])
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if last_ai:
            response_text = last_ai.content
            
            # Send response back to Telegram
            send_message(token, chat_id, response_text, None, False)
            print(f"Sent response to {username}: {response_text}")
            
    except Exception as e:
        error_msg = f"Error processing message: {e}"
        print(error_msg)
        # Optional: send error message to user
        # send_message(token, chat_id, "Sorry, I encountered an error processing your request.", None, False)
    finally:
        if token_ctx is not None:
            try:
                reset_current_chat_id(token_ctx)
            except Exception:
                pass

def _should_enable_bot() -> bool:
    flag = os.getenv("TELEGRAM_BOT_ENABLE", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _force_sqlite() -> bool:
    flag = os.getenv("TELEGRAM_FORCE_SQLITE", "true").strip().lower()
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

    if graph is None or _force_sqlite():
        print("Initializing Graph with SqliteSaver...")
        # Use SqliteSaver to avoid Postgres requirement
        db_path = repo_root / "sunday_checkpoints.sqlite"
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        graph = create_graph(checkpointer=checkpointer)

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
