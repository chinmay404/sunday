from .search import get_search
from .time_tools import get_time_tools
from .reminders.weakup_tools import (
    create_reminder,
    list_reminders,
    cancel_reminder,
    schedule_self_wakeup,
)
from .whatsapp import (
    send_whatsapp_message,
    lookup_contact,
    whatsapp_set_busy_mode,
    whatsapp_list_pending,
    whatsapp_approve_pending,
    whatsapp_reply_pending,
    whatsapp_reject_pending,
    add_to_whitelist,
    get_whitelist,
)
from .telegram_tool import send_telegram_message
from .location_tools import (
    location_current_status,
    location_remember_place,
    location_list_places,
    location_forget_place,
    location_current_address,
)
from .notion_tool import (
    notion_create_note,
    notion_append_content,
    notion_get_page_content,
    notion_query_database,
    notion_search,
)
from .utility_tools import search_memory, forget_memory, read_webpage
from .people_tools import (
    add_person_relation,
    update_person_details,
    save_preference,
    get_person_info,
)


def get_all_tools():
    # Core: search + time (calendar, todoist)
    tools = [get_search]
    tools.extend(get_time_tools())

    # Reminders & wake-ups
    tools.extend([create_reminder, list_reminders, cancel_reminder, schedule_self_wakeup])

    # WhatsApp (send, contacts, busy mode, pending queue, whitelist)
    tools.extend([send_whatsapp_message, lookup_contact,
                  whatsapp_set_busy_mode, whatsapp_list_pending, whatsapp_approve_pending,
                  whatsapp_reply_pending, whatsapp_reject_pending,
                  add_to_whitelist, get_whitelist])

    # Location (status, save/list/delete places, address)
    tools.extend([location_current_status, location_remember_place, location_list_places,
                  location_forget_place, location_current_address])

    # Telegram
    tools.append(send_telegram_message)

    # Notion (create, append, read, query, search)
    tools.extend([notion_create_note, notion_append_content,
                  notion_get_page_content, notion_query_database, notion_search])

    # Memory (search, forget, web)
    tools.extend([search_memory, forget_memory, read_webpage])

    # People & preferences
    tools.extend([add_person_relation, update_person_details, save_preference, get_person_info])

    return tools

ALL_TOOLS = get_all_tools()
