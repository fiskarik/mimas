"""Retail interview catalog, aliases, and compatibility with existing professions."""
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_core.interview.planner import CompetencyPlan
from backend.ai_web import AISession, register_ai_routes
from backend.general_interview import Profession, ensure_professions, profession_id_for_name, provisional_rating
from backend.marketplace import CandidateProfile, Opportunity, match, opportunity_view, register_marketplace_routes
from backend.media import register_video_routes
from backend.test_assessment_flow import EphemeralDatabase, FakeStorage, FakeYandex

V1_ROWS = Path(__file__).resolve().parent / 'fixtures' / 'retail_professions_v1.json'


class CardFakeYandex(FakeYandex):
    """Answers a card evaluation; requests the first probe once per primary answer."""

    async def generate(self, *, operation='question', payload=None, **kwargs):
        card = (payload or {}).get('question_card')
        if operation != 'evaluation' or not card:
            return await super().generate(operation=operation, payload=payload, **kwargs)
        probe = 0 if card['probes'] and 'parent_turn' not in payload else None
        return json.dumps({
            'correctness': 'correct', 'depth': 'medium',
            'evidence': [{'type': 'positive', 'claim': 'Названо действие', 'quote': payload['answer']}],
            'follow_up_required': probe is not None,
            'follow_up_goal': 'Не хватает объяснения покупателю' if probe is not None else '',
            'probe_index': probe, 'anchor_level': 6 if probe is not None else 10,
            'star': ({'situation': True, 'action': True, 'result': True}
                     if card['type'] == 'behavioral' else None),
            'recommended_difficulty': 3}, ensure_ascii=False)


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
            settings = json.loads(profession.settings_json)
            assert plan.role == profession.name
            assert profession.version == 2 and plan.uses_cards and plan.not_assessed
            assert len(plan.skills) == 5
            assert all(len(skill.cards) == 1 and skill.evaluation_criteria for skill in plan.skills)
            assert all(card.variants and card.probes for skill in plan.skills for card in skill.cards)
            assert plan.skills[-1].cards[0].type == 'behavioral'
            # Every planned card fits even when probes are asked.
            assert settings == {'max_questions': 7, 'max_follow_ups': 1, 'duration_minutes': 10}
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
        assert [skill['name'] for skill in snapshot['skills']] == [
            'Точность расчёта на кассе', 'Контроль оплаты', 'Спорные ситуации с покупателем',
            'Продажа алкоголя и табака', 'Надёжность']

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


def test_unedited_v1_rows_upgrade_to_card_templates_but_reviewed_rows_stay():
    db = EphemeralDatabase()
    with db.session(write=True) as session:
        for row in json.loads(V1_ROWS.read_text(encoding='utf-8')):
            session.add(Profession(approved_at=0, **row))
        session.get(Profession, 'stock_worker').description = 'Отредактировано рецензентом'
    ensure_professions(db)
    with db.session() as session:
        for identifier in ('cashier', 'sales_associate', 'order_picker'):
            row = session.get(Profession, identifier)
            assert row.version == 2
            assert CompetencyPlan.model_validate_json(row.plan_json).uses_cards
        kept = session.get(Profession, 'stock_worker')
        assert kept.version == 1 and kept.description == 'Отредактировано рецензентом'
        assert not CompetencyPlan.model_validate_json(kept.plan_json).uses_cards
    db.engine.dispose()


def test_cashier_interview_asks_cards_probes_and_scores_by_anchors(monkeypatch):
    monkeypatch.setenv('MIMAS_MAX_ASSESSMENTS_PER_DAY', '0')
    monkeypatch.setenv('MIMAS_MONITOR_ENABLED', '0')
    db = EphemeralDatabase()
    ensure_professions(db)
    app = FastAPI()
    register_marketplace_routes(app, db, lambda _: None)
    register_ai_routes(app, db, lambda _: None)
    register_video_routes(app, db, lambda _: None)
    monkeypatch.setattr('backend.ai_web.create_llm_provider', lambda **kwargs: CardFakeYandex())
    monkeypatch.setattr('backend.media._client', lambda: FakeStorage())
    monkeypatch.setattr('backend.media._bucket', lambda: 'test-bucket')
    with db.session() as session:
        plan = CompetencyPlan.model_validate_json(session.get(Profession, 'cashier').plan_json)
    cards = [skill.cards[0] for skill in plan.skills]
    with TestClient(app) as client:
        token = client.post('/api/market/candidates', json={
            'name': 'Кандидат на кассу', 'level': 'junior', 'stack': ['Кассир'],
            'years_experience': 0}).json()['token']
        session_id = client.post('/api/ai/general-sessions', headers={'X-Candidate-Token': token}, json={
            'profession_id': 'cashier', 'consent': True, 'share_with_companies': False}).json()['id']
        access = {'X-Interview-Token': token}
        prefix = '/api/ai/sessions/' + session_id
        assert client.post(prefix + '/recording/init', headers=access).status_code == 200
        view = client.post(prefix + '/start', headers=access).json()
        asked = []
        while view['current_question']:
            question = view['current_question']
            asked.append(question)
            response = client.post(prefix + '/answers', headers=access, json={
                'question_id': question['id'], 'text': f'Ответ {len(asked)}: проверю и скажу старшему.'})
            assert response.status_code == 200, response.text
            view = response.json()
    assert all(question['generation'] == 'approved_template' for question in asked)
    # Two probes fit the 7-question budget; the remaining three cards are still asked.
    assert len(asked) == 7
    assert asked[0]['text'] in (cards[0].question, *cards[0].variants)
    assert asked[1]['text'] == cards[0].probes[0]
    assert asked[3]['text'] == cards[1].probes[0]
    assert asked[-1]['type'] == 'behavioral'
    report = view['report']
    assert report['stop_reason'] == 'plan_completed'
    assert report['template_format'] == 2 and report['scoring_rubric']['not_assessed'] == plan.not_assessed
    assert [score['points'] for score in report['card_scores']] == [10, 10, 6, 6, 6]
    assert [skill['score'] for skill in report['skills']] == [10.0, 10.0, 6.0, 6.0, 6.0]
    assert report['answer_reviews'][0]['anchor']['description'] == cards[0].anchors.acceptable
    assert provisional_rating(report) == report['overall_rating'] == {
        'score': 7.6, 'assessed_answers': 5, 'total_answers': 5, 'max_score': 10, 'provisional': True}
    db.engine.dispose()


def test_each_catalog_version_keeps_an_upgrade_path_for_unedited_rows():
    from backend.general_interview import _PRISTINE_FINGERPRINTS, _retail_templates
    for template in _retail_templates():
        # Bumping a template version requires the fingerprint of the previous one.
        assert all((template['id'], version) in _PRISTINE_FINGERPRINTS
                   for version in range(1, template['version']))
