import asyncio
import json

import pytest

from ai_core.tests.test_core import evaluation
from ai_core.interview.engine import InterviewEngine
from ai_core.interview.events import RuntimeEvent
from ai_core.interview.schemas import Limits
from ai_core.interview.state import InterviewState, Phase
from ai_core.interview.planner import load_plan
from ai_core.llm.provider import FakeLLMProvider
from ai_core.reports.generator import generate_report


def q(text):
    return json.dumps({'text':text})


def ev(**kwargs):
    return json.dumps(evaluation(**kwargs))


def test_full_scripted_runtime_and_report():
    wrong = ev(correctness='incorrect', depth='low',
               evidence=[{'type':'negative','claim':'Wrong lifetime','quote':'every call'}],
               misconceptions=[{'claim':'New default every call','quote':'every call'}])
    provider = FakeLLMProvider([q('First?'), ev(), q('Second?'), wrong, q('Clarify?'),
        ev(verification_outcome='resolved'), q('Next skill?'), ev(), q('Explain pasted answer?'),
        ev(verification_outcome='resolved')])
    plan = load_plan().model_copy(deep=True)
    plan.skills = plan.skills[:2]
    async def run():
        engine = InterviewEngine(provider, plan=plan)
        question = await engine.handle(RuntimeEvent(type='INTERVIEW_STARTED'))
        question = await engine.handle(RuntimeEvent(type='ANSWER_SUBMITTED', question_id=question.id), 'created once')
        assert len(engine.state.skills[0].evidence) == 1
        assert engine.state.skills[0].status == 'IN_PROGRESS'
        question = await engine.submit(question.id, 'every call')
        assert question.action == 'FOLLOW_UP'
        question = await engine.submit(question.id, 'created once')
        assert engine.state.skills[0].misconceptions[0].status == 'resolved'
        assert engine.state.skills[0].completed
        assert engine.state.skills[0].status == 'VERIFIED'
        event = RuntimeEvent(type='PASTE_DETECTED', question_id=question.id, size=900)
        await engine.handle(event)
        await engine.handle(event)
        assert len(engine.state.integrity_signals) == 1
        assert not engine.state.skills[1].evidence
        question = await engine.submit(question.id, 'created once')
        assert question.action == 'VERIFY_INTEGRITY'
        # Recovery is a new engine instance from the JSON persistence contract.
        restored = InterviewEngine(provider, plan=plan)
        restored.state = InterviewState.model_validate_json(engine.state.model_dump_json())
        restored.started = engine.started
        question = await restored.submit(question.id, 'created once')
        assert question is None
        assert restored.state.phase == Phase.COMPLETED
        assert restored.state.integrity_signals[0].resolved
        assert restored.state.verification_history[-1].outcome == 'VERIFIED'
        report = generate_report(restored.state, mode='scripted_test')
        assert report['integrity']['signals'][0]['resolved']
        assert len(report['integrity']['verifications']) == 2
        assert all(s['evidence'] for s in report['skills'])
        assert all(s.completed for s in restored.state.skills)
    asyncio.run(run())


@pytest.mark.parametrize('outcome', ['confirmed', 'uncertain', 'unavailable'])
def test_failed_verification_never_resolves_signal(outcome):
    result = ev(correctness='incorrect', depth='low', verification_outcome=outcome,
                evidence=[{'type':'negative','quote':'wrong','claim':'Explicit wrong assertion'}]) if outcome != 'unavailable' else None
    provider = FakeLLMProvider([q('Question?'), ev(), q('Explain?')] + ([result] if result else []))
    async def run():
        engine = InterviewEngine(provider, limits=Limits(max_questions=2))
        question = await engine.start()
        await engine.handle(RuntimeEvent(type='PASTE_DETECTED', question_id=question.id, size=900))
        question = await engine.submit(question.id, 'created once')
        await engine.submit(question.id, 'wrong')
        assert not engine.state.integrity_signals[0].resolved
        assert engine.state.verification_history[0].outcome == ('CONTRADICTED' if outcome == 'confirmed' else 'UNCERTAIN')
        assert len(engine.state.skills[0].evidence) == (1 if outcome == 'unavailable' else 2)
    asyncio.run(run())


def test_no_answer_has_no_misconception_even_after_paste():
    async def run():
        engine = InterviewEngine(FakeLLMProvider([q('Question?'), q('Explain?')]))
        question = await engine.start()
        await engine.handle(RuntimeEvent(type='PASTE_DETECTED', question_id=question.id, size=900))
        question = await engine.submit(question.id, 'не знаю')
        assert not engine.state.skills[0].misconceptions
        assert not engine.state.skills[0].evidence
        assert question.action == 'VERIFY_INTEGRITY'
    asyncio.run(run())


@pytest.mark.parametrize('boundary', ['answer', 'evaluation', 'decision', 'generation'])
def test_checkpoint_restore_does_not_repeat_completed_evaluation(boundary):
    saved = []
    class Crash(Exception):
        pass
    def checkpoint(engine):
        saved.append(engine.state.model_dump_json())
        state = engine.state
        matches = {'answer':state.phase == Phase.EVALUATE_ANSWER,
                   'evaluation':state.phase == Phase.DECIDE_NEXT_ACTION and state.next_action is None,
                   'decision':state.phase == Phase.DECIDE_NEXT_ACTION and state.next_action is not None,
                   'generation':state.phase == Phase.ASK_QUESTION and bool(state.turns)}
        if matches[boundary]:
            raise Crash()
    async def run():
        provider = FakeLLMProvider([q('First?'), ev(), q('Second?')])
        engine = InterviewEngine(provider)
        question = await engine.start()
        engine.checkpoint_sink = checkpoint
        with pytest.raises(Crash):
            await engine.submit(question.id, 'created once')
        restored = InterviewEngine(provider)
        restored.state = InterviewState.model_validate_json(saved[-1])
        restored.started = engine.started
        await restored.resume()
        assert len(restored.state.turns) == 1
        assert len(restored.state.skills[0].evidence) == 1
        assert len(restored.state.questions) == 2
        assert restored.state.pending_answer is None
        assert len([c for c in provider.calls if 'answer' in c['payload']]) == 1
    asyncio.run(run())


def test_contradiction_grounding_priority_and_resolution():
    async def run():
        provider = FakeLLMProvider([q('First?'), ev(), q('Second?')])
        engine = InterviewEngine(provider)
        first = await engine.start()
        second = await engine.submit(first.id, 'created once')
        contradictory = ev(contradictions=[{'previous_question_id':first.id, 'previous_quote':'created once',
                                            'quote':'created once', 'claim':'Conflicting explicit claims'}])
        provider.responses = iter([contradictory, q('Clarify contradiction?'), ev(verification_outcome='resolved'), q('Next?')])
        question = await engine.submit(second.id, 'created once')
        assert question.action == 'VERIFY_KNOWLEDGE'
        await engine.submit(question.id, 'created once')
        assert engine.state.contradictions[0].status == 'resolved'
        assert engine.state.verification_history[0].outcome == 'VERIFIED'
    asyncio.run(run())


def test_priority_integrity_over_misconception_and_no_skill_penalty():
    async def run():
        wrong = ev(correctness='incorrect', depth='low',
                   evidence=[{'type':'negative','claim':'Wrong','quote':'wrong'}],
                   misconceptions=[{'claim':'Wrong','quote':'wrong'}])
        engine = InterviewEngine(FakeLLMProvider([q('First?'), wrong, q('Explain?')]))
        question = await engine.start()
        await engine.handle(RuntimeEvent(type='PASTE_DETECTED', question_id=question.id, size=900))
        question = await engine.submit(question.id, 'wrong')
        assert question.action == 'VERIFY_INTEGRITY'
        assert len(engine.state.skills[0].evidence) == 1
        assert engine.state.skills[0].evidence[0].source == 'answer'
    asyncio.run(run())


def test_unsupported_cross_answer_quote_is_rejected():
    from ai_core.evaluation.evaluator import AnswerEvaluator
    from ai_core.tests.test_core import question
    from ai_core.models import Level
    raw = ev(contradictions=[{'previous_question_id':'old', 'previous_quote':'invented',
                              'quote':'created once', 'claim':'Conflicting claims'}])
    provider = FakeLLMProvider([raw, raw])
    result = asyncio.run(AnswerEvaluator(provider).evaluate(question(), 'created once', Level.MIDDLE, [],
                         previous_answers=[{'question_id':'old', 'answer':'actual earlier answer'}]))
    assert result.status == 'unavailable'
    assert result.result is None


def test_integrity_then_contradiction_then_misconception_priority_and_limits():
    from ai_core.interview.events import IntegritySignal, Contradiction
    from ai_core.interview.decision_engine import decide
    from ai_core.evidence.models import Misconception
    async def run():
        engine = InterviewEngine(FakeLLMProvider([q('First?'), ev(), q('Second?')]))
        first = await engine.start()
        await engine.submit(first.id, 'created once')
        state = engine.state
        skill = state.skills[0]
        skill.misconceptions.append(Misconception(skill=skill.skill, claim='wrong', quote='created once', question_id=first.id))
        state.contradictions.append(Contradiction(skill=skill.skill, question_id=first.id,
            previous_question_id='old', claim='conflict', quote='created once', previous_quote='before'))
        state.integrity_signals.append(IntegritySignal(type='LARGE_PASTE', question_id=first.id, severity='verification_required'))
        def choose(total=2):
            return decide(skill, state.turns[-1].evaluation.result, engine.limits, total, 0, 0, 3, state).action
        assert choose() == 'VERIFY_INTEGRITY'
        assert choose(20) == 'COMPLETE_INTERVIEW'
        state.integrity_signals[0].resolved = True
        assert choose() == 'VERIFY_KNOWLEDGE'
        state.contradictions[0].status = 'resolved'
        assert choose() == 'FOLLOW_UP'
    asyncio.run(run())


def test_expired_pending_generation_does_not_call_provider():
    class Crash(Exception):
        pass
    now = [0.0]
    saved = []
    def checkpoint(engine):
        if engine.state.phase == Phase.ASK_QUESTION:
            saved.append(engine.state.model_dump_json())
            raise Crash()
    async def run():
        provider = FakeLLMProvider([])
        engine = InterviewEngine(provider, clock=lambda:now[0], checkpoint=checkpoint)
        with pytest.raises(Crash):
            await engine.start()
        restored = InterviewEngine(provider, clock=lambda:now[0])
        restored.state = InterviewState.model_validate_json(saved[-1])
        restored.started = 0.0
        now[0] = 1801
        await restored.resume()
        assert restored.state.phase == Phase.COMPLETED
        assert restored.state.stop_reason == 'time_budget'
        assert not provider.calls
    asyncio.run(run())
