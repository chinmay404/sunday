# Sunday AI - WhatsApp Integration

This project connects your WhatsApp account to the Sunday LLM backend.

## Architecture
- **Node.js (WhatsApp Client)**: Handles WhatsApp messages using `whatsapp-web.js`. Checks whitelists and forwards commands.
- **Python (LLM Backend)**: Runs a FastAPI server that processes messages using the LangGraph agent (`llm/graph/graph.py`).

## Setup

### 1. Python Environment (LLM Backend)
Make sure you have Python installed.

1. Install Python dependencies:
   ```bash
   pip install -r requirement.txt
   ```
2. Start the API server:
   ```bash
   python llm/api.py
   ```
   *The server runs on http://localhost:8000*

### 2. Node.js Environment (WhatsApp Client)
Make sure you have Node.js installed.

1. Install Node dependencies:
   ```bash
   npm install
   ```
2. Start the WhatsApp bot:
   ```bash
   node index.js
   ```
3. **First Time Only**: Scan the QR code that appears in the terminal with your WhatsApp (Linked Devices).
   *The session will be saved in `.wwebjs_auth/` so you don't need to scan again.*
4. Status endpoint:
   - `GET http://localhost:3000/status` shows readiness and the latest QR (ASCII) if login is required.
   - When the Python API server starts, it checks `/status` and sends a Telegram notification if login is needed.
5. Headless / Raspberry Pi:
   - Install Chromium and set `CHROME_PATH=/usr/bin/chromium` (or your chromium path).
   - The bot runs headless with `--no-sandbox` by default.

## Features & Controls

The bot only replies to **whitelisted** users (and you, the owner).

### Owner Commands (Send to yourself)
- `!whitelist add <ID>`: Add a user to the whitelist.
  - Example: `!whitelist add 1234567890@c.us`
- `!whitelist remove <ID>`: Remove a user.
- `!whitelist list`: Show all allowed users.
- `!ping`: Check if the bot is running.

### User Commands (Anyone)
- `!id`: Reveals the user's WhatsApp ID (sender must send this so you can add them to the whitelist).

## Debugging
- If the bot doesn't reply, check if the Python server is running.
- Logs are printed to the terminal for both processes.
