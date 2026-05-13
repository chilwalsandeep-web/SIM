"""
agents/summariser.py
Generates teacher-facing summaries of student progress.
Triggered when teacher asks "how is Riya doing?" or requests a status update.
"""

import logging
from typing import Optional

from agents.base import BaseAgent
from db.models import Assignment, ProgressUpdate, User
from db.session import db_session

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a classroom assistant generating a progress summary for a teacher.
Given a student's assignment details and their recent activity, write a concise,
informative summary (3-5 sentences) that tells the teacher:
- What the assignment was
- Where the student currently stands
- Any concerns (stuck, overdue, no activity)
- A suggested next action for the teacher if needed

Be factual and professional. Return ONLY the summary text.
"""


class SummariserAgent(BaseAgent):
    name = "summariser"

    def run(
        self,
        student_id: int,
        teacher_id: int,
        assignment_id: Optional[int] = None,
    ) -> str:
        """
        Generate a progress summary for a teacher about one of their students.
        If assignment_id is provided, summarise just that assignment.
        Otherwise summarise all active assignments for the student.
        """
        with db_session() as db:
            student: Optional[User] = db.get(User, student_id)
            if not student:
                return "Student not found."

            # Fetch assignments
            query = (
                db.query(Assignment)
                .filter_by(student_id=student_id, teacher_id=teacher_id)
            )
            if assignment_id:
                query = query.filter_by(id=assignment_id)
            else:
                query = query.filter(Assignment.status.notin_(["reviewed"]))

            assignments = query.all()
            if not assignments:
                return f"No active assignments found for {student.full_name or 'this student'}."

            # Build context string for LLM
            context_parts = [
                f"Student: {student.full_name or student.telegram_handle or 'Unknown'}"
            ]
            for a in assignments:
                updates = (
                    db.query(ProgressUpdate)
                    .filter_by(assignment_id=a.id)
                    .order_by(ProgressUpdate.created_at.desc())
                    .limit(5)
                    .all()
                )
                update_summary = (
                    "\n".join(
                        f"  - [{u.created_at.strftime('%Y-%m-%d %H:%M')}] "
                        f"{u.interpreted_status}: {u.notes}"
                        for u in updates
                    )
                    or "  No updates yet."
                )
                context_parts.append(
                    f"\nAssignment: {a.title}\n"
                    f"Description: {a.description}\n"
                    f"Due: {a.due_date.strftime('%Y-%m-%d %H:%M UTC')}\n"
                    f"Status: {a.status}\n"
                    f"Recent updates:\n{update_summary}"
                )

            context = "\n".join(context_parts)

        try:
            summary = self.llm(system=SYSTEM_PROMPT, user=context, max_tokens=400)
            self.log(
                input_text=context,
                output_text=summary,
                user_id=teacher_id,
                assignment_id=assignment_id,
            )
            return summary
        except Exception as e:
            logger.error(f"SummariserAgent.run error: {e}")
            return "Sorry, I couldn't generate a summary right now. Please try again."


# Singleton
summariser_agent = SummariserAgent()
