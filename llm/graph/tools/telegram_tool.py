import os
import sys
from pathlib import Path
from langchain_core.tools import tool
from dotenv import load_dotenv

# Add repo root to path to allow importing from integrations
current_dir = Path(__file__).resolve().parent
repo_root = current_dir.parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from integrations.telegram.send_telegram import send_message as send_telegram_api

# Load env variables
load_dotenv(repo_root / ".env")

@tool
def send_telegram_message(message: str, chat_id: str = None):
    """Send a message via Telegram. Uses default chat_id if not provided."""
    token = os.getenv("TELEGRAM_API_TOKEN")
    if not token:
        return "Error: TELEGRAM_API_TOKEN not found in environment variables."
        
    target_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not target_chat_id:
        return "Error: No chat_id provided and TELEGRAM_CHAT_ID not found in environment."

    try:
        send_telegram_api(
            token=token,
            chat_id=target_chat_id,
            message=message,
            parse_mode=None,
            disable_preview=False
        )
        return "Message sent successfully to Telegram."
    except Exception as e:
        return f"Failed to send Telegram message: {str(e)}"
