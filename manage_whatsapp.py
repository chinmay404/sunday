import argparse
import os
import subprocess
import json
import sys

# Constants
WHATSAPP_DIR = os.path.join("integrations", "whatsapp")
CONTACTS_VCF = "contacts.vcf"
CONTACTS_JSON = os.path.join(WHATSAPP_DIR, "contacts.json")

def parse_contacts():
    """Parses contacts.vcf and saves to contacts.json"""
    if not os.path.exists(CONTACTS_VCF):
        print(f"Yellow: {CONTACTS_VCF} not found in root. Skipping contact import.")
        return

    # Check for vobject
    try:
        import vobject
    except ImportError:
        print("Installing vobject for VCF parsing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "vobject"])
        import vobject

    print(f"Parsing {CONTACTS_VCF}...")
    contacts = {}
    try:
        with open(CONTACTS_VCF, 'r', encoding='utf-8') as f:
            vcard_data = f.read()
            for vcard in vobject.readComponents(vcard_data):
                try:
                    name = vcard.fn.value
                    if hasattr(vcard, 'tel'):
                        # Get first phone number
                        tel = vcard.tel_list[0].value
                        # Clean number: remove spaces, -, (), +
                        number = str(tel).replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('+', '')
                        
                        # Save
                        contacts[name.lower()] = {"name": name, "number": number}
                except Exception:
                    continue
        
        with open(CONTACTS_JSON, 'w') as f:
            json.dump(contacts, f, indent=2)
        print(f"Success: Saved {len(contacts)} contacts to {CONTACTS_JSON}")
        
    except Exception as e:
        print(f"Error parsing VCF: {e}")

def main():
    parser = argparse.ArgumentParser(description="Sunday WhatsApp Setup & Manager")
    parser.add_argument("--setup", action="store_true", help="Configure and run WhatsApp bot")
    args = parser.parse_args()

    if args.setup:
        # 1. Dependency Check
        print("--- 1. Checking Node Dependencies ---")
        if not os.path.exists(os.path.join(WHATSAPP_DIR, "node_modules")):
            print("Installing npm packages...")
            subprocess.run(["npm", "install"], cwd=WHATSAPP_DIR, check=True)
        else:
            print("node_modules exists. Skipping install.")

        # 2. Contacts
        print("\n--- 2. Processing Contacts ---")
        parse_contacts()

        # 3. Auth Check & Run
        print("\n--- 3. Starting WhatsApp Bot ---")
        auth_path = os.path.join(WHATSAPP_DIR, ".wwebjs_auth")
        if os.path.exists(auth_path):
            print("Session found. Starting server in background (Ctrl+C to stop)...")
        else:
            print("Session NOT found. Preparing to generate QR code...")
            print("Please scan the QR code with your phone.")

        # Run the Node script
        try:
            subprocess.run(["node", "index.js"], cwd=WHATSAPP_DIR)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
