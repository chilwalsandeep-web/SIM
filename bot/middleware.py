"""
bot/middleware.py
Middleware utilities: resolve user role and route to the right handler.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from db.session import db_session
from services.assignment_service import get_user_by_telegram_id

logger = logging.getLogger(__name__)


async def resolve_user_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """
    Returns the role ('teacher' | 'student') of the sender,
    or None if the user is not registered.
    """
    if not update.effective_user:
        return None
    with db_session() as db:
        user = get_user_by_telegram_id(db, update.effective_user.id)
        return user.role if user else None


async def route_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Central dispatcher for all free-text messages.
    Checks the sender's role and calls the appropriate handler.
    """
    from bot.handlers.teacher import handle_teacher_message
    from bot.handlers.student import handle_student_message

    role = await resolve_user_role(update, context)

    if role == "teacher":
        await handle_teacher_message(update, context)
    elif role == "student":
        await handle_student_message(update, context)
    else:
        await update.message.reply_text(
            "👋 Welcome! Please register first:\n"
            "• Teachers: /register\n"
            "• Students: /join <invite_code>"
        )
