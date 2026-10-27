"""Template v2: reviewed question cards, approved probes and anchored points."""
import asyncio
import json

import pytest

from ai_core.evaluation.evaluator import AnswerEvaluator
from ai_core.evaluation.schemas import EvaluationAttempt, EvaluationResult
from ai_core.interview.engine import InterviewEngine
from ai_core.interview.events import RuntimeEvent
from ai_core.interview.planner import CompetencyPlan, plan_json_schema
from ai_core.interview.schemas import CandidateAnswer, InterviewInput, Limits, Question
from ai_core.interview.state import Phase, Turn
from ai_core.llm.provider import FakeLLMProvider
from ai_core.models import Level
from ai_core.reports.answer_review import review_card_answer
from ai_core.reports.generator import generate_report

CARD = {'goal': 'Проверить действия при расхождении цены', 'type': 'situational',
        'question': 'Цена на кассе отличается от ценника. Что сделаете?',
        'variants': ['Касса пробивает цену выше ценника. Что сделаете?'],
        'probes': ['Что скажете покупателю?'],
        'anchors': {'strong': 'Проверяет цену и объясняет покупателю', 'acceptable': 'Проверяет цену',
                    'weak': 'Меняет цену сам'},
        'red_flags': ['Самовольно меняет цену']}
STAR = {'goal': 'Проверить надёжность', 'type': 'behavioral',
        'question': 'Расскажите о случае, когда мешали обстоятельства. Что вы сделали?',
        'probes': ['Что именно сделали лично вы?', 'Чем всё закончилось?'],
        'anchors': {'strong': 'Предупредил и выполнил', 'acceptable': 'Общими словами',
                    'weak': 'Подвёл без предупреждения'}}
PLAN = {'role': 'Продавец-кассир', 'version': 'profession-test-v2', 'not_assessed': ['Акцент'],
        'skills': [{'id': 'cash.price', 'name': 'Цена', 'concepts': ['Цена'], 'cards': [CARD]},
                   {'id': 'cash.reliability', 'name': 'Надёжность', 'concepts': ['Обязательства'],
                    'cards': [STAR]}]}
FULL_STAR = {'situation': True, 'action': True, 'result': True}


def evaluation(level=None, quote='проверю цену', probe=None, star=None, flags=(),
               correctness='partial'):
    return json.dumps({'correctness': correctness, 'depth': 'medium',
                       'evidence': [{'type': 'positive', 'claim': 'Названо действие', 'quote': quote}] if level else [],
                       'follow_up_required': probe is not None, 'follow_up_goal': '',
                       'probe_index': probe, 'anchor_level': level, 'star': star,
                       'red_flags': [{'index': index, 'quote': text} for index, text in flags],
                       'recommended_difficulty': 3}, ensure_ascii=False)


def make_engine(provider, max_questions=4):
    return InterviewEngine(provider, config=InterviewInput(role='Продавец-кассир', target_level=Level.JUNIOR),
                           limits=Limits(max_questions=max_questions, max_follow_ups_per_question=1),
                           plan=CompetencyPlan.model_validate(PLAN), clock=lambda: 0,
                           approved_primary_questions=True)


def answer(engine, question, text):
    return asyncio.run(engine.handle(RuntimeEvent(type='ANSWER_SUBMITTED', question_id=question.id), text))


def test_cards_derive_legacy_fields_and_reject_inconsistent_plans():
    plan = CompetencyPlan.model_validate(PLAN)
    skill = plan.skills[0]
    assert skill.goals == [CARD['goal']] and skill.questions == [CARD['question']]
    assert skill.evaluation_criteria == [CARD['anchors']['strong']] and skill.target_questions == 1
    assert CompetencyPlan.model_validate_json(plan.model_dump_json()) == plan
    legacy = {'id': 'old', 'name': 'Old', 'concepts': ['x'], 'goals': ['g'], 'questions': ['q'],
              'target_questions': 1}
    with pytest.raises(ValueError):
        CompetencyPlan.model_validate({**PLAN, 'skills': [PLAN['skills'][0], legacy]})
    with pytest.raises(ValueError):
        CompetencyPlan.model_validate({**PLAN, 'skills': [
            {**PLAN['skills'][0], 'cards': [{**CARD, 'variants': [CARD['question']]}]}]})
    assert 'cards' not in json.dumps(plan_json_schema())
    assert 'cards' in json.dumps(plan_json_schema(cards=True))


def test_card_interview_uses_approved_wordings_probes_and_anchor_points():
    provider = FakeLLMProvider([
        evaluation(level=3, probe=0),
        evaluation(level=5, quote='объясню покупателю', correctness='correct'),
        evaluation(level=4, quote='предупредил начальника', star={**FULL_STAR, 'result': False},
                   correctness='correct')])
    engine = make_engine(provider)
    first = asyncio.run(engine.handle(RuntimeEvent(type='INTERVIEW_STARTED')))
    wordings = [CARD['question'], *CARD['variants']]
    assert first.text == wordings[first.variant] and first.generation == 'approved_template'
    probe = answer(engine, first, 'Я проверю цену у старшего')
    assert (probe.text, probe.parent_id, probe.card_index) == (CARD['probes'][0], first.id, 0)
    assert probe.generation == 'approved_template'
    behavioral = answer(engine, probe, 'Сначала объясню покупателю, что проверяю цену')
    assert behavioral.text == STAR['question'] and behavioral.type == 'behavioral'
    assert answer(engine, behavioral, 'Я заранее предупредил начальника и вышел позже') is None
    assert engine.state.phase == Phase.COMPLETED
    # No model wrote a question: every call evaluated an answer against its card.
    assert [call['operation'] for call in provider.calls] == ['evaluation'] * 3
    assert provider.calls[0]['payload']['question_card']['not_assessed'] == ['Акцент']
    assert provider.calls[1]['payload']['parent_turn']['answer'] == 'Я проверю цену у старшего'
    report = generate_report(engine.state, mode='live')
    assert report['template_format'] == 2 and report['scoring_rubric']['version'] == 'anchored_points_v1'
    assert [(s['skill'], s['points'], s['answers']) for s in report['card_scores']] == [
        ('cash.price', 5, 2), ('cash.reliability', 4, 1)]
    assert [skill['score'] for skill in report['skills']] == [5.0, 4.0]


def test_probes_never_displace_planned_cards():
    engine = make_engine(FakeLLMProvider([
        evaluation(level=3, probe=0),
        evaluation(level=5, quote='предупредил', star=FULL_STAR, probe=1, correctness='correct')]),
        max_questions=2)
    first = asyncio.run(engine.handle(RuntimeEvent(type='INTERVIEW_STARTED')))
    second = answer(engine, first, 'Я проверю цену')
    assert second.text == STAR['question'] and second.parent_id is None
    # The limit is reached exactly when the last card is answered: the plan is complete.
    assert answer(engine, second, 'Я предупредил заранее') is None
    assert engine.state.stop_reason == 'plan_completed'


def test_wording_is_stable_per_interview_and_rotates_across_interviews():
    seen = set()
    for index in range(12):
        texts = []
        for _ in range(2):
            engine = make_engine(FakeLLMProvider([]))
            engine.state.interview_id = f'interview-{index}'
            texts.append(asyncio.run(engine.handle(RuntimeEvent(type='INTERVIEW_STARTED'))).text)
        assert texts[0] == texts[1]
        seen.add(texts[0])
    assert seen == {CARD['question'], *CARD['variants']}


def test_card_evaluator_enforces_anchor_star_probes_and_grounded_red_flags():
    plan = CompetencyPlan.model_validate(PLAN)
    price = plan.skills[0].cards[0].evaluator_view(plan.not_assessed)
    question = Question(skill='cash.price', difficulty=3, type='scenario', goal=CARD['goal'],
                        text=CARD['question'], card_index=0)

    def run(responses, text, card=price, asked=question):
        return asyncio.run(AnswerEvaluator(FakeLLMProvider(responses)).evaluate(
            asked, text, Level.JUNIOR, [], card=card))

    # No anchor level, then a red flag quote that the candidate never said.
    rejected = run([evaluation(level=None), evaluation(level=2, quote='сам поменяю', flags=[(0, 'скидку дам')])],
                   'Я сам поменяю цену')
    assert rejected.status == 'unavailable'
    assert rejected.failures == ['unsupported_evidence', 'unsupported_evidence']
    flagged = run([evaluation(level=1, quote='сам поменяю', flags=[(0, 'сам поменяю цену')], probe=2)],
                  'Я сам поменяю цену')
    assert flagged.result.anchor_level == 1 and flagged.result.red_flags[0].index == 0
    # The card has one probe, so index 2 cannot become a follow-up.
    assert flagged.result.probe_index is None and not flagged.result.follow_up_required
    assert flagged.prompt_version == 'card_evaluator_v1'

    star_card = plan.skills[1].cards[0].evaluator_view([])
    behavioral = Question(skill='cash.reliability', difficulty=3, type='behavioral', goal=STAR['goal'],
                          text=STAR['question'], card_index=0)
    hypothetical = run([evaluation(level=4, quote='я бы предупредил', probe=2,
                                   star={'situation': False, 'action': False, 'result': False})],
                       'Наверное, я бы предупредил', star_card, behavioral)
    assert hypothetical.result.anchor_level is None and hypothetical.result.probe_index is None
    asked_for_action = run([evaluation(level=4, quote='я бы предупредил', probe=0,
                                       star={'situation': True, 'action': False, 'result': False})],
                           'Был случай, и я бы предупредил', star_card, behavioral)
    assert asked_for_action.result.probe_index == 0
    assert asked_for_action.result.follow_up_goal == STAR['probes'][0]
    missing_star = run([evaluation(level=4, quote='предупредил')] * 2, 'Я предупредил', star_card, behavioral)
    assert missing_star.status == 'unavailable'


def test_red_flag_caps_points_and_answer_without_own_action_is_not_scored():
    plan = CompetencyPlan.model_validate(PLAN)

    def turn(card_index, skill, text, **result):
        question = Question(skill=skill, difficulty=3, type='scenario', goal='g', text='q', card_index=card_index)
        evaluated = EvaluationResult(correctness='partial', depth='medium', follow_up_required=False,
                                     recommended_difficulty=3, **result)
        return Turn(question=question, answer=CandidateAnswer(question_id=question.id, text=text),
                    evaluation=EvaluationAttempt(status='evaluated', attempts=1, result=evaluated))

    evidence = [{'type': 'positive', 'claim': 'Проверяет цену', 'quote': 'сам поменяю'}]
    flagged = review_card_answer(
        turn(0, 'cash.price', 'Я сам поменяю цену', evidence=evidence, anchor_level=4,
             red_flags=[{'index': 0, 'quote': 'сам поменяю'}]),
        plan.skills[0].cards[0], plan.not_assessed)
    assert flagged['points'] == 2 and flagged['anchor']['level'] == 4
    assert flagged['red_flags'] == [{'claim': CARD['red_flags'][0], 'quote': 'сам поменяю'}]
    assert flagged['not_assessed'] == ['Акцент']
    no_action = review_card_answer(
        turn(0, 'cash.reliability', 'Мы как-то справились', evidence=[
            {'type': 'uncertain', 'claim': 'Нет личных действий', 'quote': 'Мы как-то справились'}],
            star={'situation': True, 'action': False, 'result': True}),
        plan.skills[1].cards[0], plan.not_assessed)
    assert no_action['points'] is None and no_action['status'] == 'not_assessed'
    assert not no_action['strengths']
