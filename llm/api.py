import sys
from pathlib import Path
import os

# Add root directory to sys.path to ensure imports work correctly
current_dir = Path(__file__).resolve().parent
root_dir = current_dir.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from llm.graph.graph import create_graph
from langchain_core.messages import HumanMessage
import uvicorn
from contextlib import asynccontextmanager

# Global variable for the graph
graph = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the graph on startup
    global graph
    print("Initialize Graph...")
    graph = create_graph()
    yield
    # Clean up if necessary
    print("Shutting down...")

app = FastAPI(lifespan=lifespan, title="Sunday Chat API")

class ChatRequest(BaseModel):
    message: str
    username: str
    thread_id: str = "default"
    system_prompt: str = None
    platform: str = "unknown"

class ChatResponse(BaseModel):
    response: str

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

    config = {"configurable": {"thread_id": request.thread_id}}
    
    print(f"Processing message for thread {request.thread_id}...")
    try:
        # Invoke the graph synchronously
        result = graph.invoke(initial_state, config=config)
        
        last_message = result["messages"][-1]
        content = last_message.content if hasattr(last_message, 'content') else str(last_message)
        
        return ChatResponse(response=content)
    except Exception as e:
        print(f"Error processing message: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("llm.api:app", host="0.0.0.0", port=8000, reload=True)
