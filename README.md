# 🎓 Classroom Companion

> An AI-agent-powered Telegram bot that mediates between Teachers and Students for assignment management.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Telegram (Polling)                        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    bot/main.py (entry point)
                             │
              ┌──────────────┴──────────────┐
              │                             │
   bot/handlers/teacher.py      bot/handlers/student.py
              │                             │
              └──────────────┬──────────────┘
                             │
                    bot/middleware.py
                    (role-based routing)
                             │
            ┌────────────────┼────────────────┐
            │                │                │
    agents/             agents/          agents/
    intent_router    teacher_agent    student_agent
            │                │                │
            └────────────────┼────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │                             │
     agents/reminder_agent      agents/summariser
              │
     services/reminder_service (APScheduler)
                             │
              ┌──────────────┴──────────────┐
              │                             │
   services/assignment_service    services/transcription
              │
         db/session.py
              │
         PostgreSQL
```

## Agent Design

| Agent | Responsibility |
|---|---|
| **IntentRouter** | Classifies every incoming message into a structured intent |
| **TeacherAgent** | Parses NL assignment instructions, formats feedback |
| **StudentAgent** | Interprets progress updates, generates acknowledgements |
| **ReminderAgent** | Decides when/how to nudge students based on activity + deadline |
| **Summariser** | Generates teacher-facing progress summaries |

All agents extend `BaseAgent` which wraps the LLM call. The LLM provider is
fully swappable via `LLM_PROVIDER` in `.env` (supports `anthropic` and `openai`).

## Prompt Strategy

- Each agent has a **typed system prompt** with strict output contracts (JSON where structured data is needed)
- Graceful fallbacks: every LLM call is wrapped in try/except with sensible defaults
- Agent decisions are logged to `agent_logs` table for auditability
- Reminder messages are context-aware: tone scales from `gentle → regular → urgent → final`

## Setup

### 1. Prerequisites
- Python 3.11+
- PostgreSQL running locally
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Anthropic API key

### 2. Install

```bash
git clone <repo>
cd classroom-companion
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your keys
```

### 4. Database

```bash
# Create the database
createdb classroom_companion

# Tables are auto-created on first run (SQLAlchemy create_all)
# For migrations (optional):
alembic init db/migrations
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

### 5. Run

```bash
python -m bot.main
```

---

## User Flows

### Teacher
1. `/register` → registered as teacher
2. `/invite` → get a code → share with student
3. Type naturally: _"Assign Riya a 500-word essay on photosynthesis, due in 3 days"_
4. Receive student progress updates automatically
5. When student submits, type feedback naturally

### Student
1. `/join ABC12345` → linked to teacher
2. Receive assignment via bot
3. Reply naturally: _"done 2 paragraphs"_, _"stuck on the intro"_, _"completed!"_
4. Send file/photo/voice to submit
5. Receive teacher feedback

---

## Known Limitations

- `/assignments` summary matching for specific students is naive (first match by name)
- No multi-tenant auth — invite codes are the only access control
- Voice transcription requires an OpenAI API key (Whisper)
- Reminder scheduler runs every 30 min — not real-time
- No rate limiting on LLM calls

## What I'd Build Next

- Full Teacher/Student web UI (FastAPI + React)
- Smarter student name resolution using fuzzy matching
- Multi-assignment context awareness (bot knows which assignment a message refers to)
- Unit tests for each agent using recorded LLM responses
- Deployment on Railway with environment secrets
