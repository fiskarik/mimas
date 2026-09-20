"""Single-session engine. Transitions and limits are controlled only by Python."""
import time
from collections.abc import Callable
from datetime import datetime, timezone

from ai_core.evaluation.evaluator import AnswerEvaluator
from ai_core.evidence.service import collect
from ai_core.interview.decision_engine import Action, Decision, decide, next_difficulty
from ai_core.interview.planner import CompetencyPlan, load_plan
from ai_core.interview.question_selector import QuestionGenerator, VERSION as QUESTION_VERSION
from ai_core.interview.schemas import CandidateAnswer, InterviewInput, Limits, Question, QuestionSpec
from ai_core.interview.state import InterviewState, Phase, SkillState, Turn
from ai_core.llm.base import LLMProvider
from ai_core.models import Level, QuestionType

TRANSITIONS = {
    Phase.CREATED: {Phase.INTRO}, Phase.INTRO: {Phase.SELECT_SKILL},
    Phase.SELECT_SKILL: {Phase.ASK_QUESTION, Phase.FINAL_REVIEW},
    Phase.ASK_QUESTION: {Phase.WAITING_FOR_ANSWER, Phase.FINAL_REVIEW},
    Phase.WAITING_FOR_ANSWER: {Phase.EVALUATE_ANSWER, Phase.FINAL_REVIEW},
    Phase.EVALUATE_ANSWER: {Phase.DECIDE_NEXT_ACTION},
    Phase.DECIDE_NEXT_ACTION: {Phase.FOLLOW_UP, Phase.NEXT_QUESTION, Phase.NEXT_SKILL, Phase.FINAL_REVIEW},
    Phase.FOLLOW_UP: {Phase.ASK_QUESTION, Phase.FINAL_REVIEW},
    Phase.NEXT_QUESTION: {Phase.ASK_QUESTION, Phase.FINAL_REVIEW},
    Phase.NEXT_SKILL: {Phase.SELECT_SKILL},
    Phase.FINAL_REVIEW: {Phase.COMPLETED}, Phase.COMPLETED: set(),
}


class InterviewEngine:
    def __init__(self, provider: LLMProvider, config: InterviewInput | None = None,
                 limits: Limits | None = None, plan: CompetencyPlan | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 trace_sink: Callable[[dict], None] | None = None):
        self.plan = plan or load_plan()
        config = config or InterviewInput()
        if config.role != self.plan.role:
            raise ValueError('Plan role does not match requested role')
        self.limits = limits or Limits()
        self.state = InterviewState(config=config, skills=[
            SkillState(skill=s.id, target_level=config.target_level,
                       difficulty=list(Level).index(config.target_level) + 1)
            for s in self.plan.skills])
        self.evaluator = AnswerEvaluator(provider)
        self.generator = QuestionGenerator(provider)
        self.clock = clock
        self.started: float | None = None
        self.trace: list[dict] = []
        self.trace_sink = trace_sink

    @property
    def elapsed(self) -> float:
        return 0 if self.started is None else self.clock() - self.started

    def record(self, event: str, **details) -> None:
        item = {'event': event, 'created_at': datetime.now(timezone.utc).isoformat(),
                'phase': self.state.phase.value, **details}
        self.trace.append(item)
        if self.trace_sink:
            self.trace_sink(item)

    def transition(self, phase: Phase) -> None:
        if phase not in TRANSITIONS[self.state.phase]:
            raise ValueError(f'Invalid transition {self.state.phase} -> {phase}')
        self.state.phase = phase
        self.record('transition')

    async def start(self) -> Question | None:
        if self.state.phase != Phase.CREATED:
            raise ValueError('Interview already started')
        self.started = self.clock()
        self.transition(Phase.INTRO)
        self.record('interview_started', config=self.state.config.model_dump(mode='json'),
                    plan_version=self.plan.version, limits=self.limits.model_dump())
        self.transition(Phase.SELECT_SKILL)
        return await self.ask()

    async def ask(self, decision: Decision | None = None) -> Question | None:
        if self.state.phase not in (Phase.SELECT_SKILL, Phase.FOLLOW_UP, Phase.NEXT_QUESTION):
            raise ValueError('Cannot ask a question in current state')
        if self.elapsed >= self.limits.time_budget_seconds:
            self.complete('time_budget')
            return None
        skill = self.state.skills[self.state.skill_index]
        competency = self.plan.skills[self.state.skill_index]
        if decision and decision.action in (Action.FOLLOW_UP, Action.VERIFICATION):
            previous = self.state.questions[-1]
            spec = QuestionSpec(skill=skill.skill, difficulty=skill.difficulty,
                                type=QuestionType.VERIFICATION if decision.action == Action.VERIFICATION else QuestionType.FOLLOW_UP,
                                goal=decision.goal, parent_id=previous.parent_id or previous.id,
                                misconception_id=decision.misconception_id)
            self.state.follow_up_count += 1
        else:
            self.state.follow_up_count = 0
            index = skill.primary_questions % len(competency.goals)
            kind = QuestionType.DEBUGGING if skill.skill == 'engineering.debugging' else QuestionType.SCENARIO
            spec = QuestionSpec(skill=skill.skill, difficulty=skill.difficulty,
                                type=kind, goal=competency.goals[index])
        self.transition(Phase.ASK_QUESTION)
        question = await self.generator.generate(
            spec, competency, self.state.config.target_level, self.state.questions,
            [e.model_dump(mode='json') for e in skill.evidence],
            [m.model_dump(mode='json') for m in skill.misconceptions], skill.primary_questions)
        if self.elapsed >= self.limits.time_budget_seconds:
            self.complete('time_budget')
            return None
        self.state.questions.append(question)
        skill.questions_asked += 1
        if not question.parent_id:
            skill.primary_questions += 1
        self.record('question_generated', question=question.model_dump(mode='json'),
                    prompt_version=QUESTION_VERSION)
        self.transition(Phase.WAITING_FOR_ANSWER)
        return question

    async def submit(self, question_id: str, text: str) -> Question | None:
        if self.state.phase != Phase.WAITING_FOR_ANSWER:
            raise ValueError('No answer is expected')
        question = self.state.questions[-1]
        if question_id != question.id:
            raise ValueError('Answer must reference the current question')
        answer = CandidateAnswer(question_id=question_id, text=text)
        skill = self.state.skills[self.state.skill_index]
        self.record('answer_received', answer=answer.model_dump(mode='json'))
        self.transition(Phase.EVALUATE_ANSWER)
        misconception = next((m for m in skill.misconceptions if m.id == question.misconception_id), None)
        attempt = await self.evaluator.evaluate(question, answer.text, self.state.config.target_level,
                                                [e.model_dump(mode='json') for e in skill.evidence],
                                                misconception.model_dump(mode='json') if misconception else None,
                                                [{'question': t.question.text, 'answer': t.answer.text}
                                                 for t in self.state.turns if t.question.skill == question.skill][-2:])
        self.state.turns.append(Turn(question=question, answer=answer, evaluation=attempt))
        self.record('evaluation_completed', question_id=question.id, evaluation=attempt.model_dump(mode='json'))
        result = attempt.result
        if result:
            evidence, new_misconceptions = collect(question, result)
            skill.evidence.extend(evidence)
            for item in evidence:
                self.record('evidence_created', evidence=item.model_dump(mode='json'))
            if misconception:
                if result.verification_outcome != 'uncertain':
                    misconception.status = result.verification_outcome
                misconception.verification_question_id = question.id
                self.record('misconception_checked', misconception=misconception.model_dump(mode='json'))
            for item in new_misconceptions:
                if not any(m.claim == item.claim for m in skill.misconceptions):
                    skill.misconceptions.append(item)
                    self.record('misconception_detected', misconception=item.model_dump(mode='json'))
            skill.difficulty = next_difficulty(skill.difficulty, result)
        self.transition(Phase.DECIDE_NEXT_ACTION)
        competency = self.plan.skills[self.state.skill_index]
        decision = decide(skill, result, self.limits, len(self.state.questions), self.elapsed,
                          self.state.follow_up_count, min(competency.target_questions, len(competency.goals)))
        self.record('decision', **decision.model_dump(mode='json'))
        if decision.action == Action.FINISH:
            self.complete(decision.reason)
            return None
        if decision.action == Action.NEXT_SKILL:
            skill.completed = True
            self.record('skill_completed', skill=skill.skill, reason=decision.reason)
            self.transition(Phase.NEXT_SKILL)
            self.state.skill_index += 1
            self.transition(Phase.SELECT_SKILL)
            if self.state.skill_index >= len(self.state.skills):
                self.complete('plan_completed')
                return None
            return await self.ask()
        self.transition(Phase.FOLLOW_UP if decision.action in (Action.FOLLOW_UP, Action.VERIFICATION) else Phase.NEXT_QUESTION)
        return await self.ask(decision)

    def complete(self, reason: str = 'candidate_stopped') -> None:
        self.transition(Phase.FINAL_REVIEW)
        self.state.stop_reason = reason
        self.transition(Phase.COMPLETED)
        self.record('interview_completed', reason=reason)
