import sys
import os
from pathlib import Path
current_dir = Path(__file__).resolve().parent
root_dir = current_dir.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from llm.graph.graph import create_graph
from integrations.telegram.run_bot import start_polling
from llm.graph.tools.reminders.scheduler import start_scheduler
from llm.graph.tools.reminders.daily_briefing import start_daily_briefing_scheduler
from llm.graph.tools.reminders.location_observer import start_location_observer_scheduler
from llm.graph.habits.scheduler import start_habit_scheduler
from langchain_core.messages import HumanMessage, AIMessage

def main():
    graph = create_graph()
    telegram_thread, telegram_stop_event = start_polling(graph=graph)
    scheduler_thread, scheduler_stop_event = start_scheduler(graph=graph)
    habit_thread, habit_stop_event = start_habit_scheduler()
    daily_briefing_thread, daily_briefing_stop_event = start_daily_briefing_scheduler(graph=graph)
    location_observer_thread, location_observer_stop_event = start_location_observer_scheduler(graph=graph)
    print(graph)
    print("Sunday Agent Initialized. Type 'quit' to exit.")
    chat_history = []
    
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["quit", "exit"]:
            break
            
        # Persisted history is managed by the graph checkpointer (Postgres).
        # We only send the latest user turn; LangGraph will retrieve prior turns.
        initial_state = {
            "messages": [HumanMessage(content=user_input)],
            "thread_id": "default",
            "user_name": "chinmay",
            "user_id":"7173566704",
            "platform": "cli",
        }
        
        print("Sunday is thinking...")
        config = {"configurable": {"thread_id": "default"}}
        # Invoke with config so the checkpointer loads/saves this thread
        result = graph.invoke(initial_state, config=config)
        
        last_ai = next(
            (m for m in reversed(result.get("messages", [])) if isinstance(m, AIMessage)),
            None,
        )
        if last_ai and last_ai.content:
             print(f"Sunday: {last_ai.content}")

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

if __name__ == "__main__":
    main()
