from enum import StrEnum

from pydantic import Field

from ai_core.evaluation.schemas import EvaluationAttempt
from ai_core.evidence.models import Misconception, SkillEvidence
from ai_core.interview.schemas import CandidateAnswer, InterviewInput, Question
from ai_core.models import Level, Model
from ai_core.interview.events import RuntimeEvent, IntegritySignal, IntegrityPolicy, Verification, Contradiction, utcnow
from ai_core.interview.schemas import Limits, QuestionSpec
from datetime import datetime
from uuid import uuid4
from ai_core.interview.planner import CompetencyPlan


class Phase(StrEnum):
    CREATED = 'CREATED'
    INTRO = 'INTRO'
    SELECT_SKILL = 'SELECT_SKILL'
    ASK_QUESTION = 'ASK_QUESTION'
    WAITING_FOR_ANSWER = 'WAITING_FOR_ANSWER'
    EVALUATE_ANSWER = 'EVALUATE_ANSWER'
    DECIDE_NEXT_ACTION = 'DECIDE_NEXT_ACTION'
    FOLLOW_UP = 'FOLLOW_UP'
    NEXT_QUESTION = 'NEXT_QUESTION'
    NEXT_SKILL = 'NEXT_SKILL'
    FINAL_REVIEW = 'FINAL_REVIEW'
    COMPLETED = 'COMPLETED'


class SkillState(Model):
    skill: str
    target_level: Level
    questions_asked: int = 0
    primary_questions: int = 0
    difficulty: int = 3
    evidence: list[SkillEvidence] = Field(default_factory=list)
    misconceptions: list[Misconception] = Field(default_factory=list)
    completed: bool = False
    status: str = 'NOT_STARTED'
    current_level: Level | None = None
    confidence: float = 0.0


class Turn(Model):
    question: Question
    answer: CandidateAnswer
    evaluation: EvaluationAttempt


class InterviewState(Model):
    llm_provider: str | None = None
    plan_snapshot: CompetencyPlan | None = None
    candidate_context: dict = Field(default_factory=dict)
    events_truncated: bool = False
    interview_id: str = Field(default_factory=lambda: uuid4().hex)
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)
    limits: Limits = Field(default_factory=Limits)
    integrity_policy: IntegrityPolicy = Field(default_factory=IntegrityPolicy)
    events: list[RuntimeEvent] = Field(default_factory=list)
    integrity_signals: list[IntegritySignal] = Field(default_factory=list)
    verification_history: list[Verification] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    pending_answer: CandidateAnswer | None = None
    pending_spec: QuestionSpec | None = None
    next_action: dict | None = None
    config: InterviewInput
    phase: Phase = Phase.CREATED
    skill_index: int = 0
    skills: list[SkillState]
    questions: list[Question] = Field(default_factory=list)
    turns: list[Turn] = Field(default_factory=list)
    follow_up_count: int = 0
    stop_reason: str | None = None
