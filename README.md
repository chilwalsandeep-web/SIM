# Classroom Companion

> An AI-agent-powered Telegram bot that mediates between Teachers and Students for assignment management. Built for the SIM Engineering Interview Assignment.

---

## What It Does

Classroom Companion lets teachers assign work in plain English via Telegram, tracks student progress intelligently, sends smart reminders, and surfaces everything in clean web dashboards — all powered by a multi-agent LLM system.

**Teacher:** types `"Assign Riya a 500-word essay on photosynthesis, due in 3 days"` → bot parses, assigns, notifies student, tracks progress, prompts for feedback on submission.

**Student:** receives assignment, replies with progress updates in natural language, submits text/file/photo/voice, receives formatted feedback.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Telegram (Polling)                           │
└───────────────────────────┬─────────────────────────────────────┘
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
   intent_router     teacher_agent     student_agent
           │                │                │
           └────────────────┼────────────────┘
                            │
             ┌──────────────┼──────────────┐
             │                             │
    reminder_agent                    summariser
             │
    services/reminder_service (APScheduler — every 30 min)
                            │
             ┌──────────────┴──────────────┐
             │                             │
  assignment_service              transcription (Whisper)
             │
        db/session.py
             │
        PostgreSQL (8 tables)
             │
        api/routes.py (FastAPI — Web UI)
```

---

## Agent Design

| Agent | File | Responsibility |
|---|---|---|
| **IntentRouter** | `agents/intent_router.py` | Classifies every incoming message into a structured intent |
| **TeacherAgent** | `agents/teacher_agent.py` | Parses NL assignment instructions, formats teacher feedback |
| **StudentAgent** | `agents/student_agent.py` | Interprets progress messages, detects submission intent |
| **ReminderAgent** | `agents/reminder_agent.py` | Decides when/how to nudge based on activity + deadline |
| **Summariser** | `agents/summariser.py` | Generates teacher-facing progress summaries on request |

All agents extend `BaseAgent` in `agents/base.py` which wraps the LLM call. The provider is fully swappable via `LLM_PROVIDER` in `.env`.

---

## Prompt Strategy

- Every agent has a strict system prompt with typed output contracts
- Agents returning structured data output JSON only — no prose, no markdown
- JSON responses are stripped of markdown backticks before parsing (defensive safety net)
- Every LLM call is wrapped in try/except with a sensible fallback
- All agent inputs/outputs logged to `agent_logs` table for full auditability
- Reminder tone scales: `gentle → regular → urgent → final` based on deadline proximity and last activity

---

## Database Schema

| Table | Purpose |
|---|---|
| `users` | Teachers and students (role field differentiates) |
| `invite_codes` | Teacher-generated codes for student onboarding |
| `teacher_students` | Teacher to Student relationship |
| `assignments` | All assignments with status tracking |
| `progress_updates` | Every student progress message, LLM-interpreted |
| `submissions` | Final submissions (text, file, photo, voice) |
| `feedback` | Teacher feedback on submissions |
| `reminders` | Log of every reminder sent |
| `agent_logs` | Full audit trail of every LLM call |

---

## Setup

### Prerequisites
- Python 3.11.9
- PostgreSQL 16
- Telegram bot token (from @BotFather)
- Anthropic API key (from console.anthropic.com)

### 1. Clone and install

```bash
git clone https://github.com/chilwalsandeep-web/SIM.git
cd SIM
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install psycopg2-binary --only-binary=:all:
```

### 2. Configure environment

```bash
copy .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/classroom_companion
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_anthropic_api_key
LOG_LEVEL=INFO
```

> If your PostgreSQL password contains @ encode it as %40 in the URL

### 3. Create the database

```bash
psql -U postgres
CREATE DATABASE classroom_companion;
\q
```

### 4. Run the Telegram bot

```bash
python -m bot.main
```

### 5. Run the Web UI (separate terminal)

```bash
uvicorn api.routes:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Find your Telegram ID

```bash
python -c "
from db.session import db_session
from db.models import User
with db_session() as db:
    users = db.query(User).all()
    for u in users:
        print(f'{u.role}: {u.full_name} — telegram_id={u.telegram_id}')
"
```

### 7. Open the dashboards

```
Teacher UI:  http://localhost:8000/teacher/{your_telegram_id}
Student UI:  http://localhost:8000/student/{student_telegram_id}
API Docs:    http://localhost:8000/docs
```

---

## User Flows

### Teacher
1. `/register` — register as teacher
2. `/invite` — get invite code, share with student
3. Type naturally: "Assign Riya a 500-word essay on photosynthesis, due in 3 days"
4. Receive automatic progress updates from students
5. When student submits, give feedback naturally: "Great work! Expand the conclusion."
6. View all students and statuses on the Teacher Web UI

### Student
1. `/join ABC12345` — link to teacher's class
2. Receive assignment with clear deadline
3. Reply naturally: "done 2 paragraphs", "stuck on intro", "completed!"
4. Send file, photo, or voice note to submit
5. Receive teacher feedback in a friendly conversational format
6. View assignments, statuses and feedback on the Student Web UI

---

## Swapping the LLM Provider

```env
# Anthropic Claude (default)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Switch to OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

---

## Known Limitations

- Student name matching uses simple substring matching — fuzzy matching would be more robust
- No multi-tenant auth — invite codes are the only access control
- Voice transcription requires an OpenAI API key (Whisper) even when using Anthropic as the main LLM
- Reminder scheduler checks every 30 minutes — not real-time
- No rate limiting on LLM calls
- Web UI is read-only — no inline actions from the dashboard

---

## What I'd Build Next

- Fuzzy student name matching using rapidfuzz
- Multi-assignment context awareness when students have multiple active assignments
- Unit and eval tests for each agent using recorded LLM responses
- Deployment on Railway (bot) + Render (web UI)
- Real-time UI updates via WebSockets instead of 30-second polling
- WhatsApp transport layer using the same agent/service code

---

## What I'd Refactor

- Move all hardcoded bot messages and prompt templates to a central prompts.py
- Add Alembic migrations for proper schema versioning instead of create_all
- Add dependency injection instead of module-level singletons
- Improve error handling with a global Telegram error handler

---

## Where AI Helped vs Hurt

**Helped:**
- Scaffolding all 5 agent system prompts with correct JSON contracts rapidly
- Catching the SQLAlchemy DetachedInstanceError pattern across all handlers
- Building the FastAPI + HTML dashboard with polished dark theme quickly

**Hurt:**
- LLM returns JSON wrapped in markdown backticks despite being told not to — required defensive stripping in every agent
- Some SQLAlchemy session management patterns were subtly wrong and needed manual debugging

---

## AI Tools Used

- Claude (Anthropic) — primary coding assistant for scaffolding, debugging, prompt design
- claude-sonnet-4-5 — LLM powering all 5 agents in production

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Bot Framework | python-telegram-bot 20.7 |
| Web Framework | FastAPI + Uvicorn |
| Database | PostgreSQL + SQLAlchemy 2.0 |
| LLM | Claude Sonnet 4.5 (swappable) |
| Scheduler | APScheduler 3.10 |
| Config | pydantic-settings |
