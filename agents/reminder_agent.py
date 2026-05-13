"""
agents/reminder_agent.py
Decides WHEN and HOW to remind students based on:
- Time remaining until deadline
- Student's last activity (last progress update timestamp)
- Number of reminders already sent
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from agents.base import BaseAgent
from db.models import Assignment, Reminder, ProgressUpdate
from db.session import db_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reminder thresholds
# ---------------------------------------------------------------------------

REMINDER_TYPE_RULES = {
    # (hours_until_due, min_hours_since_last_activity) -> reminder_type
    "final":   {"hours_until_due_max": 6},
    "urgent":  {"hours_until_due_max": 24},
    "regular": {"hours_until_due_max": 72},
    "gentle":  {"hours_until_due_max": float("inf")},
}

SYSTEM_PROMPT = """
You are a classroom reminder bot. Write a short, friendly, personalised Telegram reminder
to a student about their upcoming assignment. 

Tone guide:
- gentle: warm nudge, no pressure
- regular: friendly but clear deadline mention
- urgent: direct, deadline is soon, motivating
- final: very short, alarm bells, deadline is in hours

Keep it under 80 words. Do NOT be preachy or repetitive.
Return ONLY the reminder message text.
"""


class ReminderAgent(BaseAgent):
    name = "reminder_agent"

    def run(self, assignment_id: int) -> Optional[dict]:
        """
        Evaluate whether a reminder should be sent for this assignment.
        Returns a dict with {type, message} if a reminder should go out, else None.
        """
        with db_session() as db:
            assignment: Optional[Assignment] = db.get(Assignment, assignment_id)
            if not assignment:
                logger.warning(f"ReminderAgent: assignment {assignment_id} not found")
                return None

            # Skip if already submitted or reviewed
            if assignment.status in ("submitted", "reviewed"):
                return None

            hours_left = assignment.hours_until_due
            if hours_left < 0:
                # Overdue — still send a final nudge if not already sent recently
                hours_left = 0

            # Last student activity
            last_update: Optional[ProgressUpdate] = (
                db.query(ProgressUpdate)
                .filter_by(assignment_id=assignment_id)
                .order_by(ProgressUpdate.created_at.desc())
                .first()
            )
            hours_since_activity = self._hours_since(
                last_update.created_at if last_update else assignment.created_at
            )

            # Decide reminder type
            reminder_type = self._decide_type(hours_left, hours_since_activity)
            if reminder_type is None:
                return None  # Not time to remind yet

            # Check we haven't sent the same type too recently
            if self._sent_recently(db, assignment_id, reminder_type, hours=12):
                return None

            # Generate message
            message = self._generate_message(
                reminder_type=reminder_type,
                assignment_title=assignment.title or "your assignment",
                hours_left=hours_left,
                due_date=assignment.due_date,
            )

            return {"type": reminder_type, "message": message}

    # ------------------------------------------------------------------

    def _decide_type(self, hours_left: float, hours_since_activity: float) -> Optional[str]:
        """
        Smart reminder logic:
        - If student was active in last 2 hours → skip (they're working)
        - Otherwise select type by urgency
        """
        if hours_since_activity < 2:
            logger.debug("ReminderAgent: student recently active, skipping reminder")
            return None

        if hours_left <= 6:
            return "final"
        elif hours_left <= 24:
            return "urgent"
        elif hours_left <= 72 and hours_since_activity > 24:
            return "regular"
        elif hours_since_activity > 48:
            return "gentle"
        return None

    def _sent_recently(
        self,
        db,
        assignment_id: int,
        reminder_type: str,
        hours: int = 12,
    ) -> bool:
        """Return True if the same reminder type was already sent within `hours`."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        exists = (
            db.query(Reminder)
            .filter(
                Reminder.assignment_id == assignment_id,
                Reminder.reminder_type == reminder_type,
                Reminder.sent_at >= cutoff,
            )
            .first()
        )
        return exists is not None

    def _generate_message(
        self,
        reminder_type: str,
        assignment_title: str,
        hours_left: float,
        due_date: datetime,
    ) -> str:
        due_str = due_date.strftime("%A, %d %B at %H:%M UTC")
        context = (
            f"Assignment: {assignment_title}\n"
            f"Hours until deadline: {max(0, round(hours_left))}\n"
            f"Due: {due_str}\n"
            f"Reminder type: {reminder_type}"
        )
        try:
            msg = self.llm(system=SYSTEM_PROMPT, user=context, max_tokens=150)
            self.log(input_text=context, output_text=msg)
            return msg
        except Exception as e:
            logger.error(f"ReminderAgent._generate_message error: {e}")
            return f"⏰ Reminder: '{assignment_title}' is due {due_str}. Keep going!"

    @staticmethod
    def _hours_since(dt: datetime) -> float:
        return (datetime.utcnow() - dt).total_seconds() / 3600


# Singleton
reminder_agent = ReminderAgent()
