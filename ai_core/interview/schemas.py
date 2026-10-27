from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from ai_core.models import Level, Model, QuestionType, Text

MAX_INTERVIEW_SECONDS = 20 * 60


class InterviewInput(Model):
    role: Text = 'Python Backend Developer'
    target_level: Level = Level.MIDDLE


class Limits(Model):
    max_questions: int = Field(default=20, ge=1, le=50)
    max_questions_per_skill: int = Field(default=4, ge=1, le=10)
    max_follow_ups_per_question: int = Field(default=2, ge=0, le=3)
    minimum_evidence_per_skill: int = Field(default=2, ge=1, le=5)
    no_answer_primary_limit: int = Field(default=2, ge=1, le=5)
    time_budget_seconds: int = Field(default=MAX_INTERVIEW_SECONDS, ge=1, le=3600)


class QuestionSpec(Model):
    action: str = 'ASK_QUESTION'
    verification_id: str | None = None
    skill: Text
    difficulty: int = Field(ge=1, le=5)
    type: QuestionType
    goal: Text
    parent_id: str | None = None
    misconception_id: str | None = None
    # Template v2: the card this question belongs to and the approved probe used.
    card_index: int | None = Field(default=None, ge=0)
    probe_index: int | None = Field(default=None, ge=0)


class Question(QuestionSpec):
    id: str = Field(default_factory=lambda: uuid4().hex)
    text: Text
    generation: Literal['llm', 'fallback', 'scripted', 'approved_template'] = 'llm'
    # Template v2: 0 is the main wording, 1+ are card variants.
    variant: int | None = Field(default=None, ge=0)


class GeneratedQuestion(Model):
    text: Text


class CandidateAnswer(Model):
    question_id: Text
    text: str = Field(min_length=1, max_length=16000)

    @model_validator(mode='after')
    def nonblank(self):
        if not self.text.strip():
            raise ValueError('Answer must not be blank')
        return self
