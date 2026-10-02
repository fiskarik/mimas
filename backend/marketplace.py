"""Candidate profiles, posted opportunities and reusable AI assessments."""
import hashlib
import json
import os
import secrets
import threading
import time
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Float, ForeignKey, Integer, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base, Database


LEVELS = ('junior', 'middle', 'senior')
LevelName = Literal['junior', 'middle', 'senior']


class CandidateProfile(Base):
    __tablename__ = 'candidate_profiles'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text)
    stack: Mapped[str] = mapped_column(Text)
    years_experience: Mapped[float] = mapped_column(Float)
    github_url: Mapped[str | None] = mapped_column(Text)
    desired_salary_rub: Mapped[int | None] = mapped_column(Integer)
    discoverable: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    created: Mapped[float] = mapped_column(Float)


class Opportunity(Base):
    __tablename__ = 'opportunities'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    company_name: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text)
    stack: Mapped[str] = mapped_column(Text)
    salary_min_rub: Mapped[int | None] = mapped_column(Integer)
    salary_max_rub: Mapped[int | None] = mapped_column(Integer)
    employment_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default='open', server_default='open')
    created: Mapped[float] = mapped_column(Float)


class CandidateInterest(Base):
    __tablename__ = 'candidate_interests'
    candidate_id: Mapped[str] = mapped_column(Text, ForeignKey('candidate_profiles.id'), primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(Text, ForeignKey('opportunities.id'), primary_key=True)
    created: Mapped[float] = mapped_column(Float)


class CandidateAssessment(Base):
    __tablename__ = 'candidate_assessments'
    candidate_id: Mapped[str] = mapped_column(Text, ForeignKey('candidate_profiles.id'), primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, ForeignKey('ai_sessions.id'), unique=True)
    created: Mapped[float] = mapped_column(Float)


def clean_stack(values: list[str]) -> list[str]:
    result, seen = [], set()
    for value in values:
        item = value.strip()
        if item and item.casefold() not in seen:
            result.append(item)
            seen.add(item.casefold())
    if not result or any(len(item) > 40 for item in result):
        raise ValueError('Укажите технологии длиной до 40 символов')
    return result


class CandidateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    level: LevelName
    stack: list[str] = Field(min_length=1, max_length=20)
    years_experience: float = Field(ge=0, le=60)
    github_url: str | None = Field(default=None, max_length=300)
    desired_salary_rub: int | None = Field(default=None, ge=0, le=10_000_000)

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Укажите имя или псевдоним')
        return value.strip()

    @field_validator('stack')
    @classmethod
    def stack_not_blank(cls, values):
        return clean_stack(values)

    @field_validator('github_url')
    @classmethod
    def valid_github(cls, value):
        if value and not (value.startswith('https://github.com/') or value.startswith('https://gitlab.com/')):
            raise ValueError('Укажите ссылку на GitHub или GitLab')
        return value


class Visibility(BaseModel):
    discoverable: bool


class OpportunityStatus(BaseModel):
    status: Literal['open', 'closed']


class OpportunityCreate(BaseModel):
    company_name: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=10, max_length=4000)
    level: LevelName
    stack: list[str] = Field(min_length=1, max_length=20)
    salary_min_rub: int | None = Field(default=None, ge=0, le=10_000_000)
    salary_max_rub: int | None = Field(default=None, ge=0, le=10_000_000)
    employment_type: Literal['full_time', 'contract'] = 'full_time'

    @field_validator('stack')
    @classmethod
    def stack_not_blank(cls, values):
        return clean_stack(values)


def candidate_from_token(database: Database, token: str | None) -> CandidateProfile:
    if not token:
        raise HTTPException(401, 'Требуется ключ кандидата')
    digest = hashlib.sha256(token.encode()).hexdigest()
    with database.session() as db:
        row = db.scalar(select(CandidateProfile).where(CandidateProfile.token_hash == digest))
    if not row:
        raise HTTPException(401, 'Профиль кандидата недоступен')
    return row


def profile_view(row: CandidateProfile) -> dict:
    return {'id': row.id, 'name': row.name, 'role': 'Python Backend Developer',
            'level': row.level, 'stack': json.loads(row.stack),
            'years_experience': row.years_experience, 'github_url': row.github_url,
            'desired_salary_rub': row.desired_salary_rub, 'discoverable': bool(row.discoverable)}


def opportunity_view(row: Opportunity) -> dict:
    return {'id': row.id, 'company_name': row.company_name, 'title': row.title,
            'description': row.description, 'role': 'Python Backend Developer',
            'level': row.level, 'stack': json.loads(row.stack),
            'salary_min_rub': row.salary_min_rub, 'salary_max_rub': row.salary_max_rub,
            'employment_type': row.employment_type, 'status': row.status}


def match(profile: CandidateProfile, opportunity: Opportunity) -> dict:
    wanted = {item.casefold() for item in json.loads(opportunity.stack)}
    offered = {item.casefold() for item in json.loads(profile.stack)}
    overlap = wanted & offered
    level_gap = abs(LEVELS.index(profile.level) - LEVELS.index(opportunity.level))
    salary_ok = (profile.desired_salary_rub is None or opportunity.salary_max_rub is None
                 or profile.desired_salary_rub <= opportunity.salary_max_rub)
    score = len(overlap) * 3 + (2 if level_gap == 0 else 1 if level_gap == 1 else 0) + int(salary_ok)
    reasons = [f'Совпадают технологии: {", ".join(sorted(overlap))}' if overlap else 'Совпадений по стеку пока нет']
    if level_gap == 0:
        reasons.append('Совпадает уровень')
    elif level_gap > 1:
        reasons.append('Уровень отличается более чем на одну ступень')
    if not salary_ok:
        reasons.append('Зарплатное ожидание выше верхней границы вакансии')
    return {'score': score, 'reasons': reasons, 'stack_overlap': len(overlap),
            'level_match': level_gap == 0, 'salary_match': salary_ok,
            'compatible': bool(overlap) and level_gap <= 1 and salary_ok}


def register_marketplace_routes(app: FastAPI, database: Database, authorize_company):
    signup_gate = threading.Lock()
    daily_limit = int(os.getenv('MIMAS_MAX_CANDIDATES_PER_DAY',
                              '50' if os.getenv('MIMAS_ENV', '').lower() == 'production' else '0'))
    if daily_limit < 0:
        raise ValueError('MIMAS_MAX_CANDIDATES_PER_DAY must be nonnegative')

    @app.post('/api/market/candidates')
    def create_candidate(body: CandidateCreate):
        token = secrets.token_urlsafe(32)
        row = CandidateProfile(id=uuid4().hex, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                               name=body.name, level=body.level, stack=json.dumps(body.stack, ensure_ascii=False),
                               years_experience=body.years_experience, github_url=body.github_url,
                               desired_salary_rub=body.desired_salary_rub, created=time.time())
        with signup_gate:
            with database.session(write=True) as db:
                if daily_limit:
                    created_today = db.scalar(select(func.count()).select_from(CandidateProfile).where(
                        CandidateProfile.created >= time.time() - 86400))
                    if created_today >= daily_limit:
                        raise HTTPException(429, 'Бесплатный дневной лимит регистраций исчерпан. Повторите позже.')
                db.add(row)
        return {'token': token, 'profile': profile_view(row)}

    @app.get('/api/market/me')
    def get_my_profile(x_candidate_token: str | None = Header(None)):
        profile = candidate_from_token(database, x_candidate_token)
        from backend.ai_web import AISession
        from backend.ai_presenter import session_view
        with database.session() as db:
            interests = list(db.scalars(select(CandidateInterest.opportunity_id).where(
                CandidateInterest.candidate_id == profile.id)))
            assessment = db.get(CandidateAssessment, profile.id)
            session = db.get(AISession, assessment.session_id) if assessment else None
        return {'profile': profile_view(profile), 'interested_opportunity_ids': interests,
                'assessment': session_view(session) if session else None}

    @app.patch('/api/market/me')
    def change_visibility(body: Visibility, x_candidate_token: str | None = Header(None)):
        profile = candidate_from_token(database, x_candidate_token)
        with database.session(write=True) as db:
            db.get(CandidateProfile, profile.id).discoverable = int(body.discoverable)
        profile.discoverable = int(body.discoverable)
        return profile_view(profile)

    @app.get('/api/market/opportunities')
    def list_opportunities(x_candidate_token: str | None = Header(None)):
        profile = candidate_from_token(database, x_candidate_token)
        with database.session() as db:
            rows = list(db.scalars(select(Opportunity).where(Opportunity.status == 'open')))
            selected = set(db.scalars(select(CandidateInterest.opportunity_id).where(
                CandidateInterest.candidate_id == profile.id)))
        found = [{**opportunity_view(row), 'match': match(profile, row), 'interested': row.id in selected}
                 for row in rows]
        return sorted(found, key=lambda item: (-item['match']['score'], item['title']))

    @app.post('/api/market/opportunities/{opportunity_id}/interest')
    def express_interest(opportunity_id: str, x_candidate_token: str | None = Header(None)):
        profile = candidate_from_token(database, x_candidate_token)
        with database.session(write=True) as db:
            opportunity = db.get(Opportunity, opportunity_id)
            if not opportunity or opportunity.status != 'open':
                raise HTTPException(404, 'Возможность не найдена')
            if not db.get(CandidateInterest, (profile.id, opportunity_id)):
                db.add(CandidateInterest(candidate_id=profile.id, opportunity_id=opportunity_id, created=time.time()))
        return {'opportunity_id': opportunity_id, 'interested': True}

    @app.get('/api/market/company/opportunities')
    def company_opportunities(x_company_key: str | None = Header(None)):
        authorize_company(x_company_key)
        with database.session() as db:
            rows = list(db.scalars(select(Opportunity).order_by(Opportunity.created.desc())))
        return [opportunity_view(row) for row in rows]

    @app.post('/api/market/company/opportunities')
    def create_opportunity(body: OpportunityCreate, x_company_key: str | None = Header(None)):
        authorize_company(x_company_key)
        if (body.salary_min_rub is not None and body.salary_max_rub is not None
                and body.salary_min_rub > body.salary_max_rub):
            raise HTTPException(422, 'Минимальная зарплата выше максимальной')
        row = Opportunity(id=uuid4().hex, company_name=body.company_name.strip(),
                          title=body.title.strip(), description=body.description.strip(),
                          level=body.level, stack=json.dumps(body.stack, ensure_ascii=False),
                          salary_min_rub=body.salary_min_rub, salary_max_rub=body.salary_max_rub,
                          employment_type=body.employment_type, created=time.time())
        with database.session(write=True) as db:
            db.add(row)
        return opportunity_view(row)

    @app.patch('/api/market/company/opportunities/{opportunity_id}')
    def change_opportunity_status(opportunity_id: str, body: OpportunityStatus,
                                  x_company_key: str | None = Header(None)):
        authorize_company(x_company_key)
        with database.session(write=True) as db:
            row = db.get(Opportunity, opportunity_id)
            if not row:
                raise HTTPException(404, 'Возможность не найдена')
            row.status = body.status
        return opportunity_view(row)

    @app.get('/api/market/company/candidates')
    def discover_candidates(opportunity_id: str | None = None, x_company_key: str | None = Header(None)):
        authorize_company(x_company_key)
        from backend.ai_web import AISession
        from backend.ai_presenter import session_view
        with database.session() as db:
            opportunity = db.get(Opportunity, opportunity_id) if opportunity_id else None
            if opportunity_id and not opportunity:
                raise HTTPException(404, 'Возможность не найдена')
            profiles = list(db.scalars(select(CandidateProfile).where(CandidateProfile.discoverable == 1)))
            assessments = {a.candidate_id: a for a in db.scalars(select(CandidateAssessment))}
            ids = [a.session_id for a in assessments.values()]
            sessions = {s.id: s for s in db.scalars(select(AISession).where(AISession.id.in_(ids)))} if ids else {}
            interests = {(i.candidate_id, i.opportunity_id) for i in db.scalars(select(CandidateInterest))}
        result = []
        for profile in profiles:
            assessment = assessments.get(profile.id)
            session = sessions.get(assessment.session_id) if assessment else None
            if not session:
                continue
            public_session = session_view(session)
            report = public_session['report']
            if not report:
                continue
            question_texts = {q['id']: q['text'] for q in public_session['questions']}
            item = {'profile': profile_view(profile), 'assessment_id': session.id,
                    'summary': report['overall_technical_summary'],
                    'skills': [{**{k: skill[k] for k in ('skill', 'demonstrated_level', 'status',
                                                       'answers_received', 'evaluated_answers')},
                                'evidence': [{**e, 'question_text': question_texts.get(e['question_id'], '')}
                                             for e in skill['evidence']]}
                               for skill in report['skills']],
                    'quality_status': report['quality_status']}
            if opportunity:
                item['match'] = match(profile, opportunity)
                item['interested'] = (profile.id, opportunity.id) in interests
            result.append(item)
        return sorted(result, key=lambda item: -item.get('match', {}).get('score', 0))
