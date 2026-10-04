"""Tenant isolation and human approval contract, using isolated ephemeral tables."""
from contextlib import contextmanager
from io import BytesIO
import json
import logging
import zipfile

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_core.llm.base import ProviderError
from backend.database import Base
from backend.companies import register_company_routes
from backend.marketplace import register_marketplace_routes


class EphemeralDatabase:
    def __init__(self):
        # Runtime Database only accepts PostgreSQL. This disposable DB tests
        # route logic without requiring a local PostgreSQL service.
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                                    poolclass=StaticPool)
        import backend.ai_web  # register ai_sessions mapping for foreign keys
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self, *, write=False, interview_id=None):
        with self.sessions() as db:
            with db.begin():
                yield db


def _client(monkeypatch):
    monkeypatch.setenv('MIMAS_ADMIN_KEY', 'admin-secret')
    app = FastAPI()
    database = EphemeralDatabase()
    register_company_routes(app, database)
    register_marketplace_routes(app, database)
    return TestClient(app), database


def _company(client, name, email):
    response = client.post('/api/market/companies/apply',
                           json={'name': name, 'contact_email': email})
    assert response.status_code == 200
    claim = response.json()['claim_token']
    assert client.post('/api/market/companies/claim',
                       headers={'X-Claim-Token': claim}).status_code == 409
    return response.json()['application_id'], claim


def _approve(client, application_id, claim):
    assert client.post(f'/api/market/admin/companies/{application_id}/approve',
                       headers={'X-Admin-Key': 'admin-secret'}).status_code == 200
    response = client.post('/api/market/companies/claim',
                           headers={'X-Claim-Token': claim})
    assert response.status_code == 200
    assert client.post('/api/market/companies/claim',
                       headers={'X-Claim-Token': claim}).status_code == 401
    return {'X-Company-Key': response.json()['company_key']}


def _vacancy(client, headers):
    return client.post('/api/market/company/opportunities', headers=headers, json={
        'title': 'Python Backend', 'description': 'Разработка FastAPI и PostgreSQL',
        'level': 'middle', 'stack': ['Python', 'FastAPI', 'PostgreSQL'],
        'employment_type': 'full_time'})


def _plan():
    return {'role': 'Python Backend', 'version': 'draft', 'skills': [
        {'id': 'api.design', 'name': 'API design', 'concepts': ['FastAPI'],
         'goals': ['Проверить авторизацию'], 'questions': ['Как защитить ресурс?'],
         'evaluation_criteria': ['Разделяет 401 и 403'], 'target_questions': 1},
        {'id': 'db.postgresql', 'name': 'PostgreSQL', 'concepts': ['transactions'],
         'goals': ['Проверить изоляцию'], 'questions': ['Как избежать lost update?'],
         'evaluation_criteria': ['Объясняет блокировку или атомарное обновление'], 'target_questions': 1}
    ]}


def test_company_approval_claim_and_isolation(monkeypatch):
    client, database = _client(monkeypatch)
    with client:
        first_id, first_claim = _company(client, 'Первая', 'first@example.com')
        second_id, second_claim = _company(client, 'Вторая', 'second@example.com')
        assert client.get('/api/market/admin/companies').status_code == 401
        listed = client.get('/api/market/admin/companies',
                            headers={'X-Admin-Key': 'admin-secret'}).json()
        assert {row['status'] for row in listed} == {'pending'}
        first = _approve(client, first_id, first_claim)
        second = _approve(client, second_id, second_claim)
        vacancy = _vacancy(client, first)
        assert vacancy.status_code == 200
        opportunity_id = vacancy.json()['id']
        assert vacancy.json()['company_name'] == 'Первая'
        assert vacancy.json()['status'] == 'draft'
        assert client.get('/api/market/company/opportunities', headers=second).json() == []
        assert client.get(f'/api/market/company/opportunities/{opportunity_id}/template',
                          headers=second).status_code == 404
        assert client.patch(f'/api/market/company/opportunities/{opportunity_id}',
                            headers=second, json={'status': 'closed'}).status_code == 404
        assert client.patch(f'/api/market/company/opportunities/{opportunity_id}',
                            headers=first, json={'status': 'open'}).status_code == 409

        candidate = client.post('/api/market/candidates', json={
            'name': 'Кандидат', 'level': 'middle', 'stack': ['Python'],
            'years_experience': 2}).json()
        candidate_key = {'X-Candidate-Token': candidate['token']}
        assert client.get('/api/market/opportunities', headers=candidate_key).json() == []

        class Provider:
            async def generate(self, **kwargs):
                assert kwargs['operation'] == 'template'
                return json.dumps(_plan(), ensure_ascii=False)
        monkeypatch.setattr('backend.marketplace.create_llm_provider', lambda **kwargs: Provider())
        route = f'/api/market/company/opportunities/{opportunity_id}/template'
        generated = client.post(route + '/draft', headers=first)
        assert generated.status_code == 200
        assert generated.json()['status'] == 'draft'
        assert generated.json()['plan']['version'].endswith('v1')
        assert client.put(route + '/draft', headers=second,
                          json={'plan': _plan()}).status_code == 404
        assert client.post(route + '/approve', headers=second).status_code == 404
        approved = client.post(route + '/approve', headers=first)
        assert approved.status_code == 200
        assert approved.json()['status'] == 'approved'
        assert client.put(route + '/draft', headers=first,
                          json={'plan': _plan()}).status_code == 409
        found = client.get('/api/market/opportunities', headers=candidate_key).json()
        assert [item['id'] for item in found] == [opportunity_id]
        assert client.post(f'/api/market/opportunities/{opportunity_id}/interest',
                           headers=candidate_key).status_code == 200
        revised = client.post(route + '/draft', headers=first)
        assert revised.status_code == 200
        assert revised.json()['version'] == 2
        assert revised.json()['plan']['version'].endswith('v2')
        from backend.marketplace import VacancyTemplate
        from sqlalchemy import select
        with database.session() as db:
            original = db.scalar(select(VacancyTemplate).where(
                VacancyTemplate.opportunity_id == opportunity_id,
                VacancyTemplate.version == 1))
            assert original.status == 'approved'
            assert json.loads(original.plan_json)['version'].endswith('v1')
        assert client.get('/api/market/company/candidates', headers=second,
                          params={'opportunity_id': opportunity_id}).status_code == 404
        assert client.get('/api/market/company/candidates', headers=first,
                          params={'opportunity_id': opportunity_id}).json() == []
    database.engine.dispose()


@pytest.mark.parametrize(('failure', 'expected_code'), [
    (ProviderError('PRIVATE_PROVIDER_BODY', 'rate_limit'), 'rate_limit'),
    (ProviderError('PRIVATE_PROVIDER_BODY', 'PRIVATE_PROVIDER_BODY'), 'provider_error'),
    ('{"payload": "PRIVATE_PROVIDER_BODY"', 'invalid_template_json'),
])
def test_template_generation_failure_has_safe_code(monkeypatch, caplog, failure, expected_code):
    client, database = _client(monkeypatch)
    with client:
        company_id, claim = _company(client, 'Тест', 'test@example.com')
        headers = _approve(client, company_id, claim)
        vacancy = client.post('/api/market/company/opportunities', headers=headers, json={
            'title': 'Backend', 'description': 'PRIVATE_VACANCY_TEXT',
            'level': 'middle', 'stack': ['Python'], 'employment_type': 'full_time',
        }).json()

        class Provider:
            async def generate(self, **kwargs):
                if isinstance(failure, Exception):
                    raise failure
                return failure

        monkeypatch.setattr('backend.marketplace.create_llm_provider', lambda **kwargs: Provider())
        route = f"/api/market/company/opportunities/{vacancy['id']}/template"
        with caplog.at_level(logging.WARNING, logger='backend.marketplace'):
            response = client.post(route + '/draft', headers=headers)
        assert response.status_code == 503
        assert response.json() == {
            'detail': 'AI не смог составить шаблон. Повторите попытку.',
            'code': expected_code,
        }
        assert client.get(route, headers=headers).status_code == 404
        logged = '\n'.join(record.getMessage() for record in caplog.records
                           if record.name == 'backend.marketplace')
        assert f'code={expected_code}' in logged
        for secret in ('PRIVATE_PROVIDER_BODY', 'PRIVATE_VACANCY_TEXT', headers['X-Company-Key']):
            assert secret not in logged
            assert secret not in response.text
    database.engine.dispose()


def test_docx_extraction_and_image_ocr_hook(monkeypatch):
    from backend import marketplace
    document = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Python developer</w:t></w:r></w:p></w:body></w:document>'
    target = BytesIO()
    with zipfile.ZipFile(target, 'w') as archive:
        archive.writestr('word/document.xml', document)
    assert marketplace._docx_text(target.getvalue()) == 'Python developer'

    client, database = _client(monkeypatch)
    with client:
        company_id, claim = _company(client, 'Импорт', 'import@example.com')
        headers = _approve(client, company_id, claim)
        response = client.post('/api/market/company/opportunities/import', headers=headers,
                               files={'file': ('vacancy.docx', target.getvalue(),
                                               'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
        assert response.json()['text'] == 'Python developer'

        async def fake_ocr(payload, mime, db):
            assert mime == 'image/png'
            return 'Вакансия по Python'
        monkeypatch.setattr(marketplace, '_ocr', fake_ocr)
        image = client.post('/api/market/company/opportunities/import', headers=headers,
                            files={'file': ('vacancy.png', b'\x89PNG\r\n\x1a\n',
                                            'image/png')})
        assert image.json()['text'] == 'Вакансия по Python'
    database.engine.dispose()




def test_application_rate_limit_and_docx_embedded_scan(monkeypatch):
    monkeypatch.setenv('MIMAS_MAX_COMPANY_APPLICATIONS_PER_DAY', '1')
    client, database = _client(monkeypatch)
    from backend import marketplace

    empty_xml = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p/></w:body></w:document>'
    payload = BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('word/document.xml', empty_xml)
        archive.writestr('word/media/image1.png', b'\x89PNG\r\n\x1a\n')

    async def fake_ocr(raw, mime, db):
        assert mime == 'image/png'
        return 'Текст вакансии из скана'
    monkeypatch.setattr(marketplace, '_ocr', fake_ocr)
    with client:
        company_id, claim = _company(client, 'Скан', 'scan@example.com')
        assert client.post('/api/market/companies/apply',
                           json={'name': 'Вторая', 'contact_email': 'other@example.com'}).status_code == 429
        headers = _approve(client, company_id, claim)
        result = client.post('/api/market/company/opportunities/import', headers=headers,
                             files={'file': ('scan.docx', payload.getvalue(),
                                             'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
        assert result.status_code == 200
        assert result.json()['text'] == 'Текст вакансии из скана'
    database.engine.dispose()



def test_employer_report_requires_matching_vacancy_owner(monkeypatch):
    client, database = _client(monkeypatch)
    from backend.ai_web import AISession
    from backend.marketplace import CandidateAssessment
    from backend.media import VideoRecording
    from ai_core.interview.engine import InterviewEngine
    from ai_core.interview.state import Phase
    from ai_core.llm.provider import FakeLLMProvider
    with client:
        owner_id, owner_claim = _company(client, 'Владелец', 'owner@example.com')
        other_id, other_claim = _company(client, 'Чужая', 'other@example.com')
        owner = _approve(client, owner_id, owner_claim)
        other = _approve(client, other_id, other_claim)
        vacancy = _vacancy(client, owner).json()
        signup = client.post('/api/market/candidates', json={
            'name': 'Кандидат', 'level': 'middle', 'stack': ['Python'],
            'years_experience': 3}).json()
        profile = signup['profile']
        engine = InterviewEngine(FakeLLMProvider([]))
        engine.state.phase = Phase.COMPLETED
        with database.session(write=True) as db:
            db.add(AISession(id='legacy-test-session', token_hash='digest', model='test',
                             started=1, state=engine.state.model_dump_json(), trace='[]',
                             candidate_id=profile['id'], opportunity_id=vacancy['id'], archived=0))
            db.add(CandidateAssessment(candidate_id=profile['id'],
                                       opportunity_id=vacancy['id'],
                                       session_id='legacy-test-session',
                                       consent_at=1, created=1))
        report_url = '/api/market/company/assessments/legacy-test-session'
        assert client.get(report_url, headers=other).status_code == 404
        assert client.get('/api/market/company/candidates', headers=other).json() == []
        assert client.get(report_url, headers=owner).status_code == 409
        pending = client.get('/api/market/company/candidates', headers=owner).json()
        assert pending[0]['status'] == 'recording_pending'
        assert pending[0]['summary'] is None
        candidate_key = {'X-Candidate-Token': signup['token']}
        own = client.get('/api/market/me', headers=candidate_key).json()['assessments'][vacancy['id']]
        assert own['report'] is None
        assert own['recording_status'] == 'pending'
        with database.session(write=True) as db:
            db.add(VideoRecording(session_id='legacy-test-session',
                                  object_key='test-recording', status='completed',
                                  created=1, completed=2, expires_at=0, part_count=1,
                                  interrupted=0))
        assert client.get(report_url, headers=owner).status_code == 200
        available = client.get('/api/market/me', headers=candidate_key).json()['assessments'][vacancy['id']]
        assert available['report'] is not None
        assert available['recording_status'] == 'completed'
    database.engine.dispose()



def test_legacy_archive_keeps_old_visibility_rule(monkeypatch):
    client, database = _client(monkeypatch)
    from backend.ai_web import AISession
    from backend.marketplace import LegacyCandidateAssessment
    from backend.companies import ensure_legacy_company
    from ai_core.interview.engine import InterviewEngine
    from ai_core.interview.state import Phase
    from ai_core.llm.provider import FakeLLMProvider

    ensure_legacy_company(database, 'legacy-secret')
    with client:
        other_id, other_claim = _company(client, 'Новая', 'new@example.com')
        other = _approve(client, other_id, other_claim)
        signup = client.post('/api/market/candidates', json={
            'name': 'Старый кандидат', 'level': 'middle', 'stack': ['Python'],
            'years_experience': 3}).json()
        engine = InterviewEngine(FakeLLMProvider([]))
        engine.state.phase = Phase.COMPLETED
        with database.session(write=True) as db:
            db.add(AISession(id='legacy-completed', token_hash='digest',
                             model='old-model', started=1,
                             state=engine.state.model_dump_json(),
                             trace='[]', archived=1))
            db.add(LegacyCandidateAssessment(candidate_id=signup['profile']['id'],
                                             session_id='legacy-completed', created=1))
        url = '/api/market/company/legacy-assessments'
        assert client.get(url, headers=other).status_code == 404
        legacy_header = {'X-Company-Key': 'legacy-secret'}
        assert client.get(url, headers=legacy_header).json() == []
        client.patch('/api/market/me',
                     headers={'X-Candidate-Token': signup['token']},
                     json={'discoverable': True})
        shown = client.get(url, headers=legacy_header)
        assert shown.status_code == 200
        assert len(shown.json()) == 1
        assert shown.json()[0]['assessment_id'] == 'legacy-completed'
        assert 'token' not in json.dumps(shown.json())
        client.patch('/api/market/me',
                     headers={'X-Candidate-Token': signup['token']},
                     json={'discoverable': False})
        assert client.get(url, headers=legacy_header).json() == []
    database.engine.dispose()
