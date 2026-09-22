import importlib
import json
import sys

import pytest
from fastapi.testclient import TestClient

from ai_core.llm.provider import FakeLLMProvider


@pytest.fixture
def setup_ai(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setenv('COMPANY_KEY','test-team')
    monkeypatch.delenv('DATABASE_URL',raising=False)
    sys.modules.pop('backend.app',None)
    module=importlib.import_module('backend.app')
    provider=FakeLLMProvider([json.dumps({'text':'Когда создаётся значение по умолчанию?'}),
                              json.dumps({'text':'Когда выполняется тело генератора?'})])
    provider.model='test-model'
    monkeypatch.setattr('backend.ai_web.create_llm_provider',lambda **kwargs:provider)
    with TestClient(module.app) as client:
        yield client,module
    module.database.engine.dispose()


def create(client):
    response=client.post('/api/ai/sessions',headers={'X-Company-Key':'test-team'},json={})
    assert response.status_code==200
    access=response.json()
    return '/api/ai/sessions/'+access['id'], {'X-Interview-Token':access['token']}


def test_ai_web_auth_resume_idempotency_and_report(setup_ai):
    client,module=setup_ai
    assert client.post('/api/ai/sessions',json={}).status_code==401
    base,headers=create(client)
    assert client.get(base).status_code==401
    first=client.post(base+'/start',headers=headers,json={}).json()
    assert first['current_question']
    assert client.post(base+'/start',headers=headers,json={}).json()['current_question']['id']==first['current_question']['id']
    body={'question_id':first['current_question']['id'],'text':'я не знаю'}
    next=client.post(base+'/answers',headers=headers,json=body).json()
    assert len(next['answers'])==1
    assert next['current_question']['text'] != first['current_question']['text']
    assert 'goal' not in next['current_question']
    assert client.post(base+'/answers',headers=headers,json=body).json()==next
    assert client.post(base+'/answers',headers=headers,json={**body,'text':'changed'}).status_code==409
    # Fetch restores the persisted session, not an in-memory engine instance.
    assert client.get(base,headers=headers).json()==next
    report=client.post(base+'/finish',headers=headers,json={}).json()['report']
    assert report['skills'][0]['demonstrated_level'] is None
    assert not report['skills'][0]['evidence']
    assert client.post(base+'/answers',headers=headers,json={'question_id':next['current_question']['id'],'text':'late'}).status_code==409


def test_pending_answer_survives_unexpected_failure_and_can_retry(setup_ai,monkeypatch):
    client,module=setup_ai
    base,headers=create(client)
    first=client.post(base+'/start',headers=headers,json={}).json()
    broken=FakeLLMProvider([RuntimeError('programming failure')]);broken.model='test-model'
    monkeypatch.setattr('backend.ai_web.create_llm_provider',lambda **kwargs:broken)
    body={'question_id':first['current_question']['id'],'text':'An explanation'}
    with pytest.raises(RuntimeError):
        client.post(base+'/answers',headers=headers,json=body)
    stored=client.get(base,headers=headers).json()
    assert stored['pending_answer']==body
    assert client.post(base+'/finish',headers=headers,json={}).status_code==409
    healthy=FakeLLMProvider([]);healthy.model='test-model'
    monkeypatch.setattr('backend.ai_web.create_llm_provider',lambda **kwargs:healthy)
    result=client.post(base+'/answers',headers=headers,json=body).json()
    assert result['pending_answer'] is None
    assert len(result['answers'])==1
    assert 'provider_error' in result['evaluation_notice']


def test_events_are_scoped_idempotent_private_and_persisted(setup_ai):
    from backend.ai_web import AISession
    from ai_core.interview.state import InterviewState
    client, module = setup_ai
    base, headers = create(client)
    current = client.post(base+'/start', headers=headers, json={}).json()['current_question']
    event = {'id':'paste-1', 'type':'PASTE_DETECTED', 'question_id':current['id'], 'size':900}
    assert client.post(base+'/events', json=event).status_code == 401
    assert client.post(base+'/events', headers=headers, json={**event, 'question_id':'wrong'}).status_code == 409
    for _ in range(2):
        assert client.post(base+'/events', headers=headers, json=event).status_code == 200
    public = client.get(base, headers=headers).json()
    assert 'integrity_signals' not in public
    assert 'confidence' not in json.dumps(public)
    with module.database.session() as db:
        state = InterviewState.model_validate_json(db.get(AISession, base.rsplit('/',1)[1]).state)
    assert len(state.integrity_signals) == 1
    assert state.integrity_signals[0].context['size'] == 900
    report = client.post(base+'/finish', headers=headers, json={}).json()['report']
    assert len(report['integrity']['signals']) == 1
    assert not report['integrity']['signals'][0]['resolved']
    assert client.post(base+'/events', headers=headers, json={**event, 'id':'late'}).status_code == 409


def test_api_recovers_after_question_generation_crash_without_reevaluation(setup_ai, monkeypatch):
    from ai_core.tests.test_core import evaluation
    client, module = setup_ai
    base, headers = create(client)
    current = client.post(base+'/start', headers=headers, json={}).json()['current_question']
    provider = FakeLLMProvider([json.dumps(evaluation()), RuntimeError('generation crash')])
    provider.model = 'test-model'
    monkeypatch.setattr('backend.ai_web.create_llm_provider', lambda **kwargs:provider)
    body = {'question_id':current['id'], 'text':'created once'}
    with pytest.raises(RuntimeError):
        client.post(base+'/answers', headers=headers, json=body)
    saved = client.get(base, headers=headers).json()
    assert saved['resume_required']
    assert len(saved['answers']) == 1
    provider.responses = iter([json.dumps({'text':'Recovered question?'})])
    recovered = client.post(base+'/start', headers=headers, json={}).json()
    assert not recovered['resume_required']
    assert recovered['pending_answer'] is None
    assert len(recovered['answers']) == 1
    assert len([c for c in provider.calls if 'answer' in c['payload']]) == 1


def test_event_limit_acknowledges_drop_and_does_not_block_finish(setup_ai):
    from backend.ai_web import AISession
    from ai_core.interview.state import InterviewState
    client, module = setup_ai
    base, headers = create(client)
    current = client.post(base+'/start', headers=headers, json={}).json()['current_question']
    with module.database.session(write=True) as db:
        row = db.get(AISession, base.rsplit('/', 1)[1])
        state = InterviewState.model_validate_json(row.state)
        state.integrity_policy.max_events = 1
        row.state = state.model_dump_json()
    result = client.post(base+'/events', headers=headers, json={
        'type':'FOCUS_LOST', 'question_id':current['id'], 'id':'over-cap'})
    assert result.status_code == 200
    assert result.json()['accepted'] is False
    assert result.json()['reason'] == 'event_limit'
    response = client.post(base+'/finish', headers=headers, json={})
    assert response.status_code == 200
    assert response.json()['report']['integrity']['events_truncated']


def test_existing_session_uses_saved_plan_after_deployment(setup_ai, monkeypatch):
    client, module = setup_ai
    base, headers = create(client)
    current = client.post(base+'/start', headers=headers, json={}).json()['current_question']
    def changed_plan():
        raise AssertionError('Active session must not load a newly deployed plan')
    monkeypatch.setattr('ai_core.interview.engine.load_plan', changed_plan)
    response = client.post(base+'/answers', headers=headers,
                           json={'question_id':current['id'], 'text':'не знаю'})
    assert response.status_code == 200
    assert response.json()['current_question']


def test_transient_provider_failure_keeps_pending_then_resumes_once(setup_ai, monkeypatch):
    from ai_core.llm.base import ProviderError
    from ai_core.tests.test_core import evaluation
    client, module = setup_ai
    base, headers = create(client)
    current = client.post(base+'/start', headers=headers, json={}).json()['current_question']
    provider = FakeLLMProvider([ProviderError('sanitized', 'timeout', retryable=True, exhausted=True)])
    provider.model = 'test-model'
    monkeypatch.setattr('backend.ai_web.create_llm_provider', lambda **kwargs:provider)
    body = {'question_id':current['id'], 'text':'created once'}
    failed = client.post(base+'/answers', headers=headers, json=body)
    assert failed.status_code == 503
    saved = client.get(base, headers=headers).json()
    assert saved['pending_answer'] == body
    assert not saved['answers']
    provider.responses = iter([json.dumps(evaluation()), json.dumps({'text':'Recovered question?'})])
    resumed = client.post(base+'/start', headers=headers, json={}).json()
    assert len(resumed['answers']) == 1
    assert resumed['pending_answer'] is None
    report = client.post(base+'/finish', headers=headers, json={}).json()['report']
    assert len(report['skills'][0]['evidence']) == 1


def test_provider_identity_persists_across_configuration_switch(setup_ai, monkeypatch):
    client, module = setup_ai
    provider = FakeLLMProvider([json.dumps({'text':'Gemini session question?'})])
    provider.name, provider.model = 'gemini', 'gemini-3.8-flash'
    selected = []
    def factory(**kwargs):
        selected.append(kwargs)
        return provider
    monkeypatch.setattr('backend.ai_web.create_llm_provider', factory)
    base, headers = create(client)
    monkeypatch.setenv('MIMAS_LLM_PROVIDER','groq')
    response = client.post(base+'/start', headers=headers, json={})
    assert response.status_code == 200
    assert selected[-1] == {'provider':'gemini','model':'gemini-3.8-flash'}
