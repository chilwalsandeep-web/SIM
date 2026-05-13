"""
bot/handlers/student.py
All Telegram command and message handlers for students.
Handles: /start, /join, progress updates, file/photo/voice submissions.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from agents import intent_router, Intent, student_agent
from db.session import db_session
from db.models import Assignment
from services.assignment_service import (
    get_or_create_user,
    get_user_by_telegram_id,
    redeem_invite_code,
    get_active_assignments_for_student,
    record_progress_update,
    create_submission,
    update_assignment_status,
)
from services.transcription import transcribe_voice, get_telegram_file_url
from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def cmd_start_student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    with db_session() as db:
        db_user = get_user_by_telegram_id(db, user.id)
        already_registered = db_user is not None
        role = db_user.role if db_user else None

    if already_registered and role == "student":
        await update.message.reply_text(
            f"👋 Welcome back, {user.first_name}!\n\n"
            "Use /assignments to see your current work, or just chat with me to update your progress!",
        )
    elif already_registered and role == "teacher":
        await update.message.reply_text(
            "You're registered as a *Teacher*. Use /invite or type naturally to assign work.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! Welcome to Classroom Companion.\n\n"
            "Are you a *student* joining a class? Use:\n"
            "  /join <invite_code>\n\n"
            "Are you a *teacher*? Use:\n"
            "  /register",
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# /join <code>  — student redeems an invite
# ---------------------------------------------------------------------------

async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(
            "Please provide your invite code:\n`/join ABC12345`",
            parse_mode="Markdown",
        )
        return

    code = args[0].strip().upper()

    with db_session() as db:
        student, _ = get_or_create_user(
            db=db,
            telegram_id=user.id,
            role="student",
            full_name=user.full_name,
            telegram_handle=user.username,
        )
        link = redeem_invite_code(db, code=code, student=student)
        if not link:
            await update.message.reply_text(
                "❌ Invalid or expired invite code. Please check with your teacher."
            )
            return

        teacher = link.teacher
        teacher_name = teacher.full_name or teacher.telegram_handle or "your teacher"

    await update.message.reply_text(
        f"✅ You've joined *{teacher_name}*'s class!\n\n"
        "You'll receive assignments here. You can:\n"
        "• Reply naturally to update your progress\n"
        "• Send text, files, photos, or voice notes to submit work\n"
        "• Use /assignments to see your current tasks",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /assignments  — student's assignment list
# ---------------------------------------------------------------------------

async def cmd_assignments_student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    with db_session() as db:
        student = get_user_by_telegram_id(db, user.id)
        if not student or not student.is_student:
            await update.message.reply_text("Please /join a class first.")
            return

        assignments = get_active_assignments_for_student(db, student.id)
        if not assignments:
            await update.message.reply_text("🎉 No active assignments right now. Enjoy the break!")
            return

        lines = ["📋 *Your Assignments:*\n"]
        for a in assignments:
            due = a.due_date.strftime("%d %b, %H:%M")
            overdue = " ⚠️ OVERDUE" if a.is_overdue else ""
            status_emoji = {"pending": "⏳", "in_progress": "✏️", "submitted": "📬"}.get(a.status, "❓")
            lines.append(
                f"{status_emoji} *{a.title}*{overdue}\n"
                f"   Due: {due} | Status: {a.status}\n"
                f"   _{a.description[:80]}{'...' if len(a.description) > 80 else ''}_\n"
            )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Handle free-text from student (progress update or completion)
# ---------------------------------------------------------------------------

async def handle_student_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = update.message.text or ""

    with db_session() as db:
        student = get_user_by_telegram_id(db, user.id)
        if not student or not student.is_student:
            await update.message.reply_text("Please /join a class first.")
            return

        # Get the most recent active assignment
        assignments = get_active_assignments_for_student(db, student.id)
        if not assignments:
            await update.message.reply_text(
                "You have no active assignments right now. 🎉"
            )
            return
        assignment = assignments[0]
        assignment_id = assignment.id
        teacher_telegram_id = assignment.teacher.telegram_id

    # Interpret progress
    result = student_agent.run(
        action="interpret_progress",
        raw_message=text,
        user_id=student.id,
        assignment_id=assignment_id,
    )

    # Persist progress update
    with db_session() as db:
        record_progress_update(
            db=db,
            assignment_id=assignment_id,
            student_id=student.id,
            raw_message=text,
            interpreted_status=result["interpreted_status"],
            notes=result["notes"],
        )
        if result["interpreted_status"] == "in_progress":
            update_assignment_status(db, assignment_id, "in_progress")

    # If it's a submission, handle accordingly
    if result["is_submission"]:
        await _finalize_text_submission(
            update=update,
            context=context,
            student=student,
            assignment_id=assignment_id,
            text=text,
            teacher_telegram_id=teacher_telegram_id,
        )
        return

    # Send acknowledgement
    ack = student_agent.run(
        action="acknowledge_progress",
        raw_message=text,
        interpreted_status=result["interpreted_status"],
        is_submission=False,
        user_id=student.id,
        assignment_id=assignment_id,
    )
    await update.message.reply_text(ack)

    # Notify teacher of status update
    student_name = student.full_name or student.telegram_handle or "Your student"
    await context.bot.send_message(
        chat_id=teacher_telegram_id,
        text=(
            f"📢 *Update from {student_name}:*\n"
            f"_{text}_\n\n"
            f"Status: *{result['interpreted_status']}*\n"
            f"Summary: {result['notes']}"
        ),
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Handle file / photo submissions
# ---------------------------------------------------------------------------

async def handle_student_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle file/document submissions."""
    user = update.effective_user
    document = update.message.document

    with db_session() as db:
        student = get_user_by_telegram_id(db, user.id)
        if not student:
            return
        assignments = get_active_assignments_for_student(db, student.id)
        if not assignments:
            await update.message.reply_text("No active assignment to submit for.")
            return
        assignment = assignments[0]

        sub = create_submission(
            db=db,
            assignment_id=assignment.id,
            student_id=student.id,
            submission_type="file",
            file_id=document.file_id,
        )
        teacher_telegram_id = assignment.teacher.telegram_id
        student_name = student.full_name or student.telegram_handle

    # Forward to teacher
    caption = f"📬 *Submission from {student_name}*\nAssignment: {assignment.title}"
    await context.bot.send_document(
        chat_id=teacher_telegram_id,
        document=document.file_id,
        caption=caption,
        parse_mode="Markdown",
    )
    await update.message.reply_text("✅ Your file has been submitted and forwarded to your teacher!")


async def handle_student_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo submissions."""
    user = update.effective_user
    photo = update.message.photo[-1]  # highest resolution

    with db_session() as db:
        student = get_user_by_telegram_id(db, user.id)
        if not student:
            return
        assignments = get_active_assignments_for_student(db, student.id)
        if not assignments:
            await update.message.reply_text("No active assignment to submit for.")
            return
        assignment = assignments[0]

        create_submission(
            db=db,
            assignment_id=assignment.id,
            student_id=student.id,
            submission_type="photo",
            file_id=photo.file_id,
        )
        teacher_telegram_id = assignment.teacher.telegram_id
        student_name = student.full_name or student.telegram_handle

    caption = f"📬 *Photo submission from {student_name}*\nAssignment: {assignment.title}"
    await context.bot.send_photo(
        chat_id=teacher_telegram_id,
        photo=photo.file_id,
        caption=caption,
        parse_mode="Markdown",
    )
    await update.message.reply_text("✅ Photo submitted and forwarded to your teacher!")


async def handle_student_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice note submissions — transcribes and forwards."""
    user = update.effective_user
    voice = update.message.voice

    await update.message.reply_text("🎙️ Voice note received! Transcribing...")

    with db_session() as db:
        student = get_user_by_telegram_id(db, user.id)
        if not student:
            return
        assignments = get_active_assignments_for_student(db, student.id)
        if not assignments:
            await update.message.reply_text("No active assignment to submit for.")
            return
        assignment = assignments[0]

        # Get download URL and transcribe
        file_url = await get_telegram_file_url(settings.TELEGRAM_BOT_TOKEN, voice.file_id)
        transcription = None
        if file_url:
            from services.transcription import transcribe_voice as tv
            transcription = await tv(file_url)

        create_submission(
            db=db,
            assignment_id=assignment.id,
            student_id=student.id,
            submission_type="voice",
            file_id=voice.file_id,
            transcription=transcription,
        )
        teacher_telegram_id = assignment.teacher.telegram_id
        student_name = student.full_name or student.telegram_handle

    # Forward voice + transcription to teacher
    teacher_msg = f"🎙️ *Voice submission from {student_name}*\nAssignment: {assignment.title}"
    if transcription:
        teacher_msg += f"\n\n📝 *Transcription:*\n_{transcription}_"

    await context.bot.send_voice(
        chat_id=teacher_telegram_id,
        voice=voice.file_id,
        caption=teacher_msg,
        parse_mode="Markdown",
    )

    reply = "✅ Voice note submitted!"
    if transcription:
        reply += f"\n\n📝 _Transcription:_\n{transcription}"
    await update.message.reply_text(reply, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _finalize_text_submission(
    update, context, student, assignment_id, text, teacher_telegram_id
) -> None:
    with db_session() as db:
        create_submission(
            db=db,
            assignment_id=assignment_id,
            student_id=student.id,
            submission_type="text",
            text_content=text,
        )
        assignment = db.get(Assignment, assignment_id)
        assignment_title = assignment.title if assignment else "Assignment"

    ack = student_agent.run(
        action="acknowledge_progress",
        raw_message=text,
        interpreted_status="completed",
        is_submission=True,
        user_id=student.id,
        assignment_id=assignment_id,
    )
    await update.message.reply_text(ack)

    student_name = student.full_name or student.telegram_handle or "A student"
    await context.bot.send_message(
        chat_id=teacher_telegram_id,
        text=(
            f"📬 *Submission from {student_name}*\n"
            f"Assignment: *{assignment_title}*\n\n"
            f"_{text}_\n\n"
            "Please review and send your feedback by replying naturally!"
        ),
        parse_mode="Markdown",
    )
