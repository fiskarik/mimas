import pytest
pytest.skip('Archived SQLite/Groq API contract; replaced by tenant assessment integration tests.', allow_module_level=True)

import importlib
import sys
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('COMPANY_KEY', 'test-employer')
    monkeypatch.setenv('AI_MODE', 'mock')
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    sys.modules.pop('backend.app', None)
    module = importlib.import_module('backend.app')
    with TestClient(module.app) as c:
        yield c
    module.database.engine.dispose()


COMPANY = {'X-Company-Key': 'test-employer'}


def invite(client):
    result = client.post('/api/interviews', headers=COMPANY, json={'name': 'Test Candidate'})
    assert result.status_code == 200
    row = result.json()
    return row['id'], {'X-Interview-Token': row['token']}


def start(client, iid, headers):
    assert client.post(f'/api/interviews/{iid}/start', headers=headers, json={'consent': True}).status_code == 200


def test_access_control(client):
    iid, headers = invite(client)
    other_id, other_headers = invite(client)
    assert client.get('/api/interviews').status_code == 401
    assert client.get(f'/api/interviews/{iid}', headers=other_headers).status_code == 401
    assert client.get(f'/api/company/interviews/{iid}', headers=headers).status_code == 401
    assert client.get(f'/api/company/interviews/{iid}/recording', headers=headers).status_code == 401
    response = client.get(f'/api/interviews/{iid}', headers=headers)
    assert response.status_code == 200
    assert 'token' not in response.json()['interview']
    assert other_id != iid


def test_consent_order_and_immutable_answers(client):
    iid, headers = invite(client)
    base = f'/api/interviews/{iid}'
    assert client.post(base + '/start', headers=headers, json={'consent': False}).status_code == 422
    start(client, iid, headers)
    assert client.post(base + '/start', headers=headers, json={'consent': True}).status_code == 409
    assert client.post(base + '/answers', headers=headers, json={'question_id': 'sql', 'text': 'skip'}).status_code == 409
    answer = {'question_id': 'python', 'text': 'Default values are created once.'}
    assert client.post(base + '/answers', headers=headers, json=answer).status_code == 200
    assert client.post(base + '/answers', headers=headers, json=answer).status_code == 200
    assert client.post(base + '/answers', headers=headers, json={**answer, 'text': 'changed'}).status_code == 409
    report = client.get(f'/api/company/interviews/{iid}', headers=COMPANY).json()
    assert len(report['answers']) == 1
    assert report['answers'][0]['evaluation'] is None


def test_recording_retries_missing_chunks_and_finalize(client):
    iid, headers = invite(client)
    base = f'/api/interviews/{iid}'
    start(client, iid, headers)
    assert client.put(base + '/recording/1', headers=headers, content=b'part-one').status_code == 200
    assert client.put(base + '/recording/1', headers=headers, content=b'part-one').status_code == 200
    assert client.put(base + '/recording/1', headers=headers, content=b'changed').status_code == 409
    result = client.post(base + '/finish', headers=headers, json={'expected_chunks': 2})
    assert result.json()['recording_complete'] is False
    assert client.get(f'/api/company/interviews/{iid}/recording', headers=COMPANY).status_code == 409
    assert client.put(base + '/recording/0', headers=headers, content=b'header').status_code == 200
    assert client.put(base + '/recording/2', headers=headers, content=b'extra').status_code == 409
    assert client.post(base + '/finish', headers=headers, json={'expected_chunks': 2}).json()['recording_complete'] is True
    assert client.get(f'/api/company/interviews/{iid}/recording', headers=COMPANY).content == b'headerpart-one'
    assert client.post(base + '/finish', headers=headers, json={'expected_chunks': 1}).status_code == 409


def test_event_retry_and_finished_interview(client):
    iid, headers = invite(client)
    base = f'/api/interviews/{iid}'
    start(client, iid, headers)
    event = {'id': 'event1', 'kind': 'paste', 'elapsed': 4.2, 'detail': '50 characters'}
    assert client.post(base + '/events', headers=headers, json=event).status_code == 200
    assert client.post(base + '/events', headers=headers, json=event).status_code == 200
    assert len(client.get(base, headers=headers).json()['events']) == 1
    assert client.post(base + '/finish', headers=headers, json={'expected_chunks': 0}).json()['recording_complete'] is False
    assert client.post(base + '/answers', headers=headers, json={'question_id': 'python', 'text': 'late'}).status_code == 409
    assert client.post(base + '/events', headers=headers, json={**event, 'id': 'late'}).status_code == 409


def test_live_configuration_and_stt_without_key(client, monkeypatch):
    iid, headers = invite(client)
    start(client, iid, headers)
    assert client.post(f'/api/interviews/{iid}/transcribe', headers=headers, content=b'audio').status_code == 503
    monkeypatch.setenv('AI_MODE', 'live')
    assert client.post('/api/interviews', headers=COMPANY, json={'name': 'Candidate'}).status_code == 503


def test_full_mock_interview(client):
    iid, headers = invite(client)
    start(client, iid, headers)
    for question in ['python', 'async', 'sql', 'coding', 'defense']:
        response = client.post(f'/api/interviews/{iid}/answers', headers=headers,
                               json={'question_id': question, 'text': f'Test answer for {question}'})
        assert response.status_code == 200
        assert response.json()['evaluation'] is None
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers, json={'expected_chunks': 0}).status_code == 200
    report = client.get(f'/api/company/interviews/{iid}', headers=COMPANY).json()
    assert report['interview']['status'] == 'completed'
    assert len(report['answers']) == 5
    assert report['capabilities']['runner_ready'] is False
