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


class RedFlagDraft(Model):
    index: int = Field(ge=0, le=3)
    quote: Text


class StarCheck(Model):
    situation: bool
    action: bool
    result: bool


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
    # Optional for assessments made before this field was introduced. The
    # engine still decides whether a follow-up is permitted.
    follow_up_question: str | None = None
    recommended_difficulty: int = Field(ge=1, le=5)
    verification_outcome: Literal['resolved', 'confirmed', 'uncertain'] = 'uncertain'
    # Template v2 only; legacy evaluations keep the defaults.
    anchor_level: int | None = Field(default=None, ge=1, le=5)
    red_flags: list[RedFlagDraft] = Field(default_factory=list, max_length=4)
    probe_index: int | None = Field(default=None, ge=0, le=2)
    star: StarCheck | None = None

    @model_validator(mode='after')
    def consistent(self):
        if self.follow_up_required and not self.follow_up_goal.strip():
            raise ValueError('Follow-up requires a concrete goal')
        if self.anchor_level is not None and not self.evidence:
            raise ValueError('Anchor level requires quoted evidence')
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


CARD_RESULT_FIELDS = ('anchor_level', 'red_flags', 'probe_index', 'star')


def evaluation_json_schema(*, cards: bool) -> dict:
    """Legacy questions never see the card fields, so they cannot fill them."""
    schema = EvaluationResult.model_json_schema()
    if not cards:
        for name in CARD_RESULT_FIELDS:
            schema['properties'].pop(name, None)
        for name in ('RedFlagDraft', 'StarCheck'):
            schema.get('$defs', {}).pop(name, None)
    return schema


class EvaluationAttempt(Model):
    provider: str | None = None
    model: str | None = None
    result: EvaluationResult | None = None
    status: Literal['evaluated', 'unavailable']
    attempts: int = Field(ge=1, le=2)
    prompt_version: str = 'answer_evaluator_v2'
    failures: list[str] = Field(default_factory=list)
