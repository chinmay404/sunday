from .search import get_search
from .time_tools import get_time_tools
from .whatsapp import add_to_whitelist, get_whitelist, send_whatsapp_message, lookup_contact

def get_all_tools():
    tools = [get_search]
    tools.extend(get_time_tools())
    tools.extend([add_to_whitelist, get_whitelist, send_whatsapp_message, lookup_contact])
    return tools
