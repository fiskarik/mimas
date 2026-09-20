from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import Field

from ai_core.models import EvidenceType, Model, Text


class SkillEvidence(Model):
    id: str = Field(default_factory=lambda: uuid4().hex)
    skill: Text
    source: Literal['answer', 'follow_up', 'verification', 'debugging', 'coding', 'code_explanation']
    type: EvidenceType
    claim: Text
    quote: Text
    question_id: Text
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Misconception(Model):
    id: str = Field(default_factory=lambda: uuid4().hex)
    skill: Text
    claim: Text
    quote: Text
    question_id: Text
    status: Literal['unresolved', 'resolved', 'confirmed'] = 'unresolved'
    verification_question_id: str | None = None
