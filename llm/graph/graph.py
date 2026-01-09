from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from llm.graph.states.state import ChatState
from llm.graph.nodes.agent import agent_node
from llm.graph.nodes.context import context_gathering_node
from llm.graph.nodes.memory_processor import memory_processing_node
from llm.graph.tools.manager import get_all_tools
from llm.graph.postgres_saver import PostgresSaver

def create_graph(checkpointer=None):
    workflow = StateGraph(ChatState)
    
    # Add nodes
    workflow.add_node("context_gathering", context_gathering_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("memory_processor", memory_processing_node)
    
    tools = get_all_tools()
    tool_node = ToolNode(tools)
    workflow.add_node("tools", tool_node)
    
    # Add edges
    # Start with context gathering to populate memory_context
    workflow.set_entry_point("context_gathering")
    
    # Then go to agent
    workflow.add_edge("context_gathering", "agent")
    
    workflow.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",
            END: "memory_processor"
        }
    )
    
    workflow.add_edge("tools", "agent")
    workflow.add_edge("memory_processor", END)
    
    if checkpointer is None:
        checkpointer = PostgresSaver()
    return workflow.compile(checkpointer=checkpointer)
