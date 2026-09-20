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
    monkeypatch.setattr('backend.ai_web.configured_groq',lambda:provider)
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
    assert next['current_question']['goal'] != first['current_question']['goal']
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
    monkeypatch.setattr('backend.ai_web.configured_groq',lambda:broken)
    body={'question_id':first['current_question']['id'],'text':'An explanation'}
    with pytest.raises(RuntimeError):
        client.post(base+'/answers',headers=headers,json=body)
    stored=client.get(base,headers=headers).json()
    assert stored['pending_answer']==body
    assert client.post(base+'/finish',headers=headers,json={}).status_code==409
    healthy=FakeLLMProvider([]);healthy.model='test-model'
    monkeypatch.setattr('backend.ai_web.configured_groq',lambda:healthy)
    result=client.post(base+'/answers',headers=headers,json=body).json()
    assert result['pending_answer'] is None
    assert len(result['answers'])==1
    assert 'provider_error' in result['evaluation_notice']
