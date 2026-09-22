import asyncio
import json

import pytest
from pydantic import ValidationError

from ai_core.evaluation.evaluator import AnswerEvaluator
from ai_core.evaluation.schemas import EvaluationResult
from ai_core.interview.decision_engine import Action, decide, next_difficulty
from ai_core.interview.engine import InterviewEngine
from ai_core.interview.planner import load_plan
from ai_core.interview.schemas import InterviewInput, Limits, Question
from ai_core.interview.state import Phase, SkillState
from ai_core.llm.base import ProviderError
from ai_core.llm.provider import FakeLLMProvider, OfflineProvider
from ai_core.models import Level
from ai_core.reports.generator import generate_report


def evaluation(**overrides):
    value = {'correctness': 'correct', 'depth': 'high',
             'evidence': [{'type': 'positive', 'claim': 'Объяснена причина', 'quote': 'created once'}],
             'follow_up_required': False, 'recommended_difficulty': 4}
    value.update(overrides)
    return value


def question():
    return Question(skill='python.core', difficulty=3, type='scenario', goal='mutability', text='Explain?')


def test_schema_forbids_engine_actions_and_unjustified_results():
    with pytest.raises(ValidationError):
        EvaluationResult(**evaluation(action='NEXT_SKILL'))
    with pytest.raises(ValidationError):
        EvaluationResult(**evaluation(evidence=[]))
    with pytest.raises(ValidationError):
        EvaluationResult(**evaluation(follow_up_required=True))
    with pytest.raises(ValidationError):
        Limits(max_questions=0)
    with pytest.raises(ValidationError):
        InterviewInput(role='Unknown profession')


def test_quote_hallucination_retries_entire_assessment():
    fake = FakeLLMProvider([json.dumps(evaluation()), json.dumps(evaluation())])
    result = asyncio.run(AnswerEvaluator(fake).evaluate(question(), 'The value is recreated on every call', Level.MIDDLE, []))
    assert result.status == 'unavailable'
    assert result.result is None
    assert len(fake.calls) == 2


def test_invalid_json_then_valid_result():
    fake = FakeLLMProvider(['not json', json.dumps(evaluation())])
    result = asyncio.run(AnswerEvaluator(fake).evaluate(question(), 'created once', Level.MIDDLE, []))
    assert result.status == 'evaluated'
    assert result.attempts == 2
    assert fake.calls[0]['payload']['answer'] == 'created once'
    assert 'created once' not in fake.calls[0]['system']


def test_transport_failure_preserves_answer_and_no_fake_evidence():
    async def scenario():
        engine = InterviewEngine(OfflineProvider(), limits=Limits(max_questions=1))
        q = await engine.start()
        assert q.generation == 'fallback'
        assert await engine.submit(q.id, 'unknown') is None
        assert engine.state.turns[0].answer.text == 'unknown'
        assert engine.state.turns[0].evaluation.status == 'unavailable'
        report = generate_report(engine.state, mode='offline_preview')
        assert all(s['demonstrated_level'] is None and not s['evidence'] for s in report['skills'])
        assert report['stop_reason'] == 'max_questions'
        assert [e['event'] for e in engine.trace].index('answer_received') < [e['event'] for e in engine.trace].index('evaluation_completed')
    asyncio.run(scenario())


def test_verification_resolves_only_targeted_misconception():
    wrong = evaluation(correctness='incorrect', depth='low',
                       evidence=[{'type':'negative', 'claim':'Ошибочная модель', 'quote':'automatic parallelism'}],
                       misconceptions=[{'claim':'automatic parallelism', 'quote':'automatic parallelism'}])
    fixed = evaluation(verification_outcome='resolved')
    fake = FakeLLMProvider([json.dumps({'text':'Initial question?'}), json.dumps(wrong),
                            json.dumps({'text':'Explain the CPU-bound example?'}), json.dumps(fixed)])
    async def scenario():
        engine = InterviewEngine(fake, limits=Limits(max_questions=2))
        q = await engine.start()
        follow_up = await engine.submit(q.id, 'automatic parallelism')
        assert follow_up.type == 'follow_up'
        assert follow_up.parent_id == q.id
        misconception = engine.state.skills[0].misconceptions[0]
        assert follow_up.misconception_id == misconception.id
        assert follow_up.difficulty == 2
        assert await engine.submit(follow_up.id, 'created once') is None
        assert misconception.status == 'resolved'
        assert misconception.verification_question_id == follow_up.id
        assert len(engine.state.skills[0].evidence) == 2
        assert any(e['event'] == 'decision' and e['action'] == 'FOLLOW_UP' for e in engine.trace)
    asyncio.run(scenario())


def test_follow_up_limit_forces_new_question():
    partial = EvaluationResult(**evaluation(correctness='partial', follow_up_required=True,
                                            follow_up_goal='Проверить срок жизни объекта'))
    state = SkillState(skill='python.core', target_level=Level.MIDDLE, questions_asked=2, primary_questions=1)
    d = decide(state, partial, Limits(), 2, 0, 2, 3)
    assert d.action == Action.NEXT_QUESTION
    d = decide(state, partial, Limits(), 2, 0, 1, 3)
    assert d.action == Action.FOLLOW_UP
    assert d.goal == partial.follow_up_goal


@pytest.mark.parametrize(('total','elapsed','asked','expected'), [
    (20,0,1,Action.FINISH), (2,1800,1,Action.FINISH), (4,0,4,Action.NEXT_SKILL)])
def test_limits_override_model_follow_up(total, elapsed, asked, expected):
    state = SkillState(skill='python.core', target_level=Level.MIDDLE, questions_asked=asked)
    result = EvaluationResult(**evaluation(follow_up_required=True, follow_up_goal='Specific goal'))
    assert decide(state, result, Limits(), total, elapsed, 0, 3).action == expected


def test_many_bullets_from_one_answer_do_not_verify_skill():
    from ai_core.evidence.service import collect
    result = EvaluationResult(**evaluation(evidence=[
        {'type':'positive', 'claim':f'Claim {i}', 'quote':'created once'} for i in range(5)]))
    evidence, _ = collect(question(), result)
    state = SkillState(skill='python.core', target_level=Level.MIDDLE,
                       questions_asked=1, primary_questions=1, evidence=evidence)
    assert decide(state, result, Limits(), 1, 0, 0, 3).action == Action.NEXT_QUESTION


def test_difficulty_does_not_blindly_follow_model_suggestion():
    result = EvaluationResult(**evaluation(recommended_difficulty=1))
    assert next_difficulty(3, result) == 4
    assert next_difficulty(5, result) == 5
    assert next_difficulty(2, None) == 2


def test_state_machine_rejects_skip_duplicate_and_wrong_question():
    async def scenario():
        engine = InterviewEngine(OfflineProvider(), limits=Limits(max_questions=1))
        with pytest.raises(ValueError):
            engine.transition(Phase.COMPLETED)
        with pytest.raises(ValueError):
            generate_report(engine.state, mode='offline_preview')
        q = await engine.start()
        with pytest.raises(ValueError):
            await engine.start()
        with pytest.raises(ValueError):
            await engine.submit('wrong-id', 'answer')
        with pytest.raises(ValueError):
            await engine.submit(q.id, '   ')
        assert engine.state.phase == Phase.WAITING_FOR_ANSWER
        await engine.submit(q.id, 'answer')
        with pytest.raises(ValueError):
            await engine.submit(q.id, 'answer')
    asyncio.run(scenario())


def test_offline_full_plan_terminates_covers_all_skills():
    async def scenario():
        engine = InterviewEngine(OfflineProvider())
        q = await engine.start()
        while q:
            q = await engine.submit(q.id, 'Not sure')
        assert engine.state.stop_reason == 'plan_completed'
        assert {t.question.skill for t in engine.state.turns} == {s.id for s in load_plan().skills}
        assert len(engine.state.questions) <= engine.limits.max_questions
        assert len({q.text for q in engine.state.questions}) == len(engine.state.questions)
    asyncio.run(scenario())


def test_elapsed_budget_stops_after_current_answer():
    now = [0.0]
    async def scenario():
        engine = InterviewEngine(OfflineProvider(), clock=lambda: now[0])
        q = await engine.start()
        now[0] = 1801
        assert await engine.submit(q.id, 'Answer preserved') is None
        assert engine.state.stop_reason == 'time_budget'
        assert len(engine.state.turns) == 1
    asyncio.run(scenario())


def test_unexpected_programming_errors_are_not_hidden():
    fake = FakeLLMProvider([RuntimeError('bug')])
    with pytest.raises(RuntimeError):
        asyncio.run(AnswerEvaluator(fake).evaluate(question(), 'answer', Level.MIDDLE, []))


def test_provider_failure_logs_no_candidate_text(caplog):
    fake = FakeLLMProvider([ProviderError('secret'), ProviderError('secret')])
    asyncio.run(AnswerEvaluator(fake).evaluate(question(), 'private answer', Level.MIDDLE, []))
    assert 'evaluation_failed' in caplog.text
    assert 'private answer' not in caplog.text
    assert 'secret' not in caplog.text
