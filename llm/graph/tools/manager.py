from .search import get_search
from .time_tools import get_time_tools

def get_all_tools():
    tools = [get_search]
    tools.extend(get_time_tools())
    return tools
