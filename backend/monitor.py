"""Opt-in staging monitor: reports observed helpers, never judges a candidate."""
import hashlib
import json
import os
import re
import secrets
import time
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Float, ForeignKey, Integer, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from backend.ai_web import AISession
from backend.companies import _admin_auth, company_from_key
from backend.database import Base, Database
from backend.marketplace import Opportunity

PAIR_TTL = 300
CLIENT_TTL = 6 * 3600
HELPER_ONLINE_TTL = 35
EXTENSION_ONLINE_TTL = 95
DETAIL_TTL = 30 * 86400
PRODUCT_KINDS = {'domain', 'executable', 'window_title', 'publisher'}
OBSERVATION_KINDS = {'running_process', 'foreground_window', 'topmost_overlay',
                     'background_tab', 'active_tab'}
COMPONENTS = ('helper', 'extension')


def enabled() -> bool:
    return (os.getenv('MIMAS_ENV', '').lower() == 'staging' and
            os.getenv('MIMAS_MONITOR_ENABLED', '').lower() in ('1', 'true', 'yes'))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class MonitorProduct(Base):
    __tablename__ = 'monitor_products'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    enabled: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    verified_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)


class MonitorSignature(Base):
    __tablename__ = 'monitor_signatures'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    product_id: Mapped[str] = mapped_column(Text, ForeignKey('monitor_products.id'))
    kind: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[float] = mapped_column(Float)
    enabled: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    updated_at: Mapped[float] = mapped_column(Float)


class MonitorSession(Base):
    __tablename__ = 'monitor_sessions'
    session_id: Mapped[str] = mapped_column(Text, ForeignKey('ai_sessions.id'), primary_key=True)
    platform: Mapped[str] = mapped_column(Text)
    consented_at: Mapped[float] = mapped_column(Float)


class MonitorPairCode(Base):
    __tablename__ = 'monitor_pair_codes'
    code_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, ForeignKey('ai_sessions.id'))
    component: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    claimed_at: Mapped[float | None] = mapped_column(Float)


class MonitorClient(Base):
    __tablename__ = 'monitor_clients'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, ForeignKey('ai_sessions.id'))
    component: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    last_seen: Mapped[float] = mapped_column(Float)
    revoked: Mapped[int] = mapped_column(Integer, default=0, server_default='0')


class MonitorObservation(Base):
    __tablename__ = 'monitor_observations'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, ForeignKey('ai_sessions.id'))
    client_id: Mapped[str | None] = mapped_column(Text, ForeignKey('monitor_clients.id'))
    event_id: Mapped[str | None] = mapped_column(Text)
    product_id: Mapped[str | None] = mapped_column(Text, ForeignKey('monitor_products.id'))
    kind: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[float] = mapped_column(Float)


class MonitorSummary(Base):
    __tablename__ = 'monitor_summaries'
    session_id: Mapped[str] = mapped_column(Text, ForeignKey('ai_sessions.id'), primary_key=True)
    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    detected_count: Mapped[int] = mapped_column(Integer, default=0, server_default='0')


class ConsentRequest(BaseModel):
    accepted: bool
    platform: str

    @field_validator('platform')
    @classmethod
    def platform_choice(cls, value):
        if value not in ('windows', 'other'):
            raise ValueError('Unknown platform')
        return value


class PairRequest(BaseModel):
    component: str

    @field_validator('component')
    @classmethod
    def component_choice(cls, value):
        if value not in COMPONENTS:
            raise ValueError('Unknown component')
        return value


class ClaimRequest(PairRequest):
    code: str = Field(min_length=16, max_length=64)


class ObservationRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=80)
    product_id: str = Field(min_length=1, max_length=80)
    kind: str
    state: str

    @field_validator('kind')
    @classmethod
    def kind_choice(cls, value):
        if value not in OBSERVATION_KINDS:
            raise ValueError('Unknown observation kind')
        return value

    @field_validator('state')
    @classmethod
    def state_choice(cls, value):
        if value not in ('detected', 'cleared'):
            raise ValueError('Unknown observation state')
        return value


class ProductCreate(BaseModel):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{1,79}$')
    name: str = Field(min_length=2, max_length=120)
    source_url: str = Field(pattern=r'^https://', max_length=500)
    category: str = Field(default='live_answer_copilot', max_length=60)
    enabled: bool = True


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    source_url: str | None = Field(default=None, pattern=r'^https://', max_length=500)
    category: str | None = Field(default=None, max_length=60)
    enabled: bool | None = None


class SignatureCreate(BaseModel):
    kind: str
    value: str = Field(min_length=2, max_length=240)
    source_url: str = Field(pattern=r'^https://', max_length=500)
    verified_installation: bool = False
    enabled: bool = True

    @field_validator('kind')
    @classmethod
    def signature_kind(cls, value):
        if value not in PRODUCT_KINDS:
            raise ValueError('Unknown signature kind')
        return value


class SignaturePatch(BaseModel):
    enabled: bool

def _require_feature():
    if not enabled():
        raise HTTPException(404, 'Мониторинг не включён')


def _candidate(db, iid: str, token: str | None, *, active=False) -> AISession:
    row = db.get(AISession, iid)
    if not row or not row.candidate_id or not row.opportunity_id or not token or not secrets.compare_digest(
            row.token_hash, _digest(token)):
        raise HTTPException(401, 'Интервью недоступно')
    if active and (row.archived or json.loads(row.state).get('phase') == 'COMPLETED'):
        raise HTTPException(409, 'Интервью завершено или архивировано')
    return row


def _client(db, token: str | None, *, active=True) -> MonitorClient:
    if not token:
        raise HTTPException(401, 'Требуется токен компонента')
    row = db.scalar(select(MonitorClient).where(MonitorClient.token_hash == _digest(token)))
    if not row or row.revoked or row.expires_at <= time.time():
        raise HTTPException(401, 'Токен компонента недоступен или истёк')
    if active:
        session = db.get(AISession, row.session_id)
        if not session or session.archived or json.loads(session.state).get('phase') == 'COMPLETED':
            raise HTTPException(409, 'Интервью завершено или архивировано')
    return row


def _component_ttl(component: str) -> int:
    return HELPER_ONLINE_TTL if component == 'helper' else EXTENSION_ONLINE_TTL


def _latest_clients(db, iid: str) -> dict[str, MonitorClient]:
    rows = db.scalars(select(MonitorClient).where(MonitorClient.session_id == iid,
                                                  MonitorClient.revoked == 0)
                      .order_by(MonitorClient.created_at.desc())).all()
    result = {}
    for row in rows:
        result.setdefault(row.component, row)
    return result


def _online(row: MonitorClient | None, now: float) -> bool:
    return bool(row and row.expires_at > now and
                row.last_seen >= now - _component_ttl(row.component))


def assert_start_ready(database: Database, iid: str, user_agent: str = '') -> None:
    """Called by the existing /start route; no gating outside staging pilot."""
    if not enabled():
        return
    with database.session() as db:
        consent = db.get(MonitorSession, iid)
        if not consent:
            raise HTTPException(409, 'Подтвердите согласие на проверку помощников.')
        windows = consent.platform == 'windows' or 'Windows' in user_agent
        if windows:
            clients = _latest_clients(db, iid)
            now = time.time()
            if not all(_online(clients.get(component), now) for component in COMPONENTS):
                raise HTTPException(409, 'Подключите Windows-помощник и расширение браузера перед интервью.')


def _record(db, *, session_id, client_id, event_id, product_id, kind, state, now):
    row = MonitorObservation(id=uuid4().hex, session_id=session_id, client_id=client_id,
                             event_id=event_id, product_id=product_id,
                             kind=kind, state=state, observed_at=now)
    db.add(row)
    return row


def _offline_kind(component: str) -> str:
    return 'agent_offline' if component == 'helper' else 'extension_offline'


def _last_state(db, *, iid, product_id, kind, client_id=None):
    query = select(MonitorObservation).where(
        MonitorObservation.session_id == iid,
        MonitorObservation.product_id == product_id,
        MonitorObservation.kind == kind)
    if client_id is not None:
        query = query.where(MonitorObservation.client_id == client_id)
    return db.scalar(query.order_by(MonitorObservation.observed_at.desc(),
                                    MonitorObservation.id.desc()).limit(1))


def _check_disconnects(db, iid: str, now: float):
    session = db.get(AISession, iid)
    if not session or json.loads(session.state).get('phase') in ('CREATED', 'COMPLETED'):
        return
    for component, client in _latest_clients(db, iid).items():
        if _online(client, now):
            continue
        kind = _offline_kind(component)
        last = _last_state(db, iid=iid, product_id=None, kind=kind)
        if not last or last.state != 'detected':
            _record(db, session_id=iid, client_id=client.id, event_id=None,
                    product_id=None, kind=kind, state='detected', now=now)
            db.flush()


def _prune(db, now: float):
    # Bounded cleanup on ordinary requests requires no paid scheduler.
    old = db.scalars(select(MonitorObservation).where(
        MonitorObservation.observed_at < now - DETAIL_TTL)
        .order_by(MonitorObservation.observed_at).limit(500)).all()
    for row in old:
        if row.state == 'detected':
            product_id = row.product_id or '__none__'
            summary = db.get(MonitorSummary, (row.session_id, product_id, row.kind))
            if not summary:
                summary = MonitorSummary(session_id=row.session_id, product_id=product_id,
                                         kind=row.kind, detected_count=0)
                db.add(summary)
                db.flush()
            summary.detected_count += 1
        db.delete(row)


def _observation_view(row, products):
    return {'id': row.id, 'product_id': row.product_id,
            'product_name': products.get(row.product_id), 'kind': row.kind,
            'state': row.state, 'observed_at': row.observed_at}


def _observations(db, iid: str):
    rows = db.scalars(select(MonitorObservation).where(
        MonitorObservation.session_id == iid)
        .order_by(MonitorObservation.observed_at.desc()).limit(500)).all()
    summaries = db.scalars(select(MonitorSummary).where(MonitorSummary.session_id == iid)).all()
    ids = {r.product_id for r in rows if r.product_id}
    ids.update(r.product_id for r in summaries if r.product_id != '__none__')
    products = {p.id: p.name for p in db.scalars(select(MonitorProduct).where(
        MonitorProduct.id.in_(ids)))} if ids else {}
    return ([_observation_view(row, products) for row in rows],
            [{'product_id': None if row.product_id == '__none__' else row.product_id,
              'product_name': products.get(row.product_id), 'kind': row.kind,
              'detected_count': row.detected_count} for row in summaries])


def _catalog(db):
    products = db.scalars(select(MonitorProduct).where(MonitorProduct.enabled == 1)
                          .order_by(MonitorProduct.id)).all()
    signatures = db.scalars(select(MonitorSignature).where(MonitorSignature.enabled == 1)).all()
    by_product = {}
    for signature in signatures:
        by_product.setdefault(signature.product_id, []).append(signature)
    result = []
    version = 0
    for product in products:
        version = max(version, int(product.updated_at * 1000))
        fields = {'domain': 'domains', 'executable': 'executables',
                  'window_title': 'window_titles', 'publisher': 'publishers'}
        item = {'id': product.id, 'name': product.name,
                'domains': [], 'executables': [], 'window_titles': [], 'publishers': []}
        for signature in by_product.get(product.id, []):
            if signature.verified_at:
                item[fields[signature.kind]].append(signature.value)
                version = max(version, int(signature.updated_at * 1000))
        result.append(item)
    return {'version': version, 'products': result}

def register_monitor_routes(app: FastAPI, database: Database) -> None:
    base = '/api/ai/sessions/{iid}/monitor'

    @app.get(base + '/status')
    def status(iid: str, x_interview_token: str | None = Header(None)):
        with database.session(write=True) as db:
            _candidate(db, iid, x_interview_token)
            if not enabled():
                return {'enabled': False, 'consented': False, 'platform': None,
                        'start_ready': True, 'components': {}, 'observations': [], 'summary': []}
            now = time.time()
            _prune(db, now)
            _check_disconnects(db, iid, now)
            consent = db.get(MonitorSession, iid)
            clients = _latest_clients(db, iid)
            components = {kind: {'paired': kind in clients,
                                 'online': _online(clients.get(kind), now),
                                 'last_seen': clients[kind].last_seen if kind in clients else None}
                          for kind in COMPONENTS}
            observations, summary = _observations(db, iid)
            ready = bool(consent) and (consent.platform != 'windows' or all(
                components[kind]['online'] for kind in COMPONENTS))
            return {'enabled': True, 'consented': bool(consent),
                    'platform': consent.platform if consent else None,
                    'start_ready': ready, 'components': components,
                    'observations': observations, 'summary': summary}

    @app.post(base + '/consent')
    def consent(iid: str, body: ConsentRequest,
                x_interview_token: str | None = Header(None)):
        _require_feature()
        if body.accepted is not True:
            raise HTTPException(422, 'Подтвердите согласие на проверку помощников.')
        with database.session(write=True) as db:
            session = _candidate(db, iid, x_interview_token, active=True)
            if json.loads(session.state).get('phase') != 'CREATED':
                raise HTTPException(409, 'Согласие задаётся до начала интервью.')
            row = db.get(MonitorSession, iid)
            if row:
                if row.platform != body.platform:
                    raise HTTPException(409, 'Платформа уже выбрана для этого интервью.')
            else:
                db.add(MonitorSession(session_id=iid, platform=body.platform,
                                      consented_at=time.time()))
        return {'consented': True, 'platform': body.platform}

    @app.post(base + '/pair')
    def pair(iid: str, body: PairRequest,
             x_interview_token: str | None = Header(None)):
        _require_feature()
        now = time.time()
        with database.session(write=True) as db:
            session = _candidate(db, iid, x_interview_token, active=True)
            consent = db.get(MonitorSession, iid)
            if not consent or consent.platform != 'windows':
                raise HTTPException(409, 'Подключение доступно после согласия на Windows.')
            if json.loads(session.state).get('phase') == 'COMPLETED':
                raise HTTPException(409, 'Интервью уже завершено')
            code = secrets.token_urlsafe(18)
            db.add(MonitorPairCode(code_hash=_digest(code), session_id=iid,
                                   component=body.component, created_at=now,
                                   expires_at=now + PAIR_TTL, claimed_at=None))
        return {'code': code, 'expires_at': now + PAIR_TTL}

    @app.post('/api/monitor/claim')
    def claim(body: ClaimRequest):
        _require_feature()
        now = time.time()
        with database.session(write=True) as db:
            pair_code = db.scalar(select(MonitorPairCode).where(
                MonitorPairCode.code_hash == _digest(body.code)).with_for_update())
            if (not pair_code or pair_code.component != body.component
                    or pair_code.claimed_at is not None or pair_code.expires_at <= now):
                raise HTTPException(401, 'Код подключения недоступен или истёк')
            session = db.get(AISession, pair_code.session_id)
            if not session or session.archived or json.loads(session.state).get('phase') == 'COMPLETED':
                raise HTTPException(409, 'Интервью недоступно')
            pair_code.claimed_at = now
            for old in db.scalars(select(MonitorClient).where(
                    MonitorClient.session_id == session.id,
                    MonitorClient.component == body.component,
                    MonitorClient.revoked == 0)):
                old.revoked = 1
            token = secrets.token_urlsafe(48)
            expires_at = now + CLIENT_TTL
            db.add(MonitorClient(id=uuid4().hex, session_id=session.id,
                                 component=body.component, token_hash=_digest(token),
                                 created_at=now, expires_at=expires_at,
                                 last_seen=now, revoked=0))
            return {'token': token, 'session_id': session.id,
                    'expires_at': expires_at}

    @app.get('/api/monitor/catalog')
    def catalog(x_monitor_token: str | None = Header(None)):
        _require_feature()
        with database.session() as db:
            _client(db, x_monitor_token)
            return _catalog(db)

    @app.post('/api/monitor/disconnect')
    def disconnect(x_monitor_token: str | None = Header(None)):
        _require_feature()
        now = time.time()
        with database.session(write=True) as db:
            client = _client(db, x_monitor_token, active=False)
            session = db.get(AISession, client.session_id)
            if session and json.loads(session.state).get('phase') not in ('CREATED', 'COMPLETED'):
                kind = _offline_kind(client.component)
                last = _last_state(db, iid=client.session_id, product_id=None, kind=kind)
                if not last or last.state != 'detected':
                    _record(db, session_id=client.session_id, client_id=client.id,
                            event_id=None, product_id=None, kind=kind,
                            state='detected', now=now)
            client.revoked = 1
        return {'ok': True}
    @app.post('/api/monitor/heartbeat')
    def heartbeat(x_monitor_token: str | None = Header(None)):
        _require_feature()
        now = time.time()
        with database.session(write=True) as db:
            client = _client(db, x_monitor_token)
            was_offline = not _online(client, now)
            if was_offline:
                _check_disconnects(db, client.session_id, now)
            client.last_seen = now
            kind = _offline_kind(client.component)
            last = _last_state(db, iid=client.session_id, product_id=None, kind=kind)
            if last and last.state == 'detected':
                _record(db, session_id=client.session_id, client_id=client.id,
                        event_id=None, product_id=None, kind=kind,
                        state='cleared', now=now)
        return {'ok': True, 'server_time': now}

    @app.post('/api/monitor/observations')
    def observe(body: ObservationRequest, x_monitor_token: str | None = Header(None)):
        _require_feature()
        now = time.time()
        with database.session(write=True) as db:
            client = _client(db, x_monitor_token)
            if ((client.component == 'extension' and body.kind not in ('background_tab', 'active_tab'))
                    or (client.component == 'helper' and body.kind not in (
                        'running_process', 'foreground_window', 'topmost_overlay'))):
                raise HTTPException(422, 'Неверный источник наблюдения')
            already = db.scalar(select(MonitorObservation).where(
                MonitorObservation.client_id == client.id,
                MonitorObservation.event_id == body.event_id))
            if already:
                return {'accepted': False, 'reason': 'duplicate'}
            product = db.get(MonitorProduct, body.product_id)
            if not product or not product.enabled:
                raise HTTPException(422, 'Продукта нет в проверенном каталоге')
            kinds = set(db.scalars(select(MonitorSignature.kind).where(
                MonitorSignature.product_id == product.id,
                MonitorSignature.enabled == 1,
                MonitorSignature.verified_at.is_not(None))))
            needed = ({'domain'} if client.component == 'extension' else
                      {'executable', 'window_title', 'publisher'})
            if not kinds.intersection(needed):
                raise HTTPException(422, 'Нет проверенного признака для этого источника')
            last = _last_state(db, iid=client.session_id, product_id=product.id,
                               kind=body.kind, client_id=client.id)
            if (last and last.state == body.state) or (not last and body.state == 'cleared'):
                return {'accepted': False, 'reason': 'unchanged'}
            _prune(db, now)
            _record(db, session_id=client.session_id, client_id=client.id,
                    event_id=body.event_id, product_id=product.id, kind=body.kind,
                    state=body.state, now=now)
            client.last_seen = now
        return {'accepted': True, 'observed_at': now}

    @app.get('/api/market/company/assessments/{iid}/monitor')
    def employer_report(iid: str, x_company_key: str | None = Header(None)):
        company = company_from_key(database, x_company_key)
        with database.session(write=True) as db:
            row = db.get(AISession, iid)
            opportunity = db.get(Opportunity, row.opportunity_id) if row and row.opportunity_id else None
            if not row or not opportunity or opportunity.company_id != company.id:
                raise HTTPException(404, 'Отчёт не найден')
            now = time.time()
            _prune(db, now)
            if enabled():
                _check_disconnects(db, iid, now)
            observations, summary = _observations(db, iid)
            return {'session_id': iid, 'enabled': enabled(), 'observations': observations,
                    'summary': summary, 'automatic_penalty': False}

    @app.get('/api/monitor/admin/products')
    def admin_products(x_admin_key: str | None = Header(None)):
        _require_feature()
        _admin_auth(x_admin_key)
        with database.session() as db:
            products = db.scalars(select(MonitorProduct).order_by(MonitorProduct.id)).all()
            signatures = db.scalars(select(MonitorSignature)).all()
            return {'products': [{
                'id': p.id, 'name': p.name, 'source_url': p.source_url,
                'category': p.category, 'enabled': bool(p.enabled),
                'verified_at': p.verified_at, 'updated_at': p.updated_at,
                'signatures': [{'id': s.id, 'kind': s.kind, 'value': s.value,
                                'source_url': s.source_url, 'verified_at': s.verified_at,
                                'enabled': bool(s.enabled)}
                               for s in signatures if s.product_id == p.id]}
                for p in products]}

    @app.post('/api/monitor/admin/products')
    def add_product(body: ProductCreate, x_admin_key: str | None = Header(None)):
        _require_feature()
        _admin_auth(x_admin_key)
        now = time.time()
        with database.session(write=True) as db:
            if db.get(MonitorProduct, body.id):
                raise HTTPException(409, 'Продукт уже есть')
            db.add(MonitorProduct(id=body.id, name=body.name,
                                  source_url=body.source_url,
                                  category=body.category, enabled=int(body.enabled),
                                  verified_at=now, updated_at=now))
        return {'id': body.id}

    @app.patch('/api/monitor/admin/products/{product_id}')
    def edit_product(product_id: str, body: ProductPatch,
                     x_admin_key: str | None = Header(None)):
        _require_feature()
        _admin_auth(x_admin_key)
        with database.session(write=True) as db:
            row = db.get(MonitorProduct, product_id)
            if not row:
                raise HTTPException(404, 'Продукт не найден')
            for key, value in body.model_dump(exclude_unset=True).items():
                if value is None:
                    raise HTTPException(422, 'Поля не могут быть пустыми')
                setattr(row, key, int(value) if key == 'enabled' else value)
            row.updated_at = time.time()
        return {'id': product_id, 'updated': True}

    @app.post('/api/monitor/admin/products/{product_id}/signatures')
    def add_signature(product_id: str, body: SignatureCreate,
                      x_admin_key: str | None = Header(None)):
        _require_feature()
        _admin_auth(x_admin_key)
        if body.kind != 'domain' and not body.verified_installation:
            raise HTTPException(422, 'Проверьте признак на установленной версии программы.')
        value = body.value.strip().lower() if body.kind == 'domain' else body.value.strip()
        if body.kind == 'domain' and (not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', value)
                                      or value.startswith('-')):
            raise HTTPException(422, 'Укажите домен без схемы и пути')
        with database.session(write=True) as db:
            product = db.get(MonitorProduct, product_id)
            if not product:
                raise HTTPException(404, 'Продукт не найден')
            exists = db.scalar(select(MonitorSignature).where(
                MonitorSignature.product_id == product_id,
                MonitorSignature.kind == body.kind,
                MonitorSignature.value == value))
            if exists:
                raise HTTPException(409, 'Признак уже есть')
            now = time.time()
            sid = uuid4().hex
            db.add(MonitorSignature(id=sid, product_id=product_id,
                                    kind=body.kind, value=value,
                                    source_url=body.source_url,
                                    verified_at=now, enabled=int(body.enabled),
                                    updated_at=now))
            product.updated_at = now
        return {'id': sid}

    @app.patch('/api/monitor/admin/signatures/{signature_id}')
    def edit_signature(signature_id: str, body: SignaturePatch,
                       x_admin_key: str | None = Header(None)):
        _require_feature()
        _admin_auth(x_admin_key)
        with database.session(write=True) as db:
            row = db.get(MonitorSignature, signature_id)
            if not row:
                raise HTTPException(404, 'Признак не найден')
            now = time.time()
            row.enabled = int(body.enabled)
            row.updated_at = now
            db.get(MonitorProduct, row.product_id).updated_at = now
        return {'id': signature_id, 'enabled': body.enabled}
