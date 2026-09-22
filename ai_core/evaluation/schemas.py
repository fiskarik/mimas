from typing import Literal

from pydantic import Field, model_validator

from ai_core.models import EvidenceType, Model, Text


class EvidenceDraft(Model):
    type: EvidenceType
    claim: Text
    quote: Text


class MisconceptionDraft(Model):
    claim: Text
    quote: Text


class ContradictionDraft(Model):
    previous_question_id: Text
    previous_quote: Text
    quote: Text
    claim: Text


class EvaluationResult(Model):
    contradictions: list[ContradictionDraft] = Field(default_factory=list, max_length=3)
    response_kind: Literal['substantive', 'no_answer', 'off_topic'] = 'substantive'
    correctness: Literal['correct', 'partial', 'incorrect', 'insufficient_evidence']
    depth: Literal['low', 'medium', 'high']
    demonstrated_concepts: list[Text] = Field(default_factory=list, max_length=12)
    missing_concepts: list[Text] = Field(default_factory=list, max_length=12)
    misconceptions: list[MisconceptionDraft] = Field(default_factory=list, max_length=5)
    evidence: list[EvidenceDraft] = Field(default_factory=list, max_length=8)
    follow_up_required: bool
    follow_up_goal: str = Field(default='', max_length=1500)
    recommended_difficulty: int = Field(ge=1, le=5)
    verification_outcome: Literal['resolved', 'confirmed', 'uncertain'] = 'uncertain'

    @model_validator(mode='after')
    def consistent(self):
        if self.follow_up_required and not self.follow_up_goal.strip():
            raise ValueError('Follow-up requires a concrete goal')
        if self.correctness == 'correct' and not any(e.type == 'positive' for e in self.evidence):
            raise ValueError('Correct answer requires positive evidence')
        if self.correctness == 'incorrect' and not any(e.type == 'negative' for e in self.evidence):
            raise ValueError('Incorrect answer requires negative evidence')
        if self.misconceptions and not any(e.type == 'negative' for e in self.evidence):
            raise ValueError('Misconception requires negative evidence')
        if self.verification_outcome == 'resolved' and not any(e.type == 'positive' for e in self.evidence):
            raise ValueError('Resolved misconception requires positive evidence')
        if self.verification_outcome == 'confirmed' and not any(e.type == 'negative' for e in self.evidence):
            raise ValueError('Confirmed misconception requires negative evidence')
        return self


class EvaluationAttempt(Model):
    provider: str | None = None
    model: str | None = None
    result: EvaluationResult | None = None
    status: Literal['evaluated', 'unavailable']
    attempts: int = Field(ge=1, le=2)
    prompt_version: str = 'answer_evaluator_v2'
    failures: list[str] = Field(default_factory=list)
