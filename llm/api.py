import sys
from pathlib import Path
import os
from dotenv import load_dotenv
import requests

# Add root directory to sys.path to ensure imports work correctly
current_dir = Path(__file__).resolve().parent
root_dir = current_dir.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

load_dotenv(root_dir / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from llm.graph.graph import create_graph
from langchain_core.messages import HumanMessage, AIMessage
import uvicorn
from contextlib import asynccontextmanager
from llm.graph.habits.scheduler import start_habit_scheduler
from integrations.telegram.send_telegram import send_message as send_telegram_api

WHATSAPP_STATUS_URL = os.getenv("WHATSAPP_STATUS_URL", "http://localhost:3000/status")


def _notify_whatsapp_status():
    token = os.getenv("TELEGRAM_API_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Skipping WhatsApp status notify: TELEGRAM_API_TOKEN or TELEGRAM_CHAT_ID missing.")
        return
    try:
        response = requests.get(WHATSAPP_STATUS_URL, timeout=3)
        if response.status_code != 200:
            print(f"WhatsApp status check failed: {response.status_code}")
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
        print(f"WhatsApp status check error: {exc}")
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
        print("WhatsApp status: ready.")
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
        print(f"Failed to send WhatsApp status to Telegram: {exc}")

# Global variables
graph = None
telegram_thread = None
telegram_stop_event = None
scheduler_thread = None
scheduler_stop_event = None
habit_thread = None
habit_stop_event = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the graph on startup
    global graph, telegram_thread, telegram_stop_event, scheduler_thread, scheduler_stop_event, habit_thread, habit_stop_event
    print("Initialize Graph...")
    graph = create_graph()
    try:
        from integrations.telegram.run_bot import start_polling
        telegram_thread, telegram_stop_event = start_polling(graph=graph)
    except Exception as e:
        print(f"Telegram bot not started: {e}")
    try:
        from llm.graph.tools.reminders.scheduler import start_scheduler
        scheduler_thread, scheduler_stop_event = start_scheduler(graph=graph)
    except Exception as e:
        print(f"Reminder scheduler not started: {e}")
    try:
        habit_thread, habit_stop_event = start_habit_scheduler()
    except Exception as e:
        print(f"Habit analyzer not started: {e}")
    try:
        _notify_whatsapp_status()
    except Exception as e:
        print(f"WhatsApp status notify failed: {e}")
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
    print("Shutting down...")

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

class ChatResponse(BaseModel):
    response: str

class TelegramNotifyRequest(BaseModel):
    message: str
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

    config = {"configurable": {"thread_id": request.thread_id}}
    
    print(f"Processing message for thread {request.thread_id}...")
    try:
        # Invoke the graph synchronously
        result = graph.invoke(initial_state, config=config)
        
        last_ai = next(
            (m for m in reversed(result.get("messages", [])) if isinstance(m, AIMessage)),
            None,
        )
        content = last_ai.content if last_ai and hasattr(last_ai, "content") else ""
        
        return ChatResponse(response=content)
    except Exception as e:
        print(f"Error processing message: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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

if __name__ == "__main__":
    uvicorn.run("llm.api:app", host="0.0.0.0", port=8000, reload=True)
