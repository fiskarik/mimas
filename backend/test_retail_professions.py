"""Retail interview catalog, aliases, and compatibility with existing professions."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_core.interview.planner import CompetencyPlan
from backend.ai_web import AISession, register_ai_routes
from backend.general_interview import Profession, ensure_professions, profession_id_for_name
from backend.marketplace import CandidateProfile, Opportunity, match, opportunity_view, register_marketplace_routes
from backend.test_assessment_flow import EphemeralDatabase, FakeYandex


def test_retail_catalog_is_reviewed_and_legacy_interviews_remain_addressable():
    db = EphemeralDatabase()
    ensure_professions(db)
    # Startup must not replace a plan edited by a reviewer.
    with db.session(write=True) as session:
        edited = session.get(Profession, 'cashier')
        edited.description = 'Утверждённая редакция'
        original_plan = edited.plan_json
    ensure_professions(db)

    app = FastAPI()
    register_marketplace_routes(app, db, lambda _: None)
    with TestClient(app) as client:
        choices = client.get('/api/market/professions')
        assert choices.status_code == 200
        assert {item['id'] for item in choices.json()} == {
            'cashier', 'sales_associate', 'order_picker', 'stock_worker'}

    with db.session() as session:
        for identifier in ('cashier', 'sales_associate', 'order_picker', 'stock_worker'):
            profession = session.get(Profession, identifier)
            plan = CompetencyPlan.model_validate_json(profession.plan_json)
            assert plan.role == profession.name
            assert len(plan.skills) == 2
            assert all(skill.evaluation_criteria and len(skill.questions) == len(skill.goals)
                       for skill in plan.skills)
        assert session.get(Profession, 'cashier').description == 'Утверждённая редакция'
        assert session.get(Profession, 'cashier').plan_json == original_plan
        assert session.get(Profession, 'welder') is not None
    db.engine.dispose()


def test_retail_aliases_share_profession_and_match_vacancy(monkeypatch):
    monkeypatch.setenv('MIMAS_MAX_ASSESSMENTS_PER_DAY', '0')
    db = EphemeralDatabase()
    ensure_professions(db)
    app = FastAPI()
    register_marketplace_routes(app, db, lambda _: None)
    register_ai_routes(app, db, lambda _: None)
    monkeypatch.setattr('backend.ai_web.create_llm_provider', lambda **kwargs: FakeYandex())

    assert profession_id_for_name(' Кассир ') == 'cashier'
    assert profession_id_for_name('Продавец') == 'cashier'
    assert profession_id_for_name('Сотрудник торгового зала') == 'sales_associate'
    assert profession_id_for_name('Комплектовщик') == 'order_picker'
    assert profession_id_for_name('Кладовщик') == 'stock_worker'
    assert profession_id_for_name('Сварщик') == 'welder'

    with TestClient(app) as client:
        created = client.post('/api/market/candidates', json={
            'name': 'Кандидат магазина', 'level': 'junior',
            'stack': ['Кассир', 'Работа с покупателями'], 'years_experience': 1})
        assert created.status_code == 200, created.text
        token = created.json()['token']
        assert created.json()['profile']['profession_id'] == 'cashier'
        assert client.get('/api/market/me', headers={
            'X-Candidate-Token': token}).json()['profile']['profession_id'] == 'cashier'
        response = client.post('/api/ai/general-sessions',
                               headers={'X-Candidate-Token': token},
                               json={'profession_id': 'cashier', 'consent': True,
                                     'share_with_companies': False})
        assert response.status_code == 200, response.text
        with db.session() as session:
            interview = session.get(AISession, response.json()['id'])
            snapshot = json.loads(interview.state)['plan_snapshot']
        assert snapshot['role'] == 'Продавец-кассир'
        assert {skill['name'] for skill in snapshot['skills']} == {
            'Точность расчёта на кассе', 'Обслуживание и сложные ситуации'}

    candidate = CandidateProfile(
        id='candidate', token_hash='hash', name='Кандидат магазина',
        level='junior', stack=json.dumps(['Кассир', 'Работа с покупателями']),
        years_experience=1, github_url=None, desired_salary_rub=None,
        discoverable=1, created=0)
    vacancy = Opportunity(
        id='job', company_id='company', company_name='Тестовый магазин',
        title='Продавец-кассир', description='Работа на кассе и с покупателями',
        level='junior', stack=json.dumps(['Продавец-кассир', 'Работа с покупателями']),
        salary_min_rub=None, salary_max_rub=None,
        employment_type='full_time', status='open', created=0)
    assert opportunity_view(vacancy)['profession_id'] == 'cashier'
    assert match(candidate, vacancy)['stack_overlap'] == 2
    assert match(candidate, vacancy)['compatible']
    db.engine.dispose()


def test_retail_profiles_hide_legacy_vacancies_but_old_profiles_keep_access():
    db = EphemeralDatabase()
    ensure_professions(db)
    with db.session(write=True) as session:
        session.add_all([
            Opportunity(
                id='retail-job', company_id='company', company_name='Магазин',
                title='Продавец-кассир', description='Касса и помощь покупателям',
                level='junior', stack=json.dumps(['Продавец-кассир']),
                salary_min_rub=None, salary_max_rub=None,
                employment_type='full_time', status='open', created=1),
            Opportunity(
                id='old-job', company_id='company', company_name='Мастерская',
                title='Сварщик', description='Старый пилот',
                level='junior', stack=json.dumps(['Сварщик']),
                salary_min_rub=None, salary_max_rub=None,
                employment_type='full_time', status='open', created=2),
        ])
    app = FastAPI()
    register_marketplace_routes(app, db, lambda _: None)
    with TestClient(app) as client:
        retail = client.post('/api/market/candidates', json={
            'name': 'Кандидат магазина', 'level': 'junior',
            'stack': ['Кассир'], 'years_experience': 0}).json()['token']
        legacy = client.post('/api/market/candidates', json={
            'name': 'Старый кандидат', 'level': 'junior',
            'stack': ['Сварщик'], 'years_experience': 1}).json()['token']
        retail_jobs = client.get('/api/market/opportunities',
                                 headers={'X-Candidate-Token': retail}).json()
        legacy_jobs = client.get('/api/market/opportunities',
                                 headers={'X-Candidate-Token': legacy}).json()
    assert {item['id'] for item in retail_jobs} == {'retail-job'}
    assert 'old-job' in {item['id'] for item in legacy_jobs}
    db.engine.dispose()
