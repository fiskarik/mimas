from enum import StrEnum

from pydantic import Field

from ai_core.evaluation.schemas import EvaluationAttempt
from ai_core.evidence.models import Misconception, SkillEvidence
from ai_core.interview.schemas import CandidateAnswer, InterviewInput, Question
from ai_core.models import Level, Model


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


class Turn(Model):
    question: Question
    answer: CandidateAnswer
    evaluation: EvaluationAttempt


class InterviewState(Model):
    config: InterviewInput
    phase: Phase = Phase.CREATED
    skill_index: int = 0
    skills: list[SkillState]
    questions: list[Question] = Field(default_factory=list)
    turns: list[Turn] = Field(default_factory=list)
    follow_up_count: int = 0
    stop_reason: str | None = None
