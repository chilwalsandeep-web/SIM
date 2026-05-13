"""
services/reminder_service.py
APScheduler-based background job that periodically checks assignments
and fires reminders via the Reminder Agent.
"""

import logging
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agents.reminder_agent import reminder_agent
from db.models import Assignment, Reminder
from db.session import db_session

logger = logging.getLogger(__name__)


class ReminderService:
    """
    Runs a background job every 30 minutes.
    For each pending/in_progress assignment, asks the ReminderAgent
    whether a reminder should be sent, and if so fires it via the
    provided send_message callback.
    """

    def __init__(self, send_message_fn: Callable):
        """
        Args:
            send_message_fn: async callable(telegram_id: int, text: str) -> None
                             Provided by the bot at startup.
        """
        self._send = send_message_fn
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        self._scheduler.add_job(
            self._check_all_assignments,
            trigger=IntervalTrigger(minutes=30),
            id="reminder_check",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("ReminderService started — checking every 30 minutes.")

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("ReminderService stopped.")

    async def _check_all_assignments(self) -> None:
        logger.debug("ReminderService: running assignment check...")
        try:
            with db_session() as db:
                assignments = (
                    db.query(Assignment)
                    .filter(Assignment.status.in_(["pending", "in_progress"]))
                    .all()
                )
                assignment_ids = [a.id for a in assignments]
                student_telegram_ids = {
                    a.id: a.student.telegram_id for a in assignments
                }

            for assignment_id in assignment_ids:
                await self._process_assignment(
                    assignment_id=assignment_id,
                    student_telegram_id=student_telegram_ids[assignment_id],
                )

        except Exception as e:
            logger.error(f"ReminderService._check_all_assignments error: {e}")

    async def _process_assignment(
        self,
        assignment_id: int,
        student_telegram_id: int,
    ) -> None:
        try:
            result = reminder_agent.run(assignment_id=assignment_id)
            if result is None:
                return  # No reminder needed

            reminder_type = result["type"]
            message = result["message"]

            # Send the reminder
            await self._send(telegram_id=student_telegram_id, text=message)

            # Persist the reminder record
            with db_session() as db:
                reminder = Reminder(
                    assignment_id=assignment_id,
                    student_id=db.query(Assignment).get(assignment_id).student_id,
                    reminder_type=reminder_type,
                    message_sent=message,
                )
                db.add(reminder)

            logger.info(
                f"Sent {reminder_type} reminder for assignment {assignment_id} "
                f"→ telegram_id={student_telegram_id}"
            )

        except Exception as e:
            logger.error(f"ReminderService._process_assignment({assignment_id}) error: {e}")
