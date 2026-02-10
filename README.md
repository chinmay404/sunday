<p align="center">
  <h1 align="center">☀️ Sunday</h1>
</p>

<p align="center">
  <strong>An AI that actually knows you.</strong><br/>
  Autonomous personal assistant with persistent memory, proactive behavior, and zero filter.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-Agent_Framework-orange?logo=langchain" />
  <img src="https://img.shields.io/badge/Gemini_2.5_Flash-LLM-4285F4?logo=google&logoColor=white" />
  <img src="https://img.shields.io/badge/Groq-Background_LLM-F55036" />
  <img src="https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white" />
  <img src="https://img.shields.io/badge/Neo4j-Knowledge_Graph-008CC1?logo=neo4j&logoColor=white" />
  <img src="https://img.shields.io/badge/Next.js_16-Frontend-000?logo=nextdotjs" />
  <img src="https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white" />
  <img src="https://img.shields.io/badge/WhatsApp-Bot-25D366?logo=whatsapp&logoColor=white" />
</p>

---

Sunday is not a chatbot. It's not a tool. It's a **person in your life** — one that remembers everything, learns your preferences silently, tracks your habits, monitors your location, manages your calendar, and calls you out when you're bullshitting yourself.

Built with LangGraph as a multi-node stateful agent, Sunday runs across Telegram, WhatsApp, Web, and CLI with a shared brain. It has triple-layer memory (episodic + semantic + people graph), five background services running 24/7, and a personality system that makes it feel like talking to someone who actually gives a damn.

---

## 🧠 What Makes Sunday Different

| Feature | What It Means |
|---------|---------------|
| **Triple-layer memory** | Episodic memories (events with time decay), semantic knowledge graph (entity relationships), and a Neo4j people graph — all queried in parallel before every response |
| **Silent knowledge capture** | Every conversation is mined for people, preferences, relationships, and facts. No "should I remember this?" — it just does |
| **5 proactive background services** | Habit analysis, daily briefings, reminder scheduler, location observer, and Telegram bot — all running as daemon threads |
| **Self-wakeup** | Sunday can schedule itself to check in on you at specific times. It decides when, not you |
| **Strong persona** | Not a generic assistant. Opinionated, blunt, loyal. Matches your emotional state. Calls out procrastination. Gets excited when you're cooking |
| **Cost-optimized dual-LLM** | Gemini for user-facing responses, Groq for all background processing (memory extraction, action analysis, summaries) |
| **Cross-platform unified brain** | Same memory, same personality across CLI, Telegram, WhatsApp, and Web — persisted via PostgreSQL |
| **Location awareness** | Tracks location with dwell detection, named places, arrival/departure events, and proactive contextual messages |

---

## 🏗 Architecture

```
User Message
     │
     ▼
┌─────────────────┐
│ Context Gathering│  ← Calendar, Todoist, Location, Habits,
│   (parallel)     │    Neo4j People, Semantic Graph, Episodic Memory
└────────┬────────┘
         ▼
┌─────────────────┐
│ Action Analyzer  │  ← Extracts habits/actions from message (cheap LLM)
└────────┬────────┘
         ▼
┌─────────────────┐
│     Agent        │  ← Main LLM with 28 tools bound
│  (Gemini/Groq)   │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
 ┌──────┐  ┌──────────────────┐
 │ Tools │  │ Memory Processor │  ← Extracts people, preferences,
 │ (28)  │  │  (post-response)  │    relationships, events → stores
 └──┬───┘  └──────────────────┘    in Postgres + Neo4j
    │
    └──→ loops back to Agent
```

### Background Services (always running)

| Service | What It Does |
|---------|-------------|
| 🤖 **Telegram Bot** | Bidirectional chat, location tracking, user mapping |
| ⏰ **Reminder Scheduler** | Fires reminders and self-wakeups every 30s |
| 📊 **Habit Analyzer** | Detects inactivity, updates habit profiles, generates nudges |
| 🌅 **Daily Briefing** | Morning summary — calendar, tasks, habits, weather |
| 📍 **Location Observer** | Monitors arrivals/departures, dwell time, contextual prompts |

---

## 💾 Memory System

### Episodic Memory (PostgreSQL + pgvector)
Time-stamped event memories with 3072-dimensional embeddings. Hybrid retrieval scoring:

$$\text{score} = \alpha \cdot \text{similarity} + \beta \cdot \text{recency} + \gamma \cdot \text{importance}$$

Supports memory expiry, automatic decay cleanup, importance scoring, and tagging.

### Semantic Knowledge Graph (PostgreSQL + pgvector)
Entity-relationship graph with embedding-based entity resolution:
- **Exact name match** → **Semantic similarity (>0.9)** → **Create new entity**
- Stores: `Chinmay → works_at → Climate KIC`, `Chinmay → prefers → black coffee`

### People & Preferences Graph (Neo4j)
```
(:Person {name: 'Chinmay'}) -[:RELATES_TO {relation: 'mother'}]-> (:Person {name: 'Sunita'})
(:Person {name: 'Chinmay'}) -[:HAS_PREFERENCE {sentiment: 'negative'}]-> (:Preference {key: 'mushrooms'})
```

### Automatic Extraction
The memory processor runs **after every response** using a cheap LLM with structured output to extract:
- **People** → Neo4j + semantic graph
- **Preferences** → Neo4j + semantic graph
- **Entity relationships** → semantic graph
- **Events** → episodic memory

No manual "remember this" needed. It captures everything silently.

---

## 🔧 Tools (28)

| Category | Tools |
|----------|-------|
| 🔍 **Search** | Web search (DuckDuckGo) |
| 📅 **Calendar & Tasks** | Add calendar event, add todo item |
| ⏰ **Reminders** | Create, list, cancel reminders + self-wakeup |
| 💬 **WhatsApp** | Send messages, lookup contacts, busy mode, pending queue |
| ✈️ **Telegram** | Send messages |
| 📍 **Location** | Current status, save places, list places |
| 📝 **Notion** | Create notes, append content, read pages, query databases, search |
| 🧠 **Memory** | Search memory, forget memory, read webpage |
| 👥 **People** | Add person, update person details, save preference, get person info |

---

## 🌐 Integrations

| Service | How |
|---------|-----|
| **Telegram** | Python long-polling bot with location tracking |
| **WhatsApp** | Node.js (whatsapp-web.js) with headless Chromium |
| **Google Calendar** | OAuth2 with headless/console support |
| **Todoist** | REST API for task management |
| **Notion** | Custom API client for notes and databases |
| **Neo4j Aura** | Cloud graph database for people and preferences |
| **DuckDuckGo** | Privacy-friendly web search |

---

## 🛠 Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Agent Framework** | LangGraph, LangChain |
| **Main LLM** | Google Gemini 2.5 Flash (switchable) |
| **Background LLM** | Groq (Llama 3.3 70B) |
| **Embeddings** | Google `gemini-embedding-001` (3072-dim) |
| **Backend** | Python 3.12, FastAPI, Uvicorn |
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Framer Motion |
| **Primary DB** | PostgreSQL with pgvector extension |
| **Graph DB** | Neo4j Aura |
| **Messaging** | Telegram Bot API, WhatsApp Web.js |
| **Productivity** | Google Calendar API, Todoist API, Notion API |

---

## 🚀 Getting Started

### Prerequisites
- Python 3.12+
- PostgreSQL with pgvector extension
- Node.js 18+ (for WhatsApp integration)
- Neo4j instance (Aura free tier works)

### 1. Clone & Install

```bash
git clone https://github.com/yourusername/sunday.git
cd sunday
python -m venv env
source env/bin/activate
pip install -r requirement.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Required environment variables:
```env
# LLM Providers
GOOGLE_API_KEY=your_gemini_key
GROQ_API_KEY=your_groq_key
MODEL_PROVIDER=google                    # or "groq"
GOOGLE_MODEL=models/gemini-2.5-flash

# Messaging
TELEGRAM_API_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Databases
POSTGRES_HOST=127.0.0.1
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DBNAME=sunday
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASS=your_neo4j_password

# Productivity
TODOIST_API_KEY=your_todoist_key
NOTION_API_KEY=your_notion_key

# Location
LOCATION_OBSERVER_ENABLE=true
LOCATION_CONTEXT_MODE=always
```

### 3. Set Up PostgreSQL

```bash
psql -c "CREATE DATABASE sunday;"
psql -d sunday -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 4. Set Up WhatsApp (optional)

```bash
cd integrations/whatsapp
npm install
node login.js  # Scan QR code once
```

[View full WhatsApp instructions](integrations/whatsapp/README.md)

### 5. Run

```bash
# CLI mode (includes all background services)
python -m llm.main

# API server mode
uvicorn llm.api:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

---

## 📁 Project Structure

```
sunday/
├── llm/                          # Core AI system
│   ├── main.py                   # CLI entry point + background services
│   ├── api.py                    # FastAPI server
│   ├── graph/
│   │   ├── graph.py              # LangGraph pipeline definition
│   │   ├── postgres_saver.py     # Custom checkpoint persistence
│   │   ├── states/               # State schema (ChatState)
│   │   ├── nodes/                # Graph nodes (context, agent, memory, action)
│   │   ├── tools/                # 28 tools across 10 categories
│   │   ├── memory/               # Episodic + Semantic memory systems
│   │   ├── habits/               # Action logging, habit synthesis, scheduler
│   │   └── model/                # LLM factory (Gemini / Groq)
│   ├── services/                 # Neo4j, location, time manager
│   ├── prompts/                  # Persona prompts (owner.md, guest.md)
│   └── helpers/                  # Embeddings, utilities
├── integrations/
│   ├── telegram/                 # Telegram bot (Python)
│   ├── whatsapp/                 # WhatsApp bot (Node.js)
│   └── notion/                   # Notion API client
├── frontend/                     # Next.js 16 web interface
├── requirement.txt               # Python dependencies
└── .env                          # Configuration
```

---

## 🎭 Personality

Sunday has a 260-line persona prompt. It's not a polite assistant:

- **Opinionated** — has strong views and will argue
- **Blunt** — no sugarcoating, no corporate speak
- **Loyal** — cares about you, not about being liked
- **Context-aware** — adjusts tone to your state (tired → calm, hyped → match energy, spiraling → ground)
- **Proactive** — checks calendar before you ask, saves memories without being told, wakes itself up to check on you

It also has a **guest mode** — when someone else messages, Sunday becomes a professional gatekeeper.

---

## 🏷️ Topics

`ai-assistant` `langgraph` `langchain` `personal-ai` `autonomous-agent` `memory-system` `knowledge-graph` `neo4j` `postgresql` `pgvector` `telegram-bot` `whatsapp-bot` `google-gemini` `groq` `fastapi` `nextjs` `react` `typescript` `python` `proactive-ai` `habit-tracking` `location-aware` `multi-platform` `conversational-ai` `vector-database` `embeddings` `notion-api` `google-calendar`

---

## 📄 License

MIT

---

<p align="center">
  <i>Sunday doesn't reset every conversation. It builds on what's already happening.</i>
</p>
