"""Single-session engine. Transitions and limits are controlled only by Python."""
import time
from collections.abc import Callable
from datetime import datetime, timezone

from ai_core.evaluation.evaluator import AnswerEvaluator
from ai_core.interview.assessment import apply_evaluation
from ai_core.interview.decision_engine import Action, Decision, decide
from ai_core.interview.planner import CompetencyPlan, load_plan
from ai_core.interview.question_selector import QuestionGenerator, VERSION as QUESTION_VERSION
from ai_core.interview.schemas import CandidateAnswer, InterviewInput, Limits, Question, QuestionSpec
from ai_core.interview.state import InterviewState, Phase, SkillState
from ai_core.llm.base import LLMProvider
from ai_core.models import Level, QuestionType
from ai_core.interview.events import RuntimeEvent, Verification, utcnow
from ai_core.interview.integrity import observe

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
                 candidate_context: dict | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 trace_sink: Callable[[dict], None] | None = None,
                 checkpoint: Callable | None = None,
                 approved_primary_questions: bool = False):
        self.plan = plan or load_plan()
        config = config or InterviewInput()
        if config.role != self.plan.role:
            raise ValueError('Plan role does not match requested role')
        self.limits = limits or Limits()
        self.state = InterviewState(config=config, llm_provider=getattr(provider, 'name', None), limits=self.limits, plan_snapshot=self.plan.model_copy(deep=True),
                                    candidate_context=candidate_context or {}, skills=[
            SkillState(skill=s.id, target_level=config.target_level,
                       difficulty=list(Level).index(config.target_level) + 1)
            for s in self.plan.skills])
        self.evaluator = AnswerEvaluator(provider)
        self.generator = QuestionGenerator(provider, approved_primary_questions=approved_primary_questions)
        self.clock = clock
        self.started: float | None = None
        self.trace: list[dict] = []
        self.trace_sink = trace_sink
        self.checkpoint_sink = checkpoint
        if hasattr(provider, 'telemetry_sink'):
            def telemetry(metrics):
                self.record('llm_request', **metrics)
                self.checkpoint()
            provider.telemetry_sink = telemetry

    def checkpoint(self):
        self.state.updated_at = utcnow()
        if self.checkpoint_sink:
            self.checkpoint_sink(self)

    async def handle(self, event: RuntimeEvent, text: str | None = None):
        if any(e.id == event.id for e in self.state.events):
            return None
        if event.type in ('PASTE_DETECTED', 'COPY_DETECTED', 'FOCUS_LOST', 'FOCUS_RETURNED'):
            if self.state.phase != Phase.WAITING_FOR_ANSWER or event.question_id != self.state.questions[-1].id:
                raise ValueError('Event must reference the current question')
            if len(self.state.events) >= self.state.integrity_policy.max_events:
                if not self.state.events_truncated:
                    self.state.events_truncated = True
                    self.record('event_limit_reached')
                    self.checkpoint()
                return {'accepted': False, 'reason': 'event_limit'}
            event.timestamp = utcnow()
            self.state.events.append(event)
            signal = observe(self.state, event)
            self.record('runtime_event', type=event.type, question_id=event.question_id)
            if signal:
                self.record('integrity_signal_created', signal=signal.model_dump(mode='json'))
            self.checkpoint()
            return None
        if event.type == 'INTERVIEW_STARTED':
            return await self.start()
        if event.type == 'ANSWER_SUBMITTED':
            return await self.submit(event.question_id, text or '')
        if event.type == 'INTERVIEW_FINISH_REQUESTED':
            if self.state.phase != Phase.WAITING_FOR_ANSWER or self.state.pending_answer:
                raise ValueError('Finish requires an idle interview')
            self.complete()
            return None
        raise ValueError('Event is not supported by this interview mode')

    async def resume(self):
        """Continue from durable boundaries; completed evaluations are never repeated."""
        if self.state.phase == Phase.EVALUATE_ANSWER:
            return await self.evaluate_pending()
        if self.state.phase == Phase.DECIDE_NEXT_ACTION:
            return await self.advance()
        if self.state.phase == Phase.ASK_QUESTION and self.state.pending_spec:
            return await self.generate_pending()
        if self.state.phase == Phase.SELECT_SKILL:
            return await self.ask()
        return self.state.questions[-1] if self.state.phase == Phase.WAITING_FOR_ANSWER else None

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
        self.state.started_at = utcnow()
        self.state.events.append(RuntimeEvent(type='INTERVIEW_STARTED'))
        self.transition(Phase.INTRO)
        self.record('interview_started', config=self.state.config.model_dump(mode='json'),
                    plan_version=self.plan.version, limits=self.limits.model_dump())
        self.transition(Phase.SELECT_SKILL)
        self.checkpoint()
        return await self.ask()

    async def ask(self, decision: Decision | None = None) -> Question | None:
        if self.state.phase not in (Phase.SELECT_SKILL, Phase.FOLLOW_UP, Phase.NEXT_QUESTION):
            raise ValueError('Cannot ask a question in current state')
        if self.elapsed >= self.limits.time_budget_seconds:
            self.complete('time_budget')
            return None
        skill = self.state.skills[self.state.skill_index]
        competency = self.plan.skills[self.state.skill_index]
        if decision and decision.action in (Action.FOLLOW_UP, Action.VERIFICATION, Action.VERIFY_INTEGRITY):
            previous = self.state.questions[-1]
            spec = QuestionSpec(skill=skill.skill, difficulty=skill.difficulty,
                                type=QuestionType.VERIFICATION if decision.action in (Action.VERIFICATION, Action.VERIFY_INTEGRITY) else QuestionType.FOLLOW_UP,
                                goal=decision.goal, parent_id=previous.parent_id or previous.id,
                                misconception_id=decision.misconception_id)
            spec.action = decision.action.value
            target_id = decision.target_id or decision.misconception_id
            if target_id:
                kind = 'integrity' if decision.action == Action.VERIFY_INTEGRITY else 'misconception' if decision.misconception_id else 'knowledge'
                source = previous.id
                if kind == 'integrity':
                    signal = next(s for s in self.state.integrity_signals if s.id == target_id)
                    signal.verification_count += 1
                    source = signal.question_id
                if kind == 'knowledge':
                    next(c for c in self.state.contradictions if c.id == target_id).checked = True
                verification = Verification(kind=kind, target_id=target_id, source_question_id=source)
                self.state.verification_history.append(verification)
                spec.verification_id = verification.id
                self.record('verification_started', verification=verification.model_dump(mode='json'))
            self.state.follow_up_count += 1
        else:
            self.state.follow_up_count = 0
            index = skill.primary_questions % len(competency.goals)
            kind = QuestionType.DEBUGGING if skill.skill == 'engineering.debugging' else QuestionType.SCENARIO
            spec = QuestionSpec(skill=skill.skill, difficulty=skill.difficulty,
                                type=kind, goal=competency.goals[index])
        self.transition(Phase.ASK_QUESTION)
        self.state.pending_spec = spec
        self.checkpoint()
        return await self.generate_pending()

    async def generate_pending(self):
        if self.elapsed >= self.limits.time_budget_seconds:
            self.complete('time_budget')
            return None
        spec = self.state.pending_spec
        skill = self.state.skills[self.state.skill_index]
        competency = self.plan.skills[self.state.skill_index]
        verification = next((v for v in self.state.verification_history if v.id == spec.verification_id), None)
        source = next((t for t in self.state.turns if verification and t.question.id == verification.source_question_id), None)
        precomputed_follow_up_question = None
        if (spec.action == Action.FOLLOW_UP.value and self.state.next_action
                and self.state.next_action.get('reason') == 'specific_uncertainty'
                and self.state.turns):
            assessment = self.state.turns[-1].evaluation.result
            if assessment and assessment.follow_up_required and assessment.follow_up_goal == spec.goal:
                precomputed_follow_up_question = assessment.follow_up_question
        question = await self.generator.generate(
            spec, competency, self.state.config.target_level, self.state.questions,
            [e.model_dump(mode='json') for e in skill.evidence],
            [m.model_dump(mode='json') for m in skill.misconceptions], skill.primary_questions,
            {'action': spec.action, 'candidate_answer': source.answer.text if source else None,
             'verification': verification.model_dump(mode='json') if verification else None,
             'contradictions': [c.model_dump(mode='json') for c in self.state.contradictions if c.skill == skill.skill],
             'candidate_context': self.state.candidate_context},
            precomputed_follow_up_question=precomputed_follow_up_question)
        if self.elapsed >= self.limits.time_budget_seconds:
            self.complete('time_budget')
            return None
        self.state.questions.append(question)
        if verification:
            verification.question_id = question.id
        self.state.pending_spec = None
        self.state.pending_answer = None
        skill.status = 'IN_PROGRESS'
        skill.questions_asked += 1
        if not question.parent_id:
            skill.primary_questions += 1
        self.record('question_generated', question=question.model_dump(mode='json'),
                    prompt_version=QUESTION_VERSION)
        self.transition(Phase.WAITING_FOR_ANSWER)
        self.checkpoint()
        return question

    async def submit(self, question_id: str, text: str) -> Question | None:
        if self.state.phase != Phase.WAITING_FOR_ANSWER:
            raise ValueError('No answer is expected')
        question = self.state.questions[-1]
        if question_id != question.id:
            raise ValueError('Answer must reference the current question')
        answer = CandidateAnswer(question_id=question_id, text=text)
        self.state.pending_answer = answer
        self.state.events.append(RuntimeEvent(type='ANSWER_SUBMITTED', question_id=question_id))
        self.record('answer_received', answer=answer.model_dump(mode='json'))
        self.transition(Phase.EVALUATE_ANSWER)
        self.checkpoint()
        return await self.evaluate_pending()

    async def evaluate_pending(self):
        answer = self.state.pending_answer
        question = self.state.questions[-1]
        skill = self.state.skills[self.state.skill_index]
        misconception = next((m for m in skill.misconceptions if m.id == question.misconception_id), None)
        verification = next((v for v in self.state.verification_history if v.id == question.verification_id), None)
        attempt = await self.evaluator.evaluate(question, answer.text, self.state.config.target_level,
                                                [e.model_dump(mode='json') for e in skill.evidence],
                                                misconception.model_dump(mode='json') if misconception else None,
                                                [{'question_id': t.question.id, 'question': t.question.text, 'answer': t.answer.text}
                                                 for t in self.state.turns if t.question.skill == question.skill],
                                                verification.model_dump(mode='json') if verification else None,
                                                self.plan.skills[self.state.skill_index].evaluation_criteria)
        apply_evaluation(self.state, self.limits, question, answer, attempt, self.record)
        self.transition(Phase.DECIDE_NEXT_ACTION)
        self.state.next_action = None
        self.checkpoint()
        return await self.advance()

    async def advance(self):
        skill = self.state.skills[self.state.skill_index]
        result = self.state.turns[-1].evaluation.result if self.state.turns else None
        competency = self.plan.skills[self.state.skill_index]
        decision = Decision.model_validate(self.state.next_action) if self.state.next_action else decide(
            skill, result, self.limits, len(self.state.questions), self.elapsed,
            self.state.follow_up_count, min(competency.target_questions, len(competency.goals)), self.state)
        self.state.next_action = decision.model_dump(mode='json')
        self.record('decision', **self.state.next_action)
        self.checkpoint()
        if decision.action == Action.FINISH:
            self.complete(decision.reason)
            return None
        if decision.action == Action.NEXT_SKILL:
            skill.completed = True
            if skill.status != 'VERIFIED':
                skill.status = 'INSUFFICIENT_EVIDENCE'
            self.record('skill_completed', skill=skill.skill, reason=decision.reason)
            self.transition(Phase.NEXT_SKILL)
            self.state.skill_index += 1
            self.transition(Phase.SELECT_SKILL)
            if self.state.skill_index >= len(self.state.skills):
                self.complete('plan_completed')
                return None
            return await self.ask()
        self.transition(Phase.FOLLOW_UP if decision.action in (Action.FOLLOW_UP, Action.VERIFICATION, Action.VERIFY_INTEGRITY) else Phase.NEXT_QUESTION)
        return await self.ask(decision)

    def complete(self, reason: str = 'candidate_stopped') -> None:
        if reason == 'candidate_stopped':
            self.state.events.append(RuntimeEvent(type='INTERVIEW_FINISH_REQUESTED'))
        self.transition(Phase.FINAL_REVIEW)
        self.state.stop_reason = reason
        self.state.pending_answer = None
        self.state.pending_spec = None
        self.state.next_action = {'action': Action.FINISH.value, 'reason': reason}
        for skill in self.state.skills:
            if skill.status == 'IN_PROGRESS':
                skill.status = 'INSUFFICIENT_EVIDENCE'
        self.transition(Phase.COMPLETED)
        self.record('interview_completed', reason=reason)
        self.checkpoint()
