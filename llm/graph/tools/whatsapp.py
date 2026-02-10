import json
import os
from datetime import datetime, timezone
import requests
from typing import Optional
from langchain_core.tools import tool
from difflib import get_close_matches

# Paths — use file-relative path so it works regardless of CWD
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WA_DIR = os.path.join(os.path.dirname(_REPO_ROOT), 'integrations', 'whatsapp')
WHITELIST_PATH = os.path.join(_WA_DIR, 'whitelist.json')
CONTACTS_PATH = os.path.join(_WA_DIR, 'contacts.json')
SETTINGS_PATH = os.path.join(_WA_DIR, 'settings.json')
PENDING_PATH = os.path.join(_WA_DIR, 'pending.json')
WHATSAPP_API_URL = "http://localhost:3000/send"

DEFAULT_SETTINGS = {
    "busyMode": False,
    "autoSend": False,
    "busyReplyTemplate": "I'm tied up right now but will get back to you soon.",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _load_json(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        _save_json(path, default)
    except Exception:
        return default
    return default


def _load_settings() -> dict:
    settings = _load_json(SETTINGS_PATH, DEFAULT_SETTINGS)
    merged = DEFAULT_SETTINGS.copy()
    if isinstance(settings, dict):
        merged.update(settings)
    return merged


def _save_settings(settings: dict) -> None:
    _save_json(SETTINGS_PATH, settings)


def _load_pending() -> list:
    pending = _load_json(PENDING_PATH, [])
    return pending if isinstance(pending, list) else []


def _save_pending(pending: list) -> None:
    _save_json(PENDING_PATH, pending)

def load_contacts():
    if os.path.exists(CONTACTS_PATH):
        try:
            with open(CONTACTS_PATH, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

@tool
def lookup_contact(name: str):
    """Look up a contact's phone number by name. Supports fuzzy matching."""
    contacts = load_contacts()
    if not contacts:
        return "No contacts found. Please import contacts.vcf using manage_whatsapp.py"
    
    clean_name = name.lower().strip()
    if clean_name in contacts:
        return f"Found {contacts[clean_name]['name']}: {contacts[clean_name]['number']}"
    
    # Fuzzy match
    matches = get_close_matches(clean_name, contacts.keys(), n=3, cutoff=0.6)
    if matches:
        suggestions = [f"{contacts[m]['name']} ({contacts[m]['number']})" for m in matches]
        return f"Did you mean: {', '.join(suggestions)}?"
    
    return "Contact not found."

@tool
def whatsapp_get_settings():
    """Get WhatsApp busy/auto-reply settings."""
    settings = _load_settings()
    busy = "on" if settings.get("busyMode") else "off"
    mode = "auto-send" if settings.get("autoSend") else "approval"
    template = settings.get("busyReplyTemplate", "")
    return f"WhatsApp busy mode: {busy}. Reply mode: {mode}. Template: {template}"

@tool
def whatsapp_set_busy_mode(enabled: Optional[bool] = None, auto_send: Optional[bool] = None, reply_template: Optional[str] = None):
    """Get or toggle WhatsApp busy mode settings. Call with no args to just read current settings.
    Toggle busy mode, set auto-send or approval mode, and customize reply template."""
    settings = _load_settings()
    if enabled is not None:
        settings["busyMode"] = bool(enabled)
    if auto_send is not None:
        settings["autoSend"] = bool(auto_send)
    if reply_template:
        settings["busyReplyTemplate"] = reply_template.strip()
    if enabled is not None or auto_send is not None or reply_template:
        _save_settings(settings)
    busy = "on" if settings.get("busyMode") else "off"
    mode = "auto-send" if settings.get("autoSend") else "approval"
    template = settings.get("busyReplyTemplate", "")
    return f"WhatsApp busy mode: {busy}. Reply mode: {mode}. Template: {template}"

@tool
def whatsapp_list_pending(limit: int = 10):
    """List pending WhatsApp replies awaiting approval."""
    pending = [p for p in _load_pending() if p.get("status") == "pending"]
    if not pending:
        return "No pending WhatsApp replies."
    lines = [f"Pending replies: {len(pending)}"]
    for item in pending[:max(1, min(limit, 50))]:
        lines.append(
            f"- {item.get('id')} | {item.get('from_name')} ({item.get('from_id')}) | "
            f"{item.get('message')} | draft: {item.get('draft')}"
        )
    return "\n".join(lines)

def _find_pending(pending_id: str):
    pending = _load_pending()
    for idx, item in enumerate(pending):
        if item.get("id") == pending_id:
            return pending, idx, item
    return pending, None, None

@tool
def whatsapp_approve_pending(pending_id: str):
    """Send the stored draft for a pending WhatsApp reply."""
    pending, idx, item = _find_pending(pending_id)
    if item is None or idx is None:
        return f"Pending reply not found: {pending_id}"
    if item.get("status") != "pending":
        return f"Pending reply already {item.get('status')}."
    target = item.get("from_id")
    draft = item.get("draft") or ""
    if not target or not draft:
        return "Pending reply is missing target or draft."
    result = send_whatsapp_message(target=target, message=draft)
    item["status"] = "sent"
    item["sent_at"] = _now_iso()
    item["sent_message"] = draft
    pending[idx] = item
    _save_pending(pending)
    return f"Approved and sent. {result}"

@tool
def whatsapp_reply_pending(pending_id: str, message: str):
    """Send a custom reply for a pending WhatsApp message."""
    pending, idx, item = _find_pending(pending_id)
    if item is None or idx is None:
        return f"Pending reply not found: {pending_id}"
    if item.get("status") != "pending":
        return f"Pending reply already {item.get('status')}."
    target = item.get("from_id")
    if not target:
        return "Pending reply is missing target."
    result = send_whatsapp_message(target=target, message=message)
    item["status"] = "sent"
    item["sent_at"] = _now_iso()
    item["sent_message"] = message
    pending[idx] = item
    _save_pending(pending)
    return f"Sent custom reply. {result}"

@tool
def whatsapp_reject_pending(pending_id: str):
    """Reject a pending WhatsApp reply without sending."""
    pending, idx, item = _find_pending(pending_id)
    if item is None or idx is None:
        return f"Pending reply not found: {pending_id}"
    if item.get("status") != "pending":
        return f"Pending reply already {item.get('status')}."
    item["status"] = "rejected"
    item["rejected_at"] = _now_iso()
    pending[idx] = item
    _save_pending(pending)
    return f"Rejected pending reply {pending_id}."

@tool
def add_to_whitelist(phone_number: str):
    """Add a phone number to the WhatsApp whitelist. Accepts raw digits or JID format."""
    if not phone_number.endswith("@c.us") and "@" not in phone_number:
        phone_number = f"{phone_number}@c.us"
    
    try:
        if os.path.exists(WHITELIST_PATH):
            with open(WHITELIST_PATH, 'r') as f:
                whitelist = json.load(f)
        else:
            whitelist = []
            
        if phone_number not in whitelist:
            whitelist.append(phone_number)
            with open(WHITELIST_PATH, 'w') as f:
                json.dump(whitelist, f, indent=2)
            return f"Added {phone_number} to whitelist."
        else:
            return f"{phone_number} is already in the whitelist."
    except Exception as e:
        return f"Error updating whitelist: {e}"

@tool
def get_whitelist():
    """Returns the list of whitelisted WhatsApp numbers."""
    try:
        if os.path.exists(WHITELIST_PATH):
            with open(WHITELIST_PATH, 'r') as f:
                whitelist = json.load(f)
            return str(whitelist)
        return "Whitelist is empty."
    except Exception as e:
        return f"Error reading whitelist: {e}"

@tool
def send_whatsapp_message(target: str, message: str):
    """Send a WhatsApp message. Target can be a phone number or contact name."""
    # 1. Try to resolve contact name if it doesn't look like a number
    final_number = target
    if "@" in target:
        final_number = target
    elif not target.replace('+', '').isdigit():
        contacts = load_contacts()
        clean_name = target.lower().strip()
        # Exact match
        if clean_name in contacts:
            final_number = contacts[clean_name]['number']
        else:
            # Fuzzy match
            matches = get_close_matches(clean_name, contacts.keys(), n=1, cutoff=0.7)
            if matches:
                final_number = contacts[matches[0]]['number']
            else:
                return f"Could not find contact named '{target}'. Please provide a valid phone number."

    # 2. Add suffix if needed
    if "@" not in final_number:
        # Assuming standard number, append suffix if it looks like one
        # The node API handles raw numbers well usually, but being explicit helps
        pass

    try:
        payload = {"number": final_number, "message": message}
        response = requests.post(WHATSAPP_API_URL, json=payload)
        if response.status_code == 200:
            return f"Message sent successfully to {target} ({final_number})."
        else:
            return f"Failed to send message: {response.text}"
    except Exception as e:
        # If connection fails, it often means the Node app isn't running
        return f"Error sending message (Is the WhatsApp bot running?): {e}"
