"""
bot/main.py
Entry point for the Classroom Companion Telegram bot.
Sets up handlers, starts polling, and launches the reminder scheduler.
"""

import asyncio
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import settings
from db.session import create_tables, check_connection
from bot.middleware import route_message
from bot.handlers.teacher import (
    cmd_start_teacher,
    cmd_register_teacher,
    cmd_invite,
    cmd_students,
    cmd_assignments,
)
from bot.handlers.student import (
    cmd_start_student,
    cmd_join,
    cmd_assignments_student,
    handle_student_document,
    handle_student_photo,
    handle_student_voice,
)
from services.reminder_service import ReminderService

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Send message helper (used by ReminderService)
# ---------------------------------------------------------------------------

_app: Application | None = None


async def send_message(telegram_id: int, text: str) -> None:
    """Callback provided to ReminderService to send Telegram messages."""
    if _app:
        await _app.bot.send_message(chat_id=telegram_id, text=text)


# ---------------------------------------------------------------------------
# /start  — smart router: checks role and delegates
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context) -> None:
    from db.session import db_session
    from services.assignment_service import get_user_by_telegram_id

    user = update.effective_user
    with db_session() as db:
        db_user = get_user_by_telegram_id(db, user.id)
        role = db_user.role if db_user else None

    if role == "teacher":
        await cmd_start_teacher(update, context)
    elif role == "student":
        await cmd_start_student(update, context)
    else:
        await update.message.reply_text(
            f"👋 Welcome to *Classroom Companion*, {user.first_name}!\n\n"
            "I help teachers and students manage assignments through Telegram.\n\n"
            "Are you a *teacher*? → /register\n"
            "Are you a *student*? → /join <invite_code>",
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# Build the application
# ---------------------------------------------------------------------------

def build_app() -> Application:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Universal commands
    app.add_handler(CommandHandler("start", cmd_start))

    # Teacher commands
    app.add_handler(CommandHandler("register", cmd_register_teacher))
    app.add_handler(CommandHandler("invite", cmd_invite))
    app.add_handler(CommandHandler("students", cmd_students))

    # Shared /assignments command — routes by role
    async def cmd_assignments_router(update: Update, context) -> None:
        from db.session import db_session
        from services.assignment_service import get_user_by_telegram_id
        with db_session() as db:
            user = get_user_by_telegram_id(db, update.effective_user.id)
        if user and user.is_teacher:
            await cmd_assignments(update, context)
        else:
            await cmd_assignments_student(update, context)

    app.add_handler(CommandHandler("assignments", cmd_assignments_router))

    # Student commands
    app.add_handler(CommandHandler("join", cmd_join))

    # Media handlers (students submitting work)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_student_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_student_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_student_voice))

    # Free-text messages → middleware router
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, route_message))

    return app


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _app

    logger.info("Starting Classroom Companion...")

    # Verify DB
    if not check_connection():
        logger.critical("Cannot connect to database. Check DATABASE_URL in .env")
        return

    # Run migrations / create tables
    create_tables()

    # Build bot
    _app = build_app()

    # Start reminder scheduler
    reminder_service = ReminderService(send_message_fn=send_message)
    reminder_service.start()

    logger.info("Bot is running (polling mode)...")
    _app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
