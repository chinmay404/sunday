from .search import get_search
from .time_tools import get_time_tools
from .reminders.weakup_tools import (
    create_reminder,
    list_reminders,
    cancel_reminder,
    schedule_self_wakeup,
)
from .whatsapp import (
    add_to_whitelist,
    get_whitelist,
    send_whatsapp_message,
    lookup_contact,
    whatsapp_get_settings,
    whatsapp_set_busy_mode,
    whatsapp_list_pending,
    whatsapp_approve_pending,
    whatsapp_reply_pending,
    whatsapp_reject_pending,
)
from .telegram_tool import send_telegram_message
from .location_tools import (
    location_current_status,
    location_remember_place,
    location_list_places,
    location_forget_place,
    location_pattern_report,
)
from .notion_tool import (
    notion_create_note,
    notion_append_content,
    notion_update_page_properties,
    notion_get_page,
    notion_get_page_content,
    notion_query_database,
    notion_search,
)
from llm.graph.tools.user_mapping import add_user_in_known_user, map_user, add_thing_to_remeber


def get_all_tools():
    tools = [get_search]
    tools.extend(get_time_tools())
    tools.extend([create_reminder, list_reminders, cancel_reminder, schedule_self_wakeup])
    tools.extend([add_to_whitelist, get_whitelist,
                 send_whatsapp_message, lookup_contact])
    tools.extend(
        [
            whatsapp_get_settings,
            whatsapp_set_busy_mode,
            whatsapp_list_pending,
            whatsapp_approve_pending,
            whatsapp_reply_pending,
            whatsapp_reject_pending,
        ]
    )
    tools.extend(
        [
            location_current_status,
            location_remember_place,
            location_list_places,
            location_forget_place,
            location_pattern_report,
        ]
    )
    tools.append(send_telegram_message)
    tools.extend(
        [
            notion_create_note,
            notion_append_content,
            notion_update_page_properties,
            notion_get_page,
            notion_get_page_content,
            notion_query_database,
            notion_search,
        ]
    )
    tools.extend([add_user_in_known_user, map_user, add_thing_to_remeber])
    return tools

ALL_TOOLS = get_all_tools()
