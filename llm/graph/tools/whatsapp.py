import json
import os
import requests
from langchain_core.tools import tool
from difflib import get_close_matches

# Paths
# Assuming we are running from root 'sunday/'
BASE_DIR = os.getcwd()
WHITELIST_PATH = os.path.join(BASE_DIR, 'integrations', 'whatsapp', 'whitelist.json')
CONTACTS_PATH = os.path.join(BASE_DIR, 'integrations', 'whatsapp', 'contacts.json')
WHATSAPP_API_URL = "http://localhost:3000/send"

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
    """
    Looks up a contact's phone number by name from the imported contacts list.
    """
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
def add_to_whitelist(phone_number: str):

    """
    Adds a phone number to the WhatsApp whitelist.
    The number should be in the format '1234567890@c.us' or just digits '1234567890'.
    """
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
    """
    Sends a WhatsApp message to a specific number or contact name.
    Input 'target' can be a phone number (e.g., '1234567890') or a Contact Name (e.g., 'Mom').
    If a name is provided, it tries to look it up in the contacts list.
    """
    # 1. Try to resolve contact name if it doesn't look like a number
    final_number = target
    if not target.replace('+', '').isdigit():
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
