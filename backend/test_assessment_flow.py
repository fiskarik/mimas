"""A full vacancy flow without external AI, database, or storage charges."""
from contextlib import contextmanager
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.companies import company_from_key, register_company_routes
from backend.marketplace import register_marketplace_routes
from backend.ai_web import register_ai_routes
from backend.media import register_video_routes


class EphemeralDatabase:
    def __init__(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self, *, write=False, interview_id=None):
        with self.sessions() as db:
            with db.begin():
                yield db


PLAN = {'role': 'Python Backend', 'version': 'draft', 'skills': [
    {'id': 'python', 'name': 'Python', 'concepts': ['mutability'],
     'goals': ['Проверить изменяемые значения'],
     'questions': ['Когда создаётся значение по умолчанию?'],
     'evaluation_criteria': ['Объясняет время создания объекта'], 'target_questions': 1}
]}


class FakeYandex:
    name = 'yandex'
    model = 'gpt://test/deepseek-v4.1-flash'
    async def generate(self, *, operation='question', **kwargs):
        if operation == 'template':
            return json.dumps(PLAN, ensure_ascii=False)
        if operation in ('question', 'follow_up', 'verification'):
            return json.dumps({'text': 'Когда создаётся значение по умолчанию?'}, ensure_ascii=False)
        return json.dumps({'correctness': 'correct', 'depth': 'medium',
                           'evidence': [{'type': 'positive', 'claim': 'Причина объяснена',
                                         'quote': 'created once'}],
                           'follow_up_required': False, 'recommended_difficulty': 3})


class FakeStorage:
    def create_multipart_upload(self, **kwargs):
        return {'UploadId': 'upload-one'}
    def generate_presigned_url(self, action, **kwargs):
        return 'https://example.test/private-' + action
    def complete_multipart_upload(self, **kwargs):
        return {'ETag': 'etag-test'}
    def head_object(self, **kwargs):
        return {'ContentLength': 1234}


def _company(client, name):
    claim = client.post('/api/market/companies/apply', json={
        'name': name, 'contact_email': name.lower() + '@example.test'}).json()
    assert claim['claim_token']
    assert client.post(f"/api/market/admin/companies/{claim['application_id']}/approve",
                       headers={'X-Admin-Key': 'admin-test'}).status_code == 200
    key = client.post('/api/market/companies/claim',
                      headers={'X-Claim-Token': claim['claim_token']}).json()['company_key']
    return {'X-Company-Key': key}


def _candidate(client, name):
    result = client.post('/api/market/candidates', json={
        'name': name, 'level': 'middle', 'stack': ['Python'], 'years_experience': 2}).json()
    return {'X-Candidate-Token': result['token']}


def test_two_candidates_same_vacancy_and_tenant_isolation(monkeypatch):
    monkeypatch.setenv('MIMAS_ADMIN_KEY', 'admin-test')
    monkeypatch.setenv('MIMAS_MAX_ASSESSMENTS_PER_DAY', '0')
    db = EphemeralDatabase()
    app = FastAPI()
    auth = lambda key: company_from_key(db, key)
    register_company_routes(app, db)
    register_marketplace_routes(app, db, auth)
    register_ai_routes(app, db, auth)
    register_video_routes(app, db, auth)
    monkeypatch.setattr('backend.marketplace.create_llm_provider', lambda **kwargs: FakeYandex())
    monkeypatch.setattr('backend.ai_web.create_llm_provider', lambda **kwargs: FakeYandex())
    monkeypatch.setattr('backend.media._client', lambda: FakeStorage())
    monkeypatch.setattr('backend.media._bucket', lambda: 'test-bucket')
    with TestClient(app) as client:
        owner, other = _company(client, 'Owner'), _company(client, 'Other')
        vacancy = client.post('/api/market/company/opportunities', headers=owner, json={
            'title': 'Python Backend', 'description': 'Проверка Python в сервисе',
            'level': 'middle', 'stack': ['Python'], 'employment_type': 'full_time'}).json()
        opportunity_id = vacancy['id']
        base = '/api/market/company/opportunities/' + opportunity_id + '/template'
        assert client.post(base + '/draft', headers=owner).status_code == 200
        assert client.put(base + '/draft', headers=owner, json={'plan': PLAN}).status_code == 200
        assert client.post(base + '/approve', headers=owner).status_code == 200
        assert client.get(base, headers=other).status_code == 404
        sessions = []
        for name in ('First', 'Second'):
            candidate = _candidate(client, name)
            found = client.get('/api/market/opportunities', headers=candidate).json()
            assert found[0]['id'] == opportunity_id
            assert client.post('/api/market/opportunities/' + opportunity_id + '/interest',
                               headers=candidate).status_code == 200
            created = client.post('/api/ai/sessions', headers=candidate,
                                  json={'opportunity_id': opportunity_id, 'consent': True})
            assert created.status_code == 200, created.text
            session_id = created.json()['id']
            assert client.post('/api/ai/sessions', headers=candidate,
                               json={'opportunity_id': opportunity_id, 'consent': True}).json()['id'] == session_id
            access = {'X-Interview-Token': candidate['X-Candidate-Token']}
            prefix = '/api/ai/sessions/' + session_id
            assert client.post(prefix + '/start', headers=access).status_code == 409
            assert client.post(prefix + '/recording/init', headers=access).status_code == 200
            opened = client.post(prefix + '/start', headers=access)
            assert opened.status_code == 200, opened.text
            question = opened.json()['current_question']
            assert question
            answered = client.post(prefix + '/answers', headers=access,
                                   json={'question_id': question['id'], 'text': 'я не знаю'})
            assert answered.status_code == 200, answered.text
            pending_report = client.get(prefix, headers=access).json()
            assert pending_report['report'] is None
            assert pending_report['recording_required'] is True
            assert client.post(prefix + '/recording/complete', headers=access,
                               json={'parts': [{'part_number': 1, 'etag': 'etag-test'}]}).status_code == 200
            report = client.post(prefix + '/finish', headers=access)
            assert report.status_code == 200, report.text
            assert report.json()['report']
            sessions.append(session_id)
            assert client.get('/api/market/company/assessments/' + session_id,
                              headers=other).status_code == 404
            assert client.get(prefix + '/recording/status', headers=other).status_code == 404
            assert client.get(prefix + '/recording/status', headers=owner).status_code == 200
        assert sessions[0] != sessions[1]
        assert len(client.get('/api/market/company/candidates', headers=owner).json()) == 2
        assert client.get('/api/market/company/candidates', headers=other).json() == []
    db.engine.dispose()
