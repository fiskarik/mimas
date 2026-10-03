"""Company applications and tenant authentication.

Only hashes of random bearer credentials are stored. An approved company can
claim its API key once through the private application link.
"""
import hashlib
import os
import secrets
import time
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Float, Text, func, select, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base, Database


def credential_hash(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class Company(Base):
    __tablename__ = 'companies'

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    contact_email: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default='pending', server_default='pending')
    key_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    claim_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    claim_expires: Mapped[float | None] = mapped_column(Float)
    created: Mapped[float] = mapped_column(Float)
    approved: Mapped[float | None] = mapped_column(Float)


class CompanyApplication(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    contact_email: str = Field(min_length=3, max_length=254)

    @field_validator('name', 'contact_email')
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Поле не должно быть пустым')
        return value

    @field_validator('contact_email')
    @classmethod
    def email_shape(cls, value: str) -> str:
        if '@' not in value or value.startswith('@') or value.endswith('@'):
            raise ValueError('Укажите адрес электронной почты')
        return value.lower()


def company_from_key(database: Database, key: str | None) -> Company:
    if not key:
        raise HTTPException(401, 'Требуется ключ работодателя')
    with database.session() as db:
        company = db.scalar(select(Company).where(Company.key_hash == credential_hash(key)))
    if not company or company.status != 'approved':
        raise HTTPException(401, 'Неверный ключ работодателя')
    return company


def ensure_legacy_company(database: Database, legacy_key: str | None) -> None:
    """Idempotently connect the pre-existing shared key to the legacy company."""
    if not legacy_key or legacy_key == 'demo-company':
        return
    with database.session(write=True) as db:
        row = db.get(Company, 'legacy')
        if not row:
            db.add(Company(id='legacy', name='MIMAS', contact_email='', status='approved',
                           key_hash=credential_hash(legacy_key), claim_hash=None,
                           claim_expires=None, created=time.time(), approved=time.time()))
        elif not row.key_hash:
            row.key_hash = credential_hash(legacy_key)
            row.status = 'approved'


def _admin_auth(value: str | None) -> None:
    configured = os.getenv('MIMAS_ADMIN_KEY', '')
    if not configured:
        raise HTTPException(503, 'Ключ администратора не настроен')
    if not value or not secrets.compare_digest(value, configured):
        raise HTTPException(401, 'Неверный ключ администратора')


def register_company_routes(app: FastAPI, database: Database) -> None:
    @app.post('/api/market/companies/apply')
    def apply(body: CompanyApplication):
        claim_token = secrets.token_urlsafe(48)
        now = time.time()
        company = Company(id=uuid4().hex, name=body.name, contact_email=body.contact_email,
                          status='pending', key_hash=None, claim_hash=credential_hash(claim_token),
                          claim_expires=now + 30 * 86400, created=now, approved=None)
        daily_limit = int(os.getenv('MIMAS_MAX_COMPANY_APPLICATIONS_PER_DAY', '20'))
        if daily_limit < 0:
            raise RuntimeError('MIMAS_MAX_COMPANY_APPLICATIONS_PER_DAY must be nonnegative')
        with database.session(write=True) as db:
            if daily_limit:
                if db.bind.dialect.name == 'postgresql':
                    # Serialize the count and insert across workers, not just
                    # within one Python process.
                    db.execute(text('SELECT pg_advisory_xact_lock(62714621)'))
                count = db.scalar(select(func.count()).select_from(Company).where(
                    Company.created >= now - 86400))
                if count >= daily_limit:
                    raise HTTPException(429, 'Дневной лимит заявок исчерпан. Повторите позже.')
            db.add(company)
        return {'application_id': company.id, 'claim_token': claim_token, 'status': 'pending'}

    def find_claim(token: str | None) -> Company:
        if not token:
            raise HTTPException(401, 'Требуется приватная ссылка заявки')
        with database.session() as db:
            company = db.scalar(select(Company).where(Company.claim_hash == credential_hash(token)))
        if not company or company.claim_expires is None or company.claim_expires < time.time():
            raise HTTPException(401, 'Приватная ссылка недоступна или устарела')
        return company

    @app.get('/api/market/companies/claim')
    def claim_status(x_claim_token: str | None = Header(None)):
        company = find_claim(x_claim_token)
        return {'application_id': company.id, 'name': company.name, 'status': company.status}

    @app.post('/api/market/companies/claim')
    def claim_key(x_claim_token: str | None = Header(None)):
        company = find_claim(x_claim_token)
        if company.status != 'approved':
            raise HTTPException(409, 'Заявка ещё не одобрена')
        key = secrets.token_urlsafe(48)
        with database.session(write=True) as db:
            row = db.scalar(select(Company).where(Company.id == company.id).with_for_update())
            if not row or row.claim_hash != credential_hash(x_claim_token or ''):
                raise HTTPException(409, 'Ключ уже выдан')
            row.key_hash = credential_hash(key)
            row.claim_hash = None
            row.claim_expires = None
        return {'application_id': company.id, 'company_key': key}

    @app.get('/api/market/admin/companies')
    def applications(x_admin_key: str | None = Header(None)):
        _admin_auth(x_admin_key)
        with database.session() as db:
            rows = list(db.scalars(select(Company).order_by(Company.created)))
        return [{'id': row.id, 'name': row.name, 'contact_email': row.contact_email,
                 'status': row.status, 'created': row.created} for row in rows]

    @app.post('/api/market/admin/companies/{company_id}/approve')
    def approve(company_id: str, x_admin_key: str | None = Header(None)):
        _admin_auth(x_admin_key)
        with database.session(write=True) as db:
            row = db.scalar(select(Company).where(Company.id == company_id).with_for_update())
            if not row:
                raise HTTPException(404, 'Заявка не найдена')
            if row.status == 'pending':
                row.status = 'approved'
                row.approved = time.time()
        return {'application_id': company_id, 'status': row.status}
