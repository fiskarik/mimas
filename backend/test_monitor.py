"""Staging monitor API: consent, pairings, tenant isolation and retention."""
from contextlib import contextmanager
import hashlib
import json
import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.companies import Company
from backend.marketplace import Opportunity
from backend.ai_web import AISession
from backend.monitor import (
    MonitorObservation, MonitorProduct, MonitorSignature, MonitorSummary,
    assert_start_ready, register_monitor_routes,
)
import backend.media  # noqa: F401: register all mapped foreign keys
import backend.yandex_budget  # noqa: F401


class EphemeralDatabase:
    def __init__(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self, *, write=False, interview_id=None):
        with self.sessions() as db:
            with db.begin():
                yield db


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def setup_monitor(monkeypatch):
    monkeypatch.setenv('MIMAS_ENV', 'staging')
    monkeypatch.setenv('MIMAS_MONITOR_ENABLED', '1')
    monkeypatch.setenv('MIMAS_ADMIN_KEY', 'admin-secret')
    database = EphemeralDatabase()
    now = time.time()
    with database.session(write=True) as db:
        for cid, key in [('first', 'first-key'), ('second', 'second-key')]:
            db.add(Company(id=cid, name=cid, contact_email=cid+'@example.com',
                           status='approved', key_hash=digest(key), claim_hash=None,
                           claim_expires=None, created=now, approved=now))
        db.add(Opportunity(id='vacancy', company_id='first', company_name='First',
                           title='Backend', description='Build an API', level='middle',
                           stack='[]', salary_min_rub=None, salary_max_rub=None,
                           employment_type='full_time', status='open', created=now))
        db.add(AISession(id='session', token_hash=digest('candidate-key'), model='test',
                         started=now, state=json.dumps({'phase': 'CREATED'}), trace='[]',
                         pending=None, candidate_id='candidate', opportunity_id='vacancy',
                         archived=0))
        db.add(MonitorProduct(id='known', name='Known Helper', source_url='https://known.example',
                              category='live_answer_copilot', enabled=1,
                              verified_at=now, updated_at=now))
        db.add(MonitorSignature(id='domain', product_id='known', kind='domain',
                                value='known.example', source_url='https://known.example',
                                verified_at=now, enabled=1, updated_at=now))
        db.add(MonitorSignature(id='exe', product_id='known', kind='executable',
                                value='KnownHelper.exe', source_url='https://known.example',
                                verified_at=now, enabled=1, updated_at=now))
    app = FastAPI()
    register_monitor_routes(app, database)
    with TestClient(app) as client:
        yield client, database
    database.engine.dispose()


def candidate():
    return {'X-Interview-Token': 'candidate-key'}


def pair(client, component):
    issued = client.post('/api/ai/sessions/session/monitor/pair', headers=candidate(),
                         json={'component': component})
    assert issued.status_code == 200, issued.text
    code = issued.json()['code']
    claimed = client.post('/api/monitor/claim', json={'code': code, 'component': component})
    assert claimed.status_code == 200, claimed.text
    assert client.post('/api/monitor/claim', json={'code': code, 'component': component}).status_code == 401
    return {'X-Monitor-Token': claimed.json()['token']}


@pytest.mark.parametrize('platform', ['windows', 'other'])
def test_consent_starts_without_components_and_tenant_isolation(setup_monitor, platform):
    client, database = setup_monitor
    assert client.get('/api/ai/sessions/session/monitor/status').status_code == 401
    status = client.get('/api/ai/sessions/session/monitor/status', headers=candidate()).json()
    assert status['enabled'] and not status['start_ready']
    with pytest.raises(HTTPException) as blocked:
        assert_start_ready(database, 'session', 'Windows Chrome')
    assert blocked.value.status_code == 409
    assert client.post('/api/ai/sessions/session/monitor/consent', headers=candidate(),
                       json={'accepted': True, 'platform': platform}).status_code == 200
    assert_start_ready(database, 'session', 'Windows Chrome')
    status = client.get('/api/ai/sessions/session/monitor/status', headers=candidate()).json()
    assert status['start_ready'] and not status['components']['extension']['online']
    assert not status['components']['helper']['online']
    assert client.get('/api/market/company/assessments/session/monitor',
                      headers={'X-Company-Key': 'second-key'}).status_code == 404
    assert client.get('/api/market/company/assessments/session/monitor',
                      headers={'X-Company-Key': 'first-key'}).status_code == 200


def test_optional_extension_can_pair_after_consent_on_any_platform(setup_monitor):
    client, database = setup_monitor
    assert client.post('/api/ai/sessions/session/monitor/pair', headers=candidate(),
                       json={'component': 'extension'}).status_code == 409
    assert client.post('/api/ai/sessions/session/monitor/consent', headers=candidate(),
                       json={'accepted': True, 'platform': 'other'}).status_code == 200
    extension = pair(client, 'extension')
    assert client.get('/api/monitor/catalog', headers=extension).json()['products'][0]['domains'] == ['known.example']
    assert client.post('/api/monitor/heartbeat', headers=extension).status_code == 200
    assert_start_ready(database, 'session')
    assert client.get('/api/ai/sessions/session/monitor/status', headers=candidate()).json()['components']['extension']['online']


def test_observation_dedup_source_and_retention(setup_monitor):
    client, database = setup_monitor
    client.post('/api/ai/sessions/session/monitor/consent', headers=candidate(),
                json={'accepted': True, 'platform': 'windows'})
    extension = pair(client, 'extension')
    base = {'event_id': 'first-event', 'product_id': 'known',
            'kind': 'background_tab', 'state': 'detected'}
    assert client.post('/api/monitor/observations', headers=extension,
                       json={**base, 'kind': 'running_process'}).status_code == 422
    first = client.post('/api/monitor/observations', headers=extension, json=base)
    assert first.status_code == 200 and first.json()['accepted']
    duplicate = client.post('/api/monitor/observations', headers=extension, json=base).json()
    assert duplicate == {'accepted': False, 'reason': 'duplicate'}
    assert client.post('/api/monitor/observations', headers=extension,
                       json={**base, 'event_id': 'wrong-product', 'product_id': 'unknown'}).status_code == 422
    report = client.get('/api/market/company/assessments/session/monitor',
                        headers={'X-Company-Key': 'first-key'}).json()
    assert report['automatic_penalty'] is False
    assert len(report['observations']) == 1
    assert report['observations'][0]['kind'] == 'background_tab'
    with database.session(write=True) as db:
        row = db.query(MonitorObservation).one()
        row.observed_at = time.time() - 31 * 86400
    after = client.get('/api/market/company/assessments/session/monitor',
                       headers={'X-Company-Key': 'first-key'}).json()
    assert after['observations'] == []
    assert after['summary'] == [{'product_id': 'known', 'product_name': 'Known Helper',
                                 'kind': 'background_tab', 'detected_count': 1}]
    with database.session() as db:
        assert db.query(MonitorSummary).one().detected_count == 1


def test_optional_extension_disconnect_warns_without_ending_interview(setup_monitor):
    client, database = setup_monitor
    client.post('/api/ai/sessions/session/monitor/consent', headers=candidate(),
                json={'accepted': True, 'platform': 'windows'})
    extension = pair(client, 'extension')
    with database.session(write=True) as db:
        db.get(AISession, 'session').state = json.dumps({'phase': 'WAITING_FOR_ANSWER'})
    assert client.post('/api/monitor/disconnect', headers=extension).status_code == 200
    status = client.get('/api/ai/sessions/session/monitor/status', headers=candidate()).json()
    assert status['start_ready'] and not status['components']['extension']['online']
    assert any(item['kind'] == 'extension_offline' for item in status['observations'])
    assert_start_ready(database, 'session', 'Windows Chrome')
    assert client.get('/api/market/company/assessments/session/monitor',
                      headers={'X-Company-Key': 'first-key'}).status_code == 200


def test_admin_only_verified_signatures_and_explicit_flag(setup_monitor, monkeypatch):
    client, _ = setup_monitor
    base = '/api/monitor/admin/products'
    assert client.get(base).status_code == 401
    admin = {'X-Admin-Key': 'admin-secret'}
    assert client.get(base, headers=admin).status_code == 200
    created = client.post(base, headers=admin, json={
        'id': 'new-tool', 'name': 'New Tool', 'source_url': 'https://example.org'})
    assert created.status_code == 200
    signature = client.post(base+'/new-tool/signatures', headers=admin, json={
        'kind': 'executable', 'value': 'NewTool.exe', 'source_url': 'https://example.org'})
    assert signature.status_code == 422
    signature = client.post(base+'/new-tool/signatures', headers=admin, json={
        'kind': 'executable', 'value': 'NewTool.exe', 'source_url': 'https://example.org',
        'verified_installation': True})
    assert signature.status_code == 200
    monkeypatch.setenv('MIMAS_ENV', 'production')
    assert client.get(base, headers=admin).status_code == 200
    assert client.get('/api/ai/sessions/session/monitor/status', headers=candidate()).json()['enabled'] is True
    monkeypatch.setenv('MIMAS_MONITOR_ENABLED', '0')
    assert client.get(base, headers=admin).status_code == 404
    assert client.get('/api/ai/sessions/session/monitor/status', headers=candidate()).json()['enabled'] is False


def test_helper_pairing_disabled_and_expired_extension_codes_rejected(setup_monitor):
    client, database = setup_monitor
    client.post('/api/ai/sessions/session/monitor/consent', headers=candidate(),
                json={'accepted': True, 'platform': 'windows'})
    assert client.post('/api/ai/sessions/session/monitor/pair', headers=candidate(),
                       json={'component': 'helper'}).status_code == 422
    issue = client.post('/api/ai/sessions/session/monitor/pair', headers=candidate(),
                        json={'component': 'extension'})
    assert issue.status_code == 200
    code = issue.json()['code']
    assert client.post('/api/monitor/claim',
                       json={'code': code, 'component': 'helper'}).status_code == 422
    from backend.monitor import MonitorPairCode
    with database.session(write=True) as db:
        db.get(MonitorPairCode, digest(code)).expires_at = time.time() - 1
    assert client.post('/api/monitor/claim',
                       json={'code': code, 'component': 'extension'}).status_code == 401


def test_historical_helper_observations_remain_in_report(setup_monitor):
    client, database = setup_monitor
    with database.session(write=True) as db:
        db.add(MonitorObservation(id='old-helper-event', session_id='session', client_id=None,
                                  event_id='historic', product_id='known',
                                  kind='running_process', state='detected', observed_at=time.time()))
    report = client.get('/api/market/company/assessments/session/monitor',
                        headers={'X-Company-Key': 'first-key'}).json()
    assert report['automatic_penalty'] is False
    assert report['observations'][0]['kind'] == 'running_process'
