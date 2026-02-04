import sys
import os
from pathlib import Path
current_dir = Path(__file__).resolve().parent
root_dir = current_dir.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from llm.graph.graph import create_graph
from integrations.telegram.run_bot import start_polling
from langchain_core.messages import HumanMessage

def main():
    graph = create_graph()
    telegram_thread, telegram_stop_event = start_polling(graph=graph)
    print(graph)
    print("Sunday Agent Initialized. Type 'quit' to exit.")
    chat_history = []
    
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["quit", "exit"]:
            break
            
        # Persisted history is managed by the graph checkpointer (Postgres).
        # We only send the latest user turn; LangGraph will retrieve prior turns.
        initial_state = {"messages": [HumanMessage(content=user_input)]}
        
        print("Sunday is thinking...")
        config = {"configurable": {"thread_id": "default"}}
        # Invoke with config so the checkpointer loads/saves this thread
        result = graph.invoke(initial_state, config=config)
        
        last_message = result["messages"][-1]
        if hasattr(last_message, 'content') and last_message.content:
             print(f"Sunday: {last_message.content}")

    if telegram_stop_event:
        telegram_stop_event.set()
        if telegram_thread:
            telegram_thread.join(timeout=5)

if __name__ == "__main__":
    main()
