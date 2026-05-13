"""
services/assignment_service.py
Core business logic for assignment lifecycle.
Sits between bot handlers and the DB — keeps handlers thin.
"""

import logging
import random
import string
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from db.models import (
    Assignment, Feedback, InviteCode, ProgressUpdate,
    Submission, TeacherStudent, User
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

def get_or_create_user(
    db: Session,
    telegram_id: int,
    role: str,
    full_name: Optional[str] = None,
    telegram_handle: Optional[str] = None,
) -> tuple[User, bool]:
    """
    Fetch existing user or create a new one.
    Returns (user, created_bool).
    """
    user = db.query(User).filter_by(telegram_id=telegram_id).first()
    if user:
        return user, False

    user = User(
        telegram_id=telegram_id,
        role=role,
        full_name=full_name,
        telegram_handle=telegram_handle,
    )
    db.add(user)
    db.flush()  # get id without full commit
    logger.info(f"Created new {role}: telegram_id={telegram_id}")
    return user, True


def get_user_by_telegram_id(db: Session, telegram_id: int) -> Optional[User]:
    return db.query(User).filter_by(telegram_id=telegram_id).first()


# ---------------------------------------------------------------------------
# Invite codes
# ---------------------------------------------------------------------------

def generate_invite_code(db: Session, teacher_id: int) -> InviteCode:
    """Generate a unique 8-character invite code for a teacher."""
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if not db.query(InviteCode).filter_by(code=code).first():
            break

    invite = InviteCode(teacher_id=teacher_id, code=code)
    db.add(invite)
    db.flush()
    logger.info(f"Generated invite code {code} for teacher {teacher_id}")
    return invite


def redeem_invite_code(
    db: Session,
    code: str,
    student: User,
) -> Optional[TeacherStudent]:
    """
    Redeem an invite code for a student.
    Returns TeacherStudent link on success, None on failure.
    """
    invite = db.query(InviteCode).filter_by(code=code, is_used=False).first()
    if not invite:
        logger.warning(f"Invalid or already-used invite code: {code}")
        return None

    if invite.is_expired:
        logger.warning(f"Expired invite code: {code}")
        return None

    # Mark used
    invite.is_used = True
    invite.used_by = student.id

    # Create teacher-student link (ignore if already exists)
    existing = db.query(TeacherStudent).filter_by(
        teacher_id=invite.teacher_id, student_id=student.id
    ).first()
    if existing:
        return existing

    link = TeacherStudent(teacher_id=invite.teacher_id, student_id=student.id)
    db.add(link)
    db.flush()
    logger.info(f"Student {student.id} linked to teacher {invite.teacher_id}")
    return link


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

def create_assignment(
    db: Session,
    teacher_id: int,
    student_id: int,
    title: str,
    description: str,
    raw_instruction: str,
    due_date: datetime,
) -> Assignment:
    assignment = Assignment(
        teacher_id=teacher_id,
        student_id=student_id,
        title=title,
        description=description,
        raw_instruction=raw_instruction,
        due_date=due_date,
        status="pending",
    )
    db.add(assignment)
    db.flush()
    logger.info(f"Assignment {assignment.id} created for student {student_id}")
    return assignment


def get_assignment(db: Session, assignment_id: int) -> Optional[Assignment]:
    return db.get(Assignment, assignment_id)


def get_active_assignments_for_student(db: Session, student_id: int) -> list[Assignment]:
    return (
        db.query(Assignment)
        .filter(
            Assignment.student_id == student_id,
            Assignment.status.notin_(["reviewed"]),
        )
        .order_by(Assignment.due_date.asc())
        .all()
    )


def get_all_assignments_for_teacher(db: Session, teacher_id: int) -> list[Assignment]:
    return (
        db.query(Assignment)
        .filter_by(teacher_id=teacher_id)
        .order_by(Assignment.created_at.desc())
        .all()
    )


def update_assignment_status(db: Session, assignment_id: int, status: str) -> None:
    assignment = db.get(Assignment, assignment_id)
    if assignment:
        assignment.status = status
        assignment.updated_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# Progress Updates
# ---------------------------------------------------------------------------

def record_progress_update(
    db: Session,
    assignment_id: int,
    student_id: int,
    raw_message: str,
    interpreted_status: str,
    notes: str,
) -> ProgressUpdate:
    update = ProgressUpdate(
        assignment_id=assignment_id,
        student_id=student_id,
        raw_message=raw_message,
        interpreted_status=interpreted_status,
        notes=notes,
    )
    db.add(update)
    db.flush()
    return update


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

def create_submission(
    db: Session,
    assignment_id: int,
    student_id: int,
    submission_type: str,
    text_content: Optional[str] = None,
    file_id: Optional[str] = None,
    file_url: Optional[str] = None,
    transcription: Optional[str] = None,
) -> Submission:
    submission = Submission(
        assignment_id=assignment_id,
        student_id=student_id,
        submission_type=submission_type,
        text_content=text_content,
        file_id=file_id,
        file_url=file_url,
        transcription=transcription,
    )
    db.add(submission)
    db.flush()
    update_assignment_status(db, assignment_id, "submitted")
    logger.info(f"Submission created for assignment {assignment_id}")
    return submission


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def save_feedback(
    db: Session,
    submission_id: int,
    teacher_id: int,
    raw_message: str,
    formatted_feedback: str,
) -> Feedback:
    feedback = Feedback(
        submission_id=submission_id,
        teacher_id=teacher_id,
        raw_message=raw_message,
        formatted_feedback=formatted_feedback,
    )
    db.add(feedback)
    # Mark assignment as reviewed
    submission = db.get(Submission, submission_id)
    if submission:
        update_assignment_status(db, submission.assignment_id, "reviewed")
    db.flush()
    return feedback


# ---------------------------------------------------------------------------
# Teacher's students list
# ---------------------------------------------------------------------------

def get_students_for_teacher(db: Session, teacher_id: int) -> list[User]:
    links = db.query(TeacherStudent).filter_by(teacher_id=teacher_id).all()
    return [link.student for link in links]
