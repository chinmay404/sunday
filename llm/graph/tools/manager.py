from .search import get_search
from .time_tools import get_time_tools
from .reminders.weakup_tools import create_reminder, list_reminders, cancel_reminder
from .whatsapp import add_to_whitelist, get_whitelist, send_whatsapp_message, lookup_contact
from .telegram_tool import send_telegram_message

def get_all_tools():
    tools = [get_search]
    tools.extend(get_time_tools())
    tools.extend([create_reminder, list_reminders, cancel_reminder])
    tools.extend([add_to_whitelist, get_whitelist, send_whatsapp_message, lookup_contact])
    tools.append(send_telegram_message)
    return tools
