"""The candidate-to-employer path must keep one assessment and require consent."""
import importlib
import json
import sys

from fastapi.testclient import TestClient
from ai_core.llm.provider import FakeLLMProvider


def test_marketplace_path_and_private_profile(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('COMPANY_KEY', 'team-secret')
    monkeypatch.setenv('MIMAS_MAX_CANDIDATES_PER_DAY', '1')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    sys.modules.pop('backend.app', None)
    module = importlib.import_module('backend.app')
    provider = FakeLLMProvider([json.dumps({'text': 'Почему изменяемый аргумент по умолчанию опасен?'}),
                                json.dumps({'text': 'Как работает генератор в Python?'})])
    provider.model = 'fake-free-model'
    monkeypatch.setattr('backend.ai_web.create_llm_provider', lambda **kwargs: provider)
    company = {'X-Company-Key': 'team-secret'}
    opportunity = {'company_name': 'Тестовая команда', 'title': 'Python Backend',
                   'description': 'Разработка API на Python и PostgreSQL.',
                   'level': 'middle', 'stack': ['Python', 'FastAPI', 'PostgreSQL'],
                   'salary_min_rub': 180000, 'salary_max_rub': 230000,
                   'employment_type': 'full_time'}
    candidate = {'name': 'Тестовый кандидат', 'level': 'middle',
                 'stack': ['Python', 'FastAPI', 'Asyncio'], 'years_experience': 3,
                 'github_url': 'https://github.com/example',
                 'desired_salary_rub': 200000}

    with TestClient(module.app) as client:
        assert client.get('/api/market/company/candidates').status_code == 401
        assert client.post('/api/market/company/opportunities', json=opportunity).status_code == 401
        vacancy = client.post('/api/market/company/opportunities', headers=company,
                              json=opportunity).json()
        assert vacancy['title'] == 'Python Backend'

        signup = client.post('/api/market/candidates', json=candidate)
        assert signup.status_code == 200
        assert client.post('/api/market/candidates', json=candidate).status_code == 429
        access = {'X-Candidate-Token': signup.json()['token']}
        assert signup.json()['profile']['discoverable'] is False
        assert client.get('/api/market/me').status_code == 401
        found = client.get('/api/market/opportunities', headers=access).json()
        assert len(found) == 1
        assert found[0]['match']['stack_overlap'] == 2
        assert found[0]['match']['compatible'] is True
        assert found[0]['interested'] is False
        assert client.post('/api/ai/sessions', headers=access, json={}).status_code == 409

        interest = client.post(f"/api/market/opportunities/{vacancy['id']}/interest",
                               headers=access, json={})
        assert interest.status_code == 200
        assert client.post(f"/api/market/opportunities/{vacancy['id']}/interest",
                           headers=access, json={}).status_code == 200
        session = client.post('/api/ai/sessions', headers=access, json={})
        assert session.status_code == 200
        session_id = session.json()['id']
        assert session.json()['token'] == signup.json()['token']
        again = client.post('/api/ai/sessions', headers=access, json={})
        assert again.json()['id'] == session_id
        session_base = f'/api/ai/sessions/{session_id}'
        interview_headers = {'X-Interview-Token': access['X-Candidate-Token']}
        first = client.post(session_base + '/start', headers=interview_headers, json={}).json()
        assert first['current_question']
        assert client.get('/api/market/company/candidates', headers=company).json() == []
        answered = client.post(session_base + '/answers', headers=interview_headers,
                               json={'question_id': first['current_question']['id'],
                                     'text': 'Значение списка создаётся один раз; лучше использовать None.'})
        assert answered.status_code == 200
        finished = client.post(session_base + '/finish', headers=interview_headers, json={})
        assert finished.status_code == 200
        assert finished.json()['report'] is not None
        assert client.get('/api/market/company/candidates', headers=company).json() == []

        shown = client.patch('/api/market/me', headers=access, json={'discoverable': True})
        assert shown.json()['discoverable'] is True
        company_view = client.get('/api/market/company/candidates', headers=company,
                                  params={'opportunity_id': vacancy['id']}).json()
        assert len(company_view) == 1
        assert company_view[0]['interested'] is True
        assert company_view[0]['assessment_id'] == session_id
        assert 'answer_reviews' not in company_view[0]
        assert 'token' not in json.dumps(company_view)
        my_view = client.get('/api/market/me', headers=access).json()
        assert my_view['assessment']['report'] is not None
        assert my_view['interested_opportunity_ids'] == [vacancy['id']]
        client.patch('/api/market/me', headers=access, json={'discoverable': False})
        assert client.get('/api/market/company/candidates', headers=company).json() == []
        assert client.patch(f"/api/market/company/opportunities/{vacancy['id']}",
                            json={'status': 'closed'}).status_code == 401
        closed = client.patch(f"/api/market/company/opportunities/{vacancy['id']}",
                              headers=company, json={'status': 'closed'})
        assert closed.json()['status'] == 'closed'
        assert client.get('/api/market/opportunities', headers=access).json() == []
        assert client.post(f"/api/market/opportunities/{vacancy['id']}/interest",
                           headers=access, json={}).status_code == 404

    module.database.engine.dispose()
