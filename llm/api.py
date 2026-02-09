import logging
import sys
from pathlib import Path
import os
from dotenv import load_dotenv
import requests
import base64
import subprocess
import shlex

# Add root directory to sys.path to ensure imports work correctly
current_dir = Path(__file__).resolve().parent
root_dir = current_dir.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from llm.logging_config import setup_logging
setup_logging()

logger = logging.getLogger(__name__)

load_dotenv(root_dir / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from llm.graph.graph import create_graph
from langchain_core.messages import HumanMessage, AIMessage
from llm.graph.nodes.helpers import extract_text
import uvicorn
from contextlib import asynccontextmanager
from llm.graph.habits.scheduler import start_habit_scheduler
from llm.graph.tools.reminders.daily_briefing import start_daily_briefing_scheduler
from llm.graph.tools.reminders.location_observer import start_location_observer_scheduler
from llm.services.location_service import set_current_location_user_id, reset_current_location_user_id
from integrations.telegram.send_telegram import send_message as send_telegram_api

WHATSAPP_STATUS_URL = os.getenv("WHATSAPP_STATUS_URL", "http://localhost:3000/status")
WHATSAPP_BOT_AUTOSTART = os.getenv("WHATSAPP_BOT_AUTOSTART", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
WHATSAPP_BOT_CMD = os.getenv("WHATSAPP_BOT_CMD", "node index.js")


def _whatsapp_status():
    try:
        response = requests.get(WHATSAPP_STATUS_URL, timeout=2)
        if response.status_code != 200:
            return None
        return response.json()
    except Exception:
        return None


def _start_whatsapp_bot():
    global whatsapp_process
    if not WHATSAPP_BOT_AUTOSTART:
        logger.info("WhatsApp bot autostart disabled.")
        return

    existing = _whatsapp_status()
    if existing is not None:
        logger.info("WhatsApp server already running.")
        return

    bot_dir = root_dir / "integrations" / "whatsapp"
    try:
        cmd = shlex.split(WHATSAPP_BOT_CMD)
        whatsapp_process = subprocess.Popen(
            cmd,
            cwd=str(bot_dir),
            env=os.environ.copy(),
        )
        logger.info("Started WhatsApp bot with PID %s", whatsapp_process.pid)
    except Exception as exc:
        logger.error("Failed to start WhatsApp bot: %s", exc)


def _notify_whatsapp_status():
    token = os.getenv("TELEGRAM_API_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.info("Skipping WhatsApp status notify: TELEGRAM_API_TOKEN or TELEGRAM_CHAT_ID missing.")
        return
    try:
        response = requests.get(WHATSAPP_STATUS_URL, timeout=3)
        if response.status_code != 200:
            logger.warning("WhatsApp status check failed: %s", response.status_code)
            send_telegram_api(
                token=token,
                chat_id=chat_id,
                message="WhatsApp status check failed. Is the WhatsApp server running?",
                parse_mode=None,
                disable_preview=True,
            )
            return
        data = response.json()
    except Exception as exc:
        logger.error("WhatsApp status check error: %s", exc)
        try:
            send_telegram_api(
                token=token,
                chat_id=chat_id,
                message="WhatsApp status check failed. Start the WhatsApp server to generate a QR code.",
                parse_mode=None,
                disable_preview=True,
            )
        except Exception:
            pass
        return

    if data.get("ready"):
        logger.info("WhatsApp status: ready.")
        return

    qr = data.get("qr")
    message = "WhatsApp not logged in. Scan the QR to link the device."
    if qr:
        message = f"{message}\n\n{qr}"
    else:
        message = f"{message}\n\nStart the WhatsApp server to generate a QR code."

    try:
        send_telegram_api(
            token=token,
            chat_id=chat_id,
            message=message,
            parse_mode=None,
            disable_preview=True,
        )
    except Exception as exc:
        logger.error("Failed to send WhatsApp status to Telegram: %s", exc)

# Global variables
graph = None
telegram_thread = None
telegram_stop_event = None
scheduler_thread = None
scheduler_stop_event = None
habit_thread = None
habit_stop_event = None
daily_briefing_thread = None
daily_briefing_stop_event = None
location_observer_thread = None
location_observer_stop_event = None
whatsapp_process = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the graph on startup
    global graph, telegram_thread, telegram_stop_event, scheduler_thread, scheduler_stop_event, habit_thread, habit_stop_event, daily_briefing_thread, daily_briefing_stop_event, location_observer_thread, location_observer_stop_event, whatsapp_process
    logger.info("Initializing Graph...")
    graph = create_graph()
    try:
        from integrations.telegram.run_bot import start_polling
        telegram_thread, telegram_stop_event = start_polling(graph=graph)
    except Exception as e:
        logger.error("Telegram bot not started: %s", e)
    try:
        from llm.graph.tools.reminders.scheduler import start_scheduler
        scheduler_thread, scheduler_stop_event = start_scheduler(graph=graph)
    except Exception as e:
        logger.error("Reminder scheduler not started: %s", e)
    try:
        habit_thread, habit_stop_event = start_habit_scheduler()
    except Exception as e:
        logger.error("Habit analyzer not started: %s", e)
    try:
        daily_briefing_thread, daily_briefing_stop_event = start_daily_briefing_scheduler(graph=graph)
    except Exception as e:
        logger.error("Daily briefing scheduler not started: %s", e)
    try:
        location_observer_thread, location_observer_stop_event = start_location_observer_scheduler(graph=graph)
    except Exception as e:
        logger.error("Location observer scheduler not started: %s", e)
    try:
        _start_whatsapp_bot()
    except Exception as e:
        logger.error("WhatsApp bot autostart failed: %s", e)
    try:
        _notify_whatsapp_status()
    except Exception as e:
        logger.error("WhatsApp status notify failed: %s", e)
    yield
    # Clean up if necessary
    if telegram_stop_event:
        telegram_stop_event.set()
        if telegram_thread:
            telegram_thread.join(timeout=5)
    if scheduler_stop_event:
        scheduler_stop_event.set()
        if scheduler_thread:
            scheduler_thread.join(timeout=5)
    if habit_stop_event:
        habit_stop_event.set()
        if habit_thread:
            habit_thread.join(timeout=5)
    if daily_briefing_stop_event:
        daily_briefing_stop_event.set()
        if daily_briefing_thread:
            daily_briefing_thread.join(timeout=5)
    if location_observer_stop_event:
        location_observer_stop_event.set()
        if location_observer_thread:
            location_observer_thread.join(timeout=5)
    if whatsapp_process:
        try:
            whatsapp_process.terminate()
        except Exception:
            pass
    logger.info("Shutting down...")

app = FastAPI(lifespan=lifespan, title="Sunday Chat API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

class ChatRequest(BaseModel):
    message: str
    username: str
    thread_id: str = "default"
    system_prompt: str = None
    platform: str = "unknown"
    user_id : str

class ChatResponse(BaseModel):
    response: str

class TelegramNotifyRequest(BaseModel):
    message: str
    chat_id: str | None = None

class TelegramNotifyPhotoRequest(BaseModel):
    image_base64: str
    caption: str | None = None
    chat_id: str | None = None

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    Chat endpoint.
    Identified as synchronous (def) so FastAPI runs it in a threadpool to avoid blocking the event loop
    since the graph execution likely involves synchronous DB calls.
    """
    global graph
    if graph is None:
        raise HTTPException(status_code=500, detail="Graph not initialized")

    initial_state = {"messages": [HumanMessage(content=request.message, name=request.username)]}
    if request.system_prompt:
        initial_state["system_prompt"] = request.system_prompt
    if request.platform:
        initial_state["platform"] = request.platform
    initial_state["thread_id"] = request.thread_id
    initial_state["user_name"] = request.username
    initial_state["user_id"] = request.user_id

    config = {"configurable": {"thread_id": request.thread_id}}
    
    logger.info("💬 [API] thread=%s user=%s platform=%s", request.thread_id, request.username, request.platform)
    location_user_ctx = None
    try:
        if request.user_id:
            location_user_ctx = set_current_location_user_id(str(request.user_id))
        # Invoke the graph synchronously
        result = graph.invoke(initial_state, config=config)
        
        last_ai = next(
            (m for m in reversed(result.get("messages", [])) if isinstance(m, AIMessage)),
            None,
        )
        content = extract_text(last_ai.content) if last_ai and hasattr(last_ai, "content") else ""
        
        return ChatResponse(response=content)
    except Exception as e:
        logger.error("Error processing message: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if location_user_ctx is not None:
            try:
                reset_current_location_user_id(location_user_ctx)
            except Exception:
                pass

@app.post("/telegram/notify")
def telegram_notify(request: TelegramNotifyRequest):
    token = os.getenv("TELEGRAM_API_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="Missing TELEGRAM_API_TOKEN")
    target_chat_id = request.chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not target_chat_id:
        raise HTTPException(status_code=400, detail="Missing chat_id and TELEGRAM_CHAT_ID")
    try:
        send_telegram_api(
            token=token,
            chat_id=target_chat_id,
            message=request.message,
            parse_mode=None,
            disable_preview=True,
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/telegram/notify-photo")
def telegram_notify_photo(request: TelegramNotifyPhotoRequest):
    token = os.getenv("TELEGRAM_API_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="Missing TELEGRAM_API_TOKEN")
    target_chat_id = request.chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not target_chat_id:
        raise HTTPException(status_code=400, detail="Missing chat_id and TELEGRAM_CHAT_ID")
    data = request.image_base64.strip()
    if data.startswith("data:"):
        data = data.split(",", 1)[-1]
    try:
        image_bytes = base64.b64decode(data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image")
    try:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        files = {"photo": ("qr.png", image_bytes)}
        payload = {"chat_id": target_chat_id}
        if request.caption:
            payload["caption"] = request.caption
        resp = requests.post(url, data=payload, files=files, timeout=10)
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=resp.text)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("llm.api:app", host="0.0.0.0", port=8000, reload=True)
