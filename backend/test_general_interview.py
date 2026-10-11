"""One reusable profession interview, optional vacancy follow-up, and sharing boundaries."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ai_web import register_ai_routes
from backend.companies import company_from_key, register_company_routes
from backend.general_interview import ensure_professions, provisional_rating
from backend.marketplace import register_marketplace_routes
from backend.media import register_video_routes
from backend.test_assessment_flow import EphemeralDatabase, FakeStorage, FakeYandex, _company


WELDER_EXTRA = {'role': 'Сварщик', 'version': 'draft', 'skills': [
    {'id': 'special-weld', 'name': 'Сварка тонкого металла',
     'concepts': ['Настройка режима для тонкого металла'],
     'goals': ['Проверить настройку сварочного режима'],
     'questions': ['Как настроите режим сварки для тонкой стали?'],
     'evaluation_criteria': ['Объясняет выбор режима и контроль прожога'],
     'target_questions': 1},
]}


class WelderFakeYandex(FakeYandex):
    async def generate(self, *, operation='question', **kwargs):
        if operation == 'template':
            return json.dumps(WELDER_EXTRA, ensure_ascii=False)
        return await super().generate(operation=operation, **kwargs)


def test_profession_interview_reused_and_vacancy_follow_up_optional(monkeypatch):
    monkeypatch.setenv('MIMAS_ADMIN_KEY', 'admin-test')
    monkeypatch.setenv('MIMAS_MAX_ASSESSMENTS_PER_DAY', '0')
    monkeypatch.setenv('MIMAS_MONITOR_ENABLED', '0')
    db = EphemeralDatabase()
    ensure_professions(db)
    app = FastAPI()
    auth = lambda key: company_from_key(db, key)
    register_company_routes(app, db)
    register_marketplace_routes(app, db, auth)
    register_ai_routes(app, db, auth)
    register_video_routes(app, db, auth)
    monkeypatch.setattr('backend.marketplace.create_llm_provider', lambda **kwargs: WelderFakeYandex())
    monkeypatch.setattr('backend.ai_web.create_llm_provider', lambda **kwargs: WelderFakeYandex())
    monkeypatch.setattr('backend.media._client', lambda: FakeStorage())
    monkeypatch.setattr('backend.media._bucket', lambda: 'test-bucket')
    with TestClient(app) as client:
        owner, other = _company(client, 'Owner'), _company(client, 'Other')
        candidate_token = client.post('/api/market/candidates', json={
            'name': 'Welder Candidate', 'level': 'middle',
            'stack': ['Сварщик', 'ручная дуговая сварка'],
            'years_experience': 3}).json()['token']
        candidate = {'X-Candidate-Token': candidate_token}
        catalog = client.get('/api/market/professions').json()
        assert {item['id'] for item in catalog} >= {'welder', 'fitter', 'turner', 'electrician'}
        assert client.post('/api/ai/general-sessions', headers=candidate, json={
            'profession_id': 'welder', 'consent': False,
            'share_with_companies': False}).status_code == 422
        assert client.post('/api/ai/general-sessions', headers=candidate, json={
            'profession_id': 'electrician', 'consent': True,
            'share_with_companies': True}).status_code == 409
        created = client.post('/api/ai/general-sessions', headers=candidate, json={
            'profession_id': 'welder', 'consent': True,
            'share_with_companies': False})
        assert created.status_code == 200, created.text
        general_id = created.json()['id']
        assert client.post('/api/ai/general-sessions', headers=candidate, json={
            'profession_id': 'welder', 'consent': True,
            'share_with_companies': True}).json()['id'] == general_id

        base = {'title': 'Сварщик', 'description': 'Изготовление деталей по чертежу',
                'level': 'middle', 'stack': ['Сварщик', 'ручная дуговая сварка'],
                'employment_type': 'full_time'}
        no_extra = client.post('/api/market/company/opportunities', headers=owner,
                               json=base).json()['id']
        assert client.patch('/api/market/company/opportunities/' + no_extra,
                            headers=owner, json={'status': 'open'}).status_code == 200
        no_interest = client.post('/api/market/company/opportunities', headers=owner,
                                  json={**base, 'title': 'Сварщик другой бригады'}).json()['id']
        assert client.patch('/api/market/company/opportunities/' + no_interest,
                            headers=owner, json={'status': 'open'}).status_code == 200
        extra = client.post('/api/market/company/opportunities', headers=owner,
                            json={**base, 'title': 'Сварщик тонкого металла'}).json()['id']
        template_route = f'/api/market/company/opportunities/{extra}/template'
        assert client.post(template_route + '/draft', headers=owner).status_code == 200
        assert client.put(template_route + '/draft', headers=owner,
                          json={'plan': WELDER_EXTRA}).status_code == 200
        assert client.post(template_route + '/approve', headers=owner).status_code == 200
        found = client.get('/api/market/opportunities', headers=candidate).json()
        assert {item['id']: item['additional_required'] for item in found} == {
            no_extra: False, no_interest: False, extra: True}
        for opportunity_id in (no_extra, extra):
            assert client.post(f'/api/market/opportunities/{opportunity_id}/interest',
                               headers=candidate).status_code == 200
        assert client.post('/api/ai/sessions', headers=candidate,
                           json={'opportunity_id': extra, 'consent': True}).status_code == 409

        access = {'X-Interview-Token': candidate_token}
        prefix = '/api/ai/sessions/' + general_id
        assert client.post(prefix + '/recording/init', headers=access).status_code == 200
        started = client.post(prefix + '/start', headers=access)
        assert started.status_code == 200, started.text
        question = started.json()['current_question']
        assert question and question['generation'] == 'approved_template'
        answered = client.post(prefix + '/answers', headers=access,
                               json={'question_id': question['id'], 'text': 'Сначала осмотрю рабочее место.'})
        assert answered.status_code == 200, answered.text
        finished = client.post(prefix + '/finish', headers=access)
        assert finished.status_code == 200 and finished.json()['report'], finished.text
        assert client.get(prefix + '/recording/status', headers=owner).status_code == 404
        assert client.get(prefix + '/recording/status', headers=access).status_code == 200
        assert client.get('/api/market/company/assessments/' + general_id,
                          headers=owner).status_code == 404
        assert client.get('/api/market/company/general-candidates?profession_id=welder',
                          headers=other).status_code == 200
        assert client.get('/api/market/company/general-candidates?profession_id=welder',
                          headers=owner).json() == []
        assert client.patch('/api/market/me/general-sharing', headers=candidate,
                            json={'profession_id': 'welder',
                                  'share_with_companies': True}).status_code == 200
        ranking = client.get('/api/market/company/general-candidates?profession_id=welder',
                             headers=owner).json()
        assert len(ranking) == 1
        assert ranking[0]['candidate_name'] == 'Welder Candidate'
        assert ranking[0]['interested_in_your_vacancy'] is True
        assert 'answer_reviews' not in ranking[0]
        assert 'video' not in ranking[0]
        filtered_url = ('/api/market/company/general-candidates?profession_id=welder'
                        '&opportunity_id=' + no_extra)
        selected = client.get(filtered_url, headers=owner)
        assert selected.status_code == 200 and len(selected.json()) == 1
        assert selected.json()[0]['candidate_name'] == 'Welder Candidate'
        assert client.get(filtered_url, headers=other).status_code == 404
        assert client.get('/api/market/company/general-candidates?profession_id=electrician'
                          '&opportunity_id=' + no_extra, headers=owner).status_code == 404
        assert client.get('/api/market/company/general-candidates?profession_id=welder'
                          '&opportunity_id=' + no_interest, headers=owner).json() == []
        assert client.post('/api/ai/sessions', headers=candidate,
                           json={'opportunity_id': no_extra, 'consent': True}).status_code == 409
        extra_session = client.post('/api/ai/sessions', headers=candidate,
                                    json={'opportunity_id': extra, 'consent': True})
        assert extra_session.status_code == 200, extra_session.text
        assert extra_session.json()['id'] != general_id
        assert client.patch('/api/market/me/general-sharing', headers=candidate,
                            json={'profession_id': 'welder',
                                  'share_with_companies': False}).status_code == 200
        assert client.get('/api/market/company/general-candidates?profession_id=welder',
                          headers=owner).json() == []
        assert client.get(filtered_url, headers=owner).json() == []
    db.engine.dispose()


def test_rating_ignores_unscored_answers():
    report = {'answer_reviews': [
        {'status': 'assessed', 'points': 5}, {'status': 'not_assessed', 'points': None},
        {'status': 'assessed', 'points': 3}]}
    assert provisional_rating(report) == {'score': 4, 'assessed_answers': 2,
                                          'total_answers': 3, 'max_score': 5,
                                          'provisional': True}
