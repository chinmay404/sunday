# Sunday AI Project

Sunday is an AI project with a Python backend (LLM), a Next.js frontend, and various integrations (WhatsApp).

## Project Structure

- **`llm/`**: Python backend using LangChain/LangGraph.
- **`frontend/`**: Next.js web application.
- **`integrations/whatsapp/`**: WhatsApp bot integration.

## Setup & Running

### 1. Python Backend (Required for text processing)
The backend runs the AI agent.
```bash
pip install -r requirement.txt
python llm/api.py
```
*Server runs on http://localhost:8000*

### 2. Integrations

#### WhatsApp Bot
Access Sunday via WhatsApp.
[View WhatsApp Instructions](integrations/whatsapp/README.md)
```bash
cd integrations/whatsapp
npm install
node index.js
```

### 3. Frontend
Web interface for the agent.
```bash
cd frontend
npm install
npm run dev
```
