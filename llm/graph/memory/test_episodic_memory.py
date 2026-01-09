import sys
import os
from pathlib import Path
import time

# Add project root to path so we can import modules
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from llm.graph.memory.episodic_memeory import EpisodicMemory

def test_episodic_memory():
    print("Initializing Episodic Memory...")
    try:
        memory = EpisodicMemory()
    except Exception as e:
        print(f"Failed to initialize memory. Ensure Postgres is running and .env is set correctly.\nError: {e}")
        return

    # 1. Add Memories
    print("\n--- Adding Memories ---")
    memories = [
        ("User likes to code in Python.", 0.8, "user", ["coding", "preference"]),
        ("User had toast for breakfast.", 0.2, "user", ["food", "trivial"]),
        ("Sunday suggested using Postgres.", 0.6, "assistant", ["project", "sunday"]),
        ("The weather is sunny today.", 0.1, "system", ["weather", "trivial"]),
        ("User prefers Postgres over vector-only DBs.", 0.7, "user", ["coding", "preference", "database"])
    ]
    
    for content, importance, role, tags in memories:
        print(f"Adding: '{content}' (Imp: {importance}, Role: {role})")
        memory.add_memory(content, importance, role=role, tags=tags)
        
    # 2. Retrieve Memories
    print("\n--- Retrieving Memories ---")
    query = "What tech stack does the user like?"
    print(f"Query: '{query}'")
    
    results = memory.retrieve_memories(query, k=3)
    
    for i, res in enumerate(results):
        print(f"{i+1}. {res['content']} (Score: {res['score']:.4f})")
        print(f"   Debug: {res['debug']}")

    # 3. Test Decay/Cleanup
    # Note: This won't delete anything immediately unless we force old dates or high decay, 
    # but we can run it to ensure no errors.
    print("\n--- Running Cleanup ---")
    deleted = memory.cleanup_memories(threshold=0.001) # Very low threshold to likely not delete fresh memories
    print(f"Deleted {deleted} memories (expected 0 or few for fresh memories).")

if __name__ == "__main__":
    test_episodic_memory()
