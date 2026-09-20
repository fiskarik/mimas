import asyncio
import json
import pytest

from ai_core.evaluation.evaluator import AnswerEvaluator
from ai_core.interview.engine import InterviewEngine
from ai_core.interview.planner import load_plan
from ai_core.interview.question_selector import QuestionGenerator
from ai_core.interview.schemas import Question, QuestionSpec
from ai_core.llm.provider import FakeLLMProvider
from ai_core.models import Level


@pytest.mark.parametrize('answer', ['я не знаю', 'я не умею', 'хз', 'спросите у професиналов'])
def test_abstention_is_not_a_false_technical_belief(answer):
    provider = FakeLLMProvider([])
    q = Question(skill='python.core', difficulty=3, type='scenario', goal='Default arguments', text='When is the value created?')
    result = asyncio.run(AnswerEvaluator(provider).evaluate(q, answer, Level.MIDDLE, []))
    assert result.result.correctness == 'insufficient_evidence'
    assert not result.result.misconceptions
    assert not result.result.evidence
    assert not result.result.follow_up_required
    assert not provider.calls


def test_off_topic_normalization_drops_invented_misconception():
    raw = {'response_kind':'off_topic','correctness':'incorrect','depth':'low',
           'misconceptions':[{'claim':'Believes this is a solution','quote':'banana'}],
           'evidence':[{'type':'negative','claim':'Wrong answer','quote':'banana'}],
           'follow_up_required':True,'follow_up_goal':'Demand full solution','recommended_difficulty':1}
    q = Question(skill='python.core',difficulty=3,type='scenario',goal='A',text='Question?')
    result = asyncio.run(AnswerEvaluator(FakeLLMProvider([json.dumps(raw)])).evaluate(q,'banana',Level.MIDDLE,[]))
    assert result.result.response_kind == 'off_topic'
    assert result.result.correctness == 'insufficient_evidence'
    assert not result.result.misconceptions


def test_overloaded_question_retries_then_uses_reviewed_bank():
    raw = json.dumps({'text':'1. Explain defaults?\n2. Implement a context manager?\n3. Write tests?'})
    provider = FakeLLMProvider([raw,raw])
    skill = load_plan().skills[0]
    q = asyncio.run(QuestionGenerator(provider).generate(
        QuestionSpec(skill=skill.id,difficulty=1,type='scenario',goal=skill.goals[0]),
        skill,Level.MIDDLE,[],[],[],0))
    assert q.generation == 'fallback'
    assert 'concepts' not in provider.calls[0]['payload']
    assert q.text == skill.questions[0]


def test_refusal_moves_to_another_goal_not_repeated_demand():
    async def scenario():
        provider = FakeLLMProvider([json.dumps({'text':'Когда создаётся значение по умолчанию?'}),
                                    json.dumps({'text':'Когда генератор выполняет свой код?'})])
        engine = InterviewEngine(provider)
        first = await engine.start()
        second = await engine.submit(first.id,'я не знаю')
        assert second.parent_id is None
        assert second.goal != first.goal
        assert second.difficulty == 2
        assert not engine.state.skills[0].misconceptions
    asyncio.run(scenario())


def test_failure_trace_has_safe_error_category():
    provider=FakeLLMProvider(['bad JSON','bad JSON'])
    q=Question(skill='python.core',difficulty=3,type='scenario',goal='A',text='Question?')
    result=asyncio.run(AnswerEvaluator(provider).evaluate(q,'A substantive answer',Level.MIDDLE,[]))
    assert result.failures == ['invalid_output','invalid_output']
    assert result.prompt_version == 'answer_evaluator_v2'


def test_mutability_answer_not_downgraded_for_unrelated_test_requirement():
    bad={'correctness':'partial','depth':'medium','missing_concepts':['тест с контекст-менеджером'],
         'evidence':[{'type':'positive','claim':'Understands defaults','quote':'once'}],
         'follow_up_required':True,'follow_up_goal':'Напишите тест','recommended_difficulty':3}
    good={**bad,'correctness':'correct','missing_concepts':[], 'follow_up_required':False,'follow_up_goal':''}
    provider=FakeLLMProvider([json.dumps(bad),json.dumps(good)])
    q=Question(skill='python.core',difficulty=3,type='scenario',goal='Проверить изменяемый аргумент по умолчанию',text='Explain and write a context manager test?')
    result=asyncio.run(AnswerEvaluator(provider).evaluate(q,'once',Level.MIDDLE,[]))
    assert result.status=='evaluated'
    assert result.attempts==2
    assert result.result.correctness=='correct'


def test_follow_up_evaluator_receives_previous_code():
    answer='assert b == []'
    result={'correctness':'incorrect','depth':'low',
            'evidence':[{'type':'negative','claim':'The list contains a','quote':answer}],
            'follow_up_required':False,'recommended_difficulty':2}
    provider=FakeLLMProvider([json.dumps({'text':'Как исправить общий список?'}),
                              json.dumps({'correctness':'partial','depth':'medium',
                                          'evidence':[{'type':'positive','claim':'New list','quote':'return [x]'}],
                                          'follow_up_required':True,'follow_up_goal':'Проверить содержимое возвращаемого списка','recommended_difficulty':3}),
                              json.dumps({'text':'Что содержит список после append_item("a")?'}),json.dumps(result),
                              json.dumps({'text':'Когда выполняется генератор?'})])
    async def scenario():
        engine=InterviewEngine(provider)
        q=await engine.start()
        q=await engine.submit(q.id,'def append_item(x): return [x]')
        await engine.submit(q.id,answer)
        calls=[c for c in provider.calls if 'previous_answers_for_context_only' in c['payload']]
        assert calls[-1]['payload']['previous_answers_for_context_only'][0]['answer']=='def append_item(x): return [x]'
    asyncio.run(scenario())


def test_static_materialization_contradiction_cannot_be_marked_correct():
    from ai_core.evaluation.code_checks import check_materialization
    from ai_core.evaluation.schemas import EvaluationResult
    answer='Без сохранения в список: consumed = list(itertools.islice(g, 1000))'
    result=EvaluationResult(correctness='correct',depth='high',
        evidence=[{'type':'positive','claim':'No list storage','quote':'list(itertools.islice(g, 1000))'}],
        follow_up_required=False,recommended_difficulty=3)
    checked=check_materialization(result,answer)
    assert checked.correctness=='partial'
    assert any(e.type=='negative' and e.quote in answer for e in checked.evidence)
    assert not any(e.type=='positive' for e in checked.evidence)


def test_rate_limit_is_visible_and_not_retried_immediately():
    from ai_core.llm.base import ProviderError
    provider=FakeLLMProvider([ProviderError('Groq rate limit','rate_limit')])
    q=Question(skill='python.core',difficulty=3,type='scenario',goal='A',text='Question?')
    result=asyncio.run(AnswerEvaluator(provider).evaluate(q,'A substantive answer',Level.MIDDLE,[]))
    assert result.failures==['rate_limit']
    assert result.attempts==1
    assert len(provider.calls)==1


def test_legacy_question_scoping_preserves_code_and_core_task():
    from ai_core.evaluation.normalization import scoped_question_text
    original='def f(x=[]): pass\n1. Почему изменяемый аргумент общий?\n2. Как исправить?\n3. Напишите тест с контекст-менеджером.'
    scoped=scoped_question_text(original,'Проверить изменяемый аргумент по умолчанию')
    assert 'def f' in scoped and 'Как исправить' in scoped
    assert 'контекст' not in scoped
