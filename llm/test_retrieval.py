
from llm.graph.memory.semantic_memory import SemanticMemory

try:
    sm = SemanticMemory()
    query = "where do i work at"
    print(f"Query: '{query}'")
    
    # Test with default threshold (0.6 in class definition, but 0.5 in context.py)
    print("\n--- Testing Threshold 0.5 ---")
    facts = sm.retrieve_facts(query, k=5, threshold=0.5)
    for f in facts:
        print(f"Found: {f['content']} (Score: {f['score']})")
        
    if not facts:
        print("No facts found at 0.5")

    # Test with lower threshold
    print("\n--- Testing Threshold 0.1 ---")
    facts = sm.retrieve_facts(query, k=5, threshold=0.1)
    for f in facts:
        print(f"Found: {f['content']} (Score: {f['score']})")

except Exception as e:
    print(f"Error: {e}")
