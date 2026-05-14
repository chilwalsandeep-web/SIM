"""
bot/handlers/teacher.py
All Telegram command and message handlers for teachers.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from agents import intent_router, Intent, teacher_agent, summariser_agent
from db.session import db_session
from services.assignment_service import (
    get_or_create_user,
    get_students_for_teacher,
    generate_invite_code,
    create_assignment,
    get_all_assignments_for_teacher,
    save_feedback,
    get_user_by_telegram_id,
)
from db.models import Assignment, Submission

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# /start  (teacher entry point)
# ---------------------------------------------------------------------------

async def cmd_start_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    with db_session() as db:
        _, created = get_or_create_user(
            db=db,
            telegram_id=user.id,
            role="teacher",
            full_name=user.full_name,
            telegram_handle=user.username,
        )
    greeting = "Welcome back" if not created else "Welcome"
    await update.message.reply_text(
        f"👋 {greeting}, {user.first_name}!\n\n"
        "You're registered as a *Teacher*. Here's what you can do:\n\n"
        "• /invite — generate a student invite code\n"
        "• /students — see all your students\n"
        "• /assignments — view all assignments\n"
        "• Just type naturally to assign work or give feedback!\n\n"
        "_Example: \"Assign Riya a 500-word essay on photosynthesis, due in 3 days\"_",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /register  (explicit teacher registration)
# ---------------------------------------------------------------------------

async def cmd_register_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    with db_session() as db:
        db_user, created = get_or_create_user(
            db=db,
            telegram_id=user.id,
            role="teacher",
            full_name=user.full_name,
            telegram_handle=user.username,
        )
    if created:
        await update.message.reply_text(
            "✅ You're now registered as a *Teacher*!\n"
            "Use /invite to generate a code for your students.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"You're already registered as a *{db_user.role}*.",
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# /invite  — generate an invite code
# ---------------------------------------------------------------------------

async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    with db_session() as db:
        teacher = get_user_by_telegram_id(db, user.id)
        if not teacher or not teacher.is_teacher:
            await update.message.reply_text("❌ Only teachers can generate invite codes.")
            return

        invite = generate_invite_code(db, teacher.id)
        code = invite.code

    await update.message.reply_text(
        f"🔗 *Invite Code Generated!*\n\n"
        f"`{code}`\n\n"
        "Share this code with your student. They should:\n"
        "1. Start the bot\n"
        "2. Use /join and enter this code\n\n"
        "_Code expires after first use._",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /students  — list all linked students
# ---------------------------------------------------------------------------

async def cmd_students(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    with db_session() as db:
        teacher = get_user_by_telegram_id(db, user.id)
        if not teacher or not teacher.is_teacher:
            await update.message.reply_text("❌ Only teachers can view this.")
            return

        students = get_students_for_teacher(db, teacher.id)
        if not students:
            await update.message.reply_text(
                "You have no students yet. Use /invite to add one!"
            )
            return

        lines = ["👥 *Your Students:*\n"]
        for i, s in enumerate(students, 1):
            handle = f"@{s.telegram_handle}" if s.telegram_handle else "no handle"
            name = s.full_name or "Unknown"
            lines.append(f"{i}. {name} ({handle})")

        message = "\n".join(lines)

    await update.message.reply_text(message)

# ---------------------------------------------------------------------------
# /assignments  — list all assignments
# ---------------------------------------------------------------------------

async def cmd_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    with db_session() as db:
        teacher = get_user_by_telegram_id(db, user.id)
        if not teacher or not teacher.is_teacher:
            await update.message.reply_text("❌ Only teachers can view this.")
            return

        assignments = get_all_assignments_for_teacher(db, teacher.id)
        if not assignments:
            await update.message.reply_text("No assignments yet.")
            return

        lines = ["📋 *All Assignments:*\n"]
        for a in assignments:
            student_name = a.student.full_name or a.student.telegram_handle or "Unknown"
            due = a.due_date.strftime("%d %b, %H:%M")
            status_emoji = {
                "pending": "⏳", "in_progress": "✏️",
                "submitted": "📬", "reviewed": "✅"
            }.get(a.status, "❓")
            lines.append(
                f"{status_emoji} *{a.title}*\n"
                f"   Student: {student_name} | Due: {due} | Status: {a.status}\n"
            )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Handle free-text from teacher (assignment / feedback via LLM)
# ---------------------------------------------------------------------------

async def handle_teacher_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = update.message.text or ""

    with db_session() as db:
        teacher = get_user_by_telegram_id(db, user.id)
        if not teacher:
            await update.message.reply_text("Please /register first.")
            return
        teacher_id = teacher.id

    intent = intent_router.run(message=text, user_id=teacher_id)

    if intent == Intent.ASSIGN_WORK:
        await _handle_assign_work(update, context, teacher_id=teacher_id, text=text)

    elif intent == Intent.GIVE_FEEDBACK:
        await _handle_give_feedback(update, context, teacher_id=teacher_id, text=text)

    elif intent == Intent.REQUEST_SUMMARY:
        await _handle_request_summary(update, context, teacher_id=teacher_id, text=text)

    elif intent == Intent.GREETING:
        await update.message.reply_text(
            "👋 Hi! You can assign work, request summaries, or give feedback — just type naturally!"
        )
    else:
        await update.message.reply_text(
            "I'm not sure what you mean. Try something like:\n"
            "Assign Riya a 500-word essay on photosynthesis, due in 3 days"
        )


# ---------------------------------------------------------------------------
# Internal: assign work
# ---------------------------------------------------------------------------

async def _handle_assign_work(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    teacher_id: int,
    text: str,
) -> None:
    await update.message.reply_text("🔍 Parsing your assignment instruction...")

    parsed = teacher_agent.run(
        action="parse_assignment",
        raw_instruction=text,
        user_id=teacher_id,
    )

    # Find the student by name/handle
    with db_session() as db:
        students = get_students_for_teacher(db, teacher_id)
        target_student = None
        if parsed.get("student_name"):
            name_lower = parsed["student_name"].lower()
            for s in students:
                if (
                    (s.full_name and name_lower in s.full_name.lower())
                    or (s.telegram_handle and name_lower in s.telegram_handle.lower())
                ):
                    target_student = s
                    break

        if not target_student:
            if len(students) == 1:
                target_student = students[0]
            else:
                student_list = "\n".join(
                    f"  • {s.full_name or s.telegram_handle}" for s in students
                )
                await update.message.reply_text(
                    f"👥 Which student is this for? Please mention their name clearly.\n\n"
                    f"Your students:\n{student_list}"
                )
                return

        assignment = create_assignment(
            db=db,
            teacher_id=teacher_id,
            student_id=target_student.id,
            title=parsed["title"],
            description=parsed["description"],
            raw_instruction=text,
            due_date=parsed["due_date"],
        )
        assignment_id = assignment.id
        student_telegram_id = target_student.telegram_id
        student_name = target_student.full_name or target_student.telegram_handle

    # Build and send the assignment message to the student
    student_msg = teacher_agent.run(
        action="build_assignment_message",
        description=parsed["description"],
        due_date=parsed["due_date"],
        student_name=student_name,
        assignment_id=assignment_id,
    )
    await context.bot.send_message(chat_id=student_telegram_id, text=student_msg)

    # Confirm to teacher
    await update.message.reply_text(
        f"✅ Assignment sent to *{student_name}*!\n\n"
        f"📚 *{parsed['title']}*\n"
        f"Due: {parsed['due_date'].strftime('%A, %d %B at %H:%M UTC')}",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Internal: give feedback
# ---------------------------------------------------------------------------

async def _handle_give_feedback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    teacher_id: int,
    text: str,
) -> None:
    # Find the most recent submission awaiting feedback from this teacher
    with db_session() as db:
        submission = (
            db.query(Submission)
            .join(Assignment)
            .filter(
                Assignment.teacher_id == teacher_id,
                Assignment.status == "submitted",
            )
            .order_by(Submission.submitted_at.desc())
            .first()
        )
        if not submission:
            await update.message.reply_text(
                "No pending submissions found to give feedback on."
            )
            return

        formatted = teacher_agent.run(
            action="format_feedback",
            raw_feedback=text,
            user_id=teacher_id,
            assignment_id=submission.assignment_id,
        )
        fb = save_feedback(
            db=db,
            submission_id=submission.id,
            teacher_id=teacher_id,
            raw_message=text,
            formatted_feedback=formatted,
        )
        student_telegram_id = submission.student.telegram_id
        student_name = submission.student.full_name or submission.student.telegram_handle

    await context.bot.send_message(
        chat_id=student_telegram_id,
        text=f"📝 *Feedback from your teacher:*\n\n{formatted}",
        parse_mode="Markdown",
    )
    await update.message.reply_text(
        f"✅ Feedback sent to *{student_name}*!",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Internal: request summary
# ---------------------------------------------------------------------------

async def _handle_request_summary(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    teacher_id: int,
    text: str,
) -> None:
    await update.message.reply_text("⏳ Generating summary...")
    with db_session() as db:
        students = get_students_for_teacher(db, teacher_id)
        if not students:
            await update.message.reply_text("You have no students yet.")
            return
        # Use the first student for now; smarter name matching can be added
        student_id = students[0].id

    summary = summariser_agent.run(student_id=student_id, teacher_id=teacher_id)
    await update.message.reply_text(f"📊 *Student Summary:*\n\n{summary}", parse_mode="Markdown")
