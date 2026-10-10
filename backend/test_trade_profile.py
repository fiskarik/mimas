"""A trade profile must keep its own profession in both candidate and employer views."""
import json

from backend.marketplace import CandidateProfile, Opportunity, match, profile_view


def test_welder_profile_and_matching_use_profession_and_skills():
    candidate = CandidateProfile(
        id='candidate', token_hash='hash', name='Тестовый кандидат',
        level='middle', stack=json.dumps(['Сварщик', 'Ручная дуговая сварка', 'Чтение чертежей']),
        years_experience=3, github_url=None, desired_salary_rub=90000,
        discoverable=1, created=0,
    )
    vacancy = Opportunity(
        id='job', company_id='company', company_name='Тестовая компания',
        title='Сварщик', description='Сварка конструкций и чтение чертежей',
        level='middle', stack=json.dumps(['Сварщик', 'Чтение чертежей']),
        salary_min_rub=80000, salary_max_rub=120000,
        employment_type='full_time', status='open', created=0,
    )

    profile = profile_view(candidate)
    assert profile['role'] == 'Сварщик'
    assert profile['stack'][1] == 'Ручная дуговая сварка'
    result = match(candidate, vacancy)
    assert result['compatible']
    assert result['stack_overlap'] == 2
    assert result['reasons'][0].startswith('Совпадают навыки:')
