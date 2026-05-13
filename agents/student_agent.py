"""
agents/student_agent.py
Handles all student-side intelligence:
- Interpreting progress updates in natural language
- Detecting submission intent
- Generating acknowledgement replies
"""

import json
import logging
from typing import Optional

from agents.base import BaseAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

INTERPRET_PROGRESS_SYSTEM = """
You are a classroom assistant bot. A student just sent a message about their assignment progress.
Interpret the message and return ONLY a JSON object (no markdown, no backticks):

{
  "interpreted_status": "<one of: started | in_progress | stuck | completed>",
  "notes": "<1-2 sentence summary of what the student said>",
  "is_submission": <true if the student is saying they finished and are submitting, else false>
}

Be generous in interpreting "completed" — if they say "done", "finished", "submitted", "all good", treat as completed.
"""

ACKNOWLEDGE_PROGRESS_SYSTEM = """
You are a friendly classroom companion bot replying to a student's progress update.
Write a short (1-2 sentence), warm, encouraging reply acknowledging their update.
If they're stuck, offer a brief word of encouragement and remind them their teacher is there to help.
If they're done, celebrate briefly and tell them their submission has been forwarded.
Return ONLY the reply text, nothing else.
"""

FEEDBACK_DELIVERY_SYSTEM = """
You are a classroom bot delivering teacher feedback to a student.
Reframe the feedback in a warm, friendly conversational tone as if the bot is personally
passing on the teacher's thoughts. Start with something like "Your teacher reviewed your work!"
Keep it under 120 words. Return ONLY the message text.
"""


# ---------------------------------------------------------------------------
# Student Agent
# ---------------------------------------------------------------------------

class StudentAgent(BaseAgent):
    name = "student_agent"

    def run(self, action: str, **kwargs):
        dispatch = {
            "interpret_progress":    self.interpret_progress,
            "acknowledge_progress":  self.acknowledge_progress,
            "deliver_feedback":      self.deliver_feedback,
        }
        handler = dispatch.get(action)
        if not handler:
            raise ValueError(f"StudentAgent: unknown action '{action}'")
        return handler(**kwargs)

    # ------------------------------------------------------------------
    # Interpret a student's natural language progress message
    # ------------------------------------------------------------------

    def interpret_progress(
        self,
        raw_message: str,
        user_id: Optional[int] = None,
        assignment_id: Optional[int] = None,
    ) -> dict:
        """
        Parse what the student said about their progress.

        Returns:
            {
                "interpreted_status": str,   # started | in_progress | stuck | completed
                "notes": str,
                "is_submission": bool,
            }
        """
        try:
            raw = self.llm(
                system=INTERPRET_PROGRESS_SYSTEM,
                user=raw_message,
                max_tokens=256,
            )
            data = json.loads(raw)
            self.log(
                input_text=raw_message,
                output_text=raw,
                user_id=user_id,
                assignment_id=assignment_id,
            )
            return {
                "interpreted_status": data.get("interpreted_status", "in_progress"),
                "notes":              data.get("notes", ""),
                "is_submission":      bool(data.get("is_submission", False)),
            }

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"StudentAgent.interpret_progress fallback: {e}")
            return {
                "interpreted_status": "in_progress",
                "notes":              raw_message,
                "is_submission":      False,
            }

    # ------------------------------------------------------------------
    # Generate a reply to send back to the student after a progress update
    # ------------------------------------------------------------------

    def acknowledge_progress(
        self,
        raw_message: str,
        interpreted_status: str,
        is_submission: bool = False,
        user_id: Optional[int] = None,
        assignment_id: Optional[int] = None,
    ) -> str:
        """Generate an encouraging reply for the student."""
        context = (
            f"Student message: {raw_message}\n"
            f"Interpreted status: {interpreted_status}\n"
            f"Is this a final submission: {is_submission}"
        )
        try:
            reply = self.llm(
                system=ACKNOWLEDGE_PROGRESS_SYSTEM,
                user=context,
                max_tokens=128,
            )
            self.log(
                input_text=context,
                output_text=reply,
                user_id=user_id,
                assignment_id=assignment_id,
            )
            return reply
        except Exception as e:
            logger.error(f"StudentAgent.acknowledge_progress error: {e}")
            if is_submission:
                return "✅ Got it! Your submission has been forwarded to your teacher."
            return "👍 Thanks for the update! Keep going, you're doing great."

    # ------------------------------------------------------------------
    # Wrap teacher feedback for delivery to the student
    # ------------------------------------------------------------------

    def deliver_feedback(
        self,
        formatted_feedback: str,
        user_id: Optional[int] = None,
        assignment_id: Optional[int] = None,
    ) -> str:
        """Wrap teacher feedback in a friendly conversational delivery message."""
        try:
            msg = self.llm(
                system=FEEDBACK_DELIVERY_SYSTEM,
                user=formatted_feedback,
                max_tokens=200,
            )
            self.log(
                input_text=formatted_feedback,
                output_text=msg,
                user_id=user_id,
                assignment_id=assignment_id,
            )
            return msg
        except Exception as e:
            logger.error(f"StudentAgent.deliver_feedback error: {e}")
            return f"📝 Feedback from your teacher:\n\n{formatted_feedback}"


# Singleton
student_agent = StudentAgent()
