"""Observable, bounded client events. No clipboard contents or AI-use inference."""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import Field
from ai_core.models import Model


def utcnow():
    return datetime.now(timezone.utc)


class RuntimeEvent(Model):
    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=100)
    type: Literal['INTERVIEW_STARTED', 'ANSWER_SUBMITTED', 'FOCUS_LOST', 'FOCUS_RETURNED',
                  'PASTE_DETECTED', 'COPY_DETECTED', 'QUESTION_TIMEOUT', 'CODING_SUBMITTED',
                  'INTERVIEW_FINISH_REQUESTED']
    question_id: str | None = Field(default=None, max_length=100)
    size: int = Field(default=0, ge=0, le=1000000)
    timestamp: datetime = Field(default_factory=utcnow)


class IntegrityPolicy(Model):
    large_paste_chars: int = Field(default=500, ge=1)
    max_events: int = Field(default=1000, ge=1)
    max_verifications_per_signal: int = Field(default=1, ge=1, le=3)


class IntegritySignal(Model):
    id: str = Field(default_factory=lambda: uuid4().hex)
    type: Literal['LARGE_PASTE', 'FOCUS_LOST_BEFORE_ANSWER']
    timestamp: datetime = Field(default_factory=utcnow)
    question_id: str
    context: dict = Field(default_factory=dict)
    severity: Literal['info', 'verification_required']
    resolved: bool = False
    verification_count: int = 0


class Verification(Model):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: Literal['integrity', 'knowledge', 'misconception']
    target_id: str
    source_question_id: str
    question_id: str | None = None
    outcome: Literal['PENDING', 'VERIFIED', 'UNCERTAIN', 'CONTRADICTED'] = 'PENDING'
    evidence_ids: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=utcnow)


class Contradiction(Model):
    id: str = Field(default_factory=lambda: uuid4().hex)
    skill: str
    question_id: str
    previous_question_id: str
    claim: str
    quote: str
    previous_quote: str
    status: Literal['unresolved', 'resolved', 'confirmed'] = 'unresolved'
    checked: bool = False
