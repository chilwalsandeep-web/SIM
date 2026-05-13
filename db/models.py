"""
db/models.py
SQLAlchemy ORM models for Classroom Companion.
"""

from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, Column, ForeignKey, Integer,
    String, Text, DateTime, UniqueConstraint
)
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True)
    telegram_id     = Column(BigInteger, unique=True, nullable=False, index=True)
    telegram_handle = Column(String(255), nullable=True)
    full_name       = Column(String(255), nullable=True)
    role            = Column(String(10), nullable=False)   # 'teacher' | 'student'
    created_at      = Column(DateTime, default=datetime.utcnow)

    # Relationships
    invite_codes_created  = relationship("InviteCode", foreign_keys="InviteCode.teacher_id", back_populates="teacher")
    invite_codes_used     = relationship("InviteCode", foreign_keys="InviteCode.used_by",    back_populates="redeemer")
    students_linked       = relationship("TeacherStudent", foreign_keys="TeacherStudent.teacher_id", back_populates="teacher")
    teacher_linked        = relationship("TeacherStudent", foreign_keys="TeacherStudent.student_id", back_populates="student")
    assignments_given     = relationship("Assignment", foreign_keys="Assignment.teacher_id",  back_populates="teacher")
    assignments_received  = relationship("Assignment", foreign_keys="Assignment.student_id",  back_populates="student")
    progress_updates      = relationship("ProgressUpdate", back_populates="student")
    submissions           = relationship("Submission",      back_populates="student")
    reminders             = relationship("Reminder",        back_populates="student")
    agent_logs            = relationship("AgentLog",        back_populates="user")

    def __repr__(self):
        return f"<User id={self.id} role={self.role} handle={self.telegram_handle}>"

    @property
    def is_teacher(self):
        return self.role == "teacher"

    @property
    def is_student(self):
        return self.role == "student"


# ---------------------------------------------------------------------------
# Invite Codes
# ---------------------------------------------------------------------------

class InviteCode(Base):
    __tablename__ = "invite_codes"

    id          = Column(Integer, primary_key=True)
    code        = Column(String(20), unique=True, nullable=False, index=True)
    teacher_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    used_by     = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_used     = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
    expires_at  = Column(DateTime, nullable=True)

    # Relationships
    teacher     = relationship("User", foreign_keys=[teacher_id], back_populates="invite_codes_created")
    redeemer    = relationship("User", foreign_keys=[used_by],    back_populates="invite_codes_used")

    def __repr__(self):
        return f"<InviteCode code={self.code} used={self.is_used}>"

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at


# ---------------------------------------------------------------------------
# Teacher ↔ Student relationship
# ---------------------------------------------------------------------------

class TeacherStudent(Base):
    __tablename__ = "teacher_students"
    __table_args__ = (UniqueConstraint("teacher_id", "student_id"),)

    id          = Column(Integer, primary_key=True)
    teacher_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    student_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    linked_at   = Column(DateTime, default=datetime.utcnow)

    # Relationships
    teacher     = relationship("User", foreign_keys=[teacher_id], back_populates="students_linked")
    student     = relationship("User", foreign_keys=[student_id], back_populates="teacher_linked")

    def __repr__(self):
        return f"<TeacherStudent teacher={self.teacher_id} student={self.student_id}>"


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

class Assignment(Base):
    __tablename__ = "assignments"

    id              = Column(Integer, primary_key=True)
    teacher_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    student_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    title           = Column(String(255), nullable=True)       # LLM-extracted short title
    description     = Column(Text, nullable=False)             # Full assignment text
    raw_instruction = Column(Text, nullable=True)              # Original teacher message verbatim
    due_date        = Column(DateTime, nullable=False)
    status          = Column(String(20), default="pending")    # pending | in_progress | submitted | reviewed
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    teacher         = relationship("User",           foreign_keys=[teacher_id], back_populates="assignments_given")
    student         = relationship("User",           foreign_keys=[student_id], back_populates="assignments_received")
    progress_updates = relationship("ProgressUpdate", back_populates="assignment", order_by="ProgressUpdate.created_at")
    submissions     = relationship("Submission",     back_populates="assignment")
    reminders       = relationship("Reminder",       back_populates="assignment")
    agent_logs      = relationship("AgentLog",       back_populates="assignment")

    def __repr__(self):
        return f"<Assignment id={self.id} title={self.title} status={self.status}>"

    @property
    def is_overdue(self):
        return datetime.utcnow() > self.due_date and self.status not in ("submitted", "reviewed")

    @property
    def hours_until_due(self):
        delta = self.due_date - datetime.utcnow()
        return delta.total_seconds() / 3600


# ---------------------------------------------------------------------------
# Progress Updates
# ---------------------------------------------------------------------------

class ProgressUpdate(Base):
    __tablename__ = "progress_updates"

    id                  = Column(Integer, primary_key=True)
    assignment_id       = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    student_id          = Column(Integer, ForeignKey("users.id"),       nullable=False)
    raw_message         = Column(Text, nullable=True)           # Original student message
    interpreted_status  = Column(String(50), nullable=True)     # started | in_progress | stuck | completed
    notes               = Column(Text, nullable=True)           # LLM summary of the update
    created_at          = Column(DateTime, default=datetime.utcnow)

    # Relationships
    assignment  = relationship("Assignment",   back_populates="progress_updates")
    student     = relationship("User",         back_populates="progress_updates")

    def __repr__(self):
        return f"<ProgressUpdate assignment={self.assignment_id} status={self.interpreted_status}>"


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------

class Submission(Base):
    __tablename__ = "submissions"

    id              = Column(Integer, primary_key=True)
    assignment_id   = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    student_id      = Column(Integer, ForeignKey("users.id"),       nullable=False)
    submission_type = Column(String(10), nullable=False)   # 'text' | 'file' | 'photo' | 'voice'
    text_content    = Column(Text, nullable=True)          # for text submissions
    file_id         = Column(String(255), nullable=True)   # Telegram file_id
    file_url        = Column(Text, nullable=True)          # stored/downloaded URL
    transcription   = Column(Text, nullable=True)          # voice → text (Whisper)
    submitted_at    = Column(DateTime, default=datetime.utcnow)

    # Relationships
    assignment  = relationship("Assignment", back_populates="submissions")
    student     = relationship("User",       back_populates="submissions")
    feedback    = relationship("Feedback",   back_populates="submission", uselist=False)

    def __repr__(self):
        return f"<Submission id={self.id} type={self.submission_type} assignment={self.assignment_id}>"


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

class Feedback(Base):
    __tablename__ = "feedback"

    id                  = Column(Integer, primary_key=True)
    submission_id       = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    teacher_id          = Column(Integer, ForeignKey("users.id"),       nullable=False)
    raw_message         = Column(Text, nullable=True)       # Original teacher message
    formatted_feedback  = Column(Text, nullable=True)       # LLM-polished version sent to student
    given_at            = Column(DateTime, default=datetime.utcnow)

    # Relationships
    submission  = relationship("Submission", back_populates="feedback")
    teacher     = relationship("User")

    def __repr__(self):
        return f"<Feedback id={self.id} submission={self.submission_id}>"


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

class Reminder(Base):
    __tablename__ = "reminders"

    id              = Column(Integer, primary_key=True)
    assignment_id   = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    student_id      = Column(Integer, ForeignKey("users.id"),       nullable=False)
    reminder_type   = Column(String(20), nullable=True)    # 'gentle' | 'regular' | 'urgent' | 'final'
    message_sent    = Column(Text, nullable=True)
    sent_at         = Column(DateTime, default=datetime.utcnow)

    # Relationships
    assignment  = relationship("Assignment", back_populates="reminders")
    student     = relationship("User",       back_populates="reminders")

    def __repr__(self):
        return f"<Reminder id={self.id} type={self.reminder_type} assignment={self.assignment_id}>"


# ---------------------------------------------------------------------------
# Agent Logs
# ---------------------------------------------------------------------------

class AgentLog(Base):
    __tablename__ = "agent_logs"

    id              = Column(Integer, primary_key=True)
    agent_name      = Column(String(50), nullable=True)    # intent_router | teacher_agent | student_agent | reminder_agent | summariser
    input_text      = Column(Text, nullable=True)
    output_text     = Column(Text, nullable=True)
    user_id         = Column(Integer, ForeignKey("users.id"),       nullable=True)
    assignment_id   = Column(Integer, ForeignKey("assignments.id"), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user        = relationship("User",       back_populates="agent_logs")
    assignment  = relationship("Assignment", back_populates="agent_logs")

    def __repr__(self):
        return f"<AgentLog agent={self.agent_name} user={self.user_id}>"
