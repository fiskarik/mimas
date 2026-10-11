"""Company interview limits are versioned and copied into each candidate session."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.ai_web import AISession, register_ai_routes
from backend.companies import company_from_key, register_company_routes
from backend.marketplace import register_marketplace_routes
from backend.test_assessment_flow import PLAN, EphemeralDatabase, FakeYandex, _candidate, _company


def test_settings_are_private_validated_and_frozen_per_interview(monkeypatch):
    monkeypatch.setenv('MIMAS_ADMIN_KEY', 'admin-test')
    db = EphemeralDatabase()
    app = FastAPI()
    auth = lambda key: company_from_key(db, key)
    register_company_routes(app, db)
    register_marketplace_routes(app, db, auth)
    register_ai_routes(app, db, auth)
    monkeypatch.setattr('backend.marketplace.create_llm_provider', lambda **kwargs: FakeYandex())
    monkeypatch.setattr('backend.ai_web.create_llm_provider', lambda **kwargs: FakeYandex())
    with TestClient(app) as client:
        owner, other = _company(client, 'Owner'), _company(client, 'Other')
        vacancy = client.post('/api/market/company/opportunities', headers=owner, json={
            'title': 'Сварщик', 'description': 'Сварка деталей по чертежам',
            'level': 'middle', 'stack': ['Сварщик'], 'employment_type': 'full_time'}).json()
        opportunity_id = vacancy['id']
        route = f'/api/market/company/opportunities/{opportunity_id}/template'
        assert client.post(route + '/draft', headers=owner).status_code == 200
        settings_v1 = {'max_questions': 4, 'max_follow_ups': 0, 'duration_minutes': 5}
        assert client.put(route + '/draft', headers=other,
                          json={'plan': PLAN, 'settings': settings_v1}).status_code == 404
        assert client.put(route + '/draft', headers=owner,
                          json={'plan': PLAN, 'settings': {**settings_v1, 'duration_minutes': 21}}).status_code == 422
        saved = client.put(route + '/draft', headers=owner,
                           json={'plan': PLAN, 'settings': settings_v1})
        assert saved.status_code == 200, saved.text
        assert saved.json()['settings'] == settings_v1
        assert client.post(route + '/approve', headers=owner).status_code == 200
        assert client.put(route + '/draft', headers=owner,
                          json={'plan': PLAN, 'settings': settings_v1}).status_code == 409

        first = _candidate(client, 'First')
        assert client.post(f'/api/market/opportunities/{opportunity_id}/interest',
                           headers=first).status_code == 200
        first_session = client.post('/api/ai/sessions', headers=first,
                                    json={'opportunity_id': opportunity_id, 'consent': True})
        assert first_session.status_code == 200, first_session.text
        with db.session() as session:
            first_row = session.get(AISession, first_session.json()['id'])
            first_state = json.loads(first_row.state)
        assert first_state['limits']['max_questions'] == 4
        assert first_state['limits']['max_follow_ups_per_question'] == 0
        assert first_state['limits']['time_budget_seconds'] == 300

        assert client.post(route + '/revision', headers=other).status_code == 404
        revision = client.post(route + '/revision', headers=owner)
        assert revision.status_code == 200, revision.text
        assert revision.json()['version'] == 2
        assert revision.json()['settings'] == settings_v1
        assert client.post(route + '/revision', headers=owner).status_code == 409
        settings_v2 = {'max_questions': 2, 'max_follow_ups': 1, 'duration_minutes': 10}
        revised = client.put(route + '/draft', headers=owner,
                             json={'plan': PLAN, 'settings': settings_v2})
        assert revised.status_code == 200, revised.text
        assert client.post(route + '/approve', headers=owner).status_code == 200
        second = _candidate(client, 'Second')
        assert client.post(f'/api/market/opportunities/{opportunity_id}/interest',
                           headers=second).status_code == 200
        second_session = client.post('/api/ai/sessions', headers=second,
                                     json={'opportunity_id': opportunity_id, 'consent': True})
        assert second_session.status_code == 200, second_session.text
        with db.session() as session:
            first_row = session.get(AISession, first_session.json()['id'])
            second_row = session.get(AISession, second_session.json()['id'])
            assert json.loads(first_row.state)['limits']['max_questions'] == 4
            assert json.loads(second_row.state)['limits']['max_questions'] == 2
            assert json.loads(second_row.state)['limits']['time_budget_seconds'] == 600
    db.engine.dispose()
