"""
agents/teacher_agent.py
Handles all teacher-side intelligence:
- Parsing natural language assignment instructions
- Formatting feedback before sending to students
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from agents.base import BaseAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PARSE_ASSIGNMENT_SYSTEM = """
You are a teacher assistant bot. A teacher just sent an instruction to assign work to a student.
Extract the assignment details and return ONLY a JSON object (no markdown, no backticks):

{
  "title": "<short title, max 10 words>",
  "description": "<full clear assignment description for the student>",
  "student_name": "<student name or handle mentioned, or null>",
  "due_in_days": <integer number of days until due, or null if not mentioned>,
  "due_date_str": "<ISO 8601 datetime string if you can infer it, else null>"
}

If a due date/time is not mentioned, set due_in_days to 3 (default).
Be friendly and encouraging in the description — students will read it directly.
"""

FORMAT_FEEDBACK_SYSTEM = """
You are a helpful teacher assistant. A teacher just wrote feedback on a student's submission.
Rewrite this feedback in a warm, encouraging, constructive tone suitable for a student
receiving it via Telegram. Keep it concise (2-4 sentences max). 
Return ONLY the formatted feedback text, nothing else.
"""

ASSIGNMENT_NOTIFICATION_SYSTEM = """
You are a classroom bot sending an assignment notification to a student.
Write a friendly, clear Telegram message announcing this assignment.
Include: the assignment description, the deadline, and a motivational closing line.
Keep it under 150 words. Return ONLY the message text.
"""


# ---------------------------------------------------------------------------
# Teacher Agent
# ---------------------------------------------------------------------------

class TeacherAgent(BaseAgent):
    name = "teacher_agent"

    def run(self, action: str, **kwargs):
        """Dispatch to the right sub-method based on action."""
        dispatch = {
            "parse_assignment":        self.parse_assignment,
            "format_feedback":         self.format_feedback,
            "build_assignment_message": self.build_assignment_message,
        }
        handler = dispatch.get(action)
        if not handler:
            raise ValueError(f"TeacherAgent: unknown action '{action}'")
        return handler(**kwargs)

    # ------------------------------------------------------------------
    # Parse a natural language assignment instruction
    # ------------------------------------------------------------------

    def parse_assignment(
        self,
        raw_instruction: str,
        user_id: Optional[int] = None,
    ) -> dict:
        """
        Parse teacher's natural language instruction into structured data.

        Returns:
            {
                "title": str,
                "description": str,
                "student_name": str | None,
                "due_date": datetime,
            }
        """
        try:
            raw = self.llm(
                system=PARSE_ASSIGNMENT_SYSTEM,
                user=raw_instruction,
                max_tokens=512,
            )
            clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(clean)
            self.log(input_text=raw_instruction, output_text=raw, user_id=user_id)

            # Resolve due_date
            due_date = self._resolve_due_date(
                due_in_days=data.get("due_in_days"),
                due_date_str=data.get("due_date_str"),
            )

            return {
                "title":        data.get("title", "Assignment"),
                "description":  data.get("description", raw_instruction),
                "student_name": data.get("student_name"),
                "due_date":     due_date,
            }

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"TeacherAgent.parse_assignment fallback: {e}")
            # Graceful fallback — store the raw instruction as-is
            return {
                "title":        "Assignment",
                "description":  raw_instruction,
                "student_name": None,
                "due_date":     datetime.utcnow() + timedelta(days=3),
            }

    # ------------------------------------------------------------------
    # Format teacher's raw feedback into a student-friendly message
    # ------------------------------------------------------------------

    def format_feedback(
        self,
        raw_feedback: str,
        user_id: Optional[int] = None,
        assignment_id: Optional[int] = None,
    ) -> str:
        """Polish teacher's raw feedback into a warm student-facing message."""
        try:
            formatted = self.llm(
                system=FORMAT_FEEDBACK_SYSTEM,
                user=raw_feedback,
                max_tokens=256,
            )
            self.log(
                input_text=raw_feedback,
                output_text=formatted,
                user_id=user_id,
                assignment_id=assignment_id,
            )
            return formatted
        except Exception as e:
            logger.error(f"TeacherAgent.format_feedback error: {e}")
            return raw_feedback  # fallback: send as-is

    # ------------------------------------------------------------------
    # Build the Telegram message sent to the student when assigned
    # ------------------------------------------------------------------

    def build_assignment_message(
        self,
        description: str,
        due_date: datetime,
        student_name: Optional[str] = None,
        assignment_id: Optional[int] = None,
    ) -> str:
        """Generate the Telegram message a student receives for a new assignment."""
        due_str = due_date.strftime("%A, %d %B %Y at %H:%M UTC")
        context = f"Assignment: {description}\nDeadline: {due_str}"
        if student_name:
            context = f"Student name: {student_name}\n" + context

        try:
            msg = self.llm(
                system=ASSIGNMENT_NOTIFICATION_SYSTEM,
                user=context,
                max_tokens=256,
            )
            self.log(
                input_text=context,
                output_text=msg,
                assignment_id=assignment_id,
            )
            return msg
        except Exception as e:
            logger.error(f"TeacherAgent.build_assignment_message error: {e}")
            return f"📚 New assignment!\n\n{description}\n\n⏰ Due: {due_str}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_due_date(
        due_in_days: Optional[int],
        due_date_str: Optional[str],
    ) -> datetime:
        if due_date_str:
            try:
                return datetime.fromisoformat(due_date_str)
            except ValueError:
                pass
        days = due_in_days if isinstance(due_in_days, int) and due_in_days > 0 else 3
        return datetime.utcnow() + timedelta(days=days)


# Singleton
teacher_agent = TeacherAgent()
