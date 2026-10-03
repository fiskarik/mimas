"""Tests for private S3 video uploads without network or paid storage calls."""
import hashlib
import time
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import media
from backend.ai_web import AISession
from backend.companies import Company, company_from_key, credential_hash
from backend.marketplace import CandidateAssessment, CandidateProfile, Opportunity


SESSION_ID = 'session-owned'
CANDIDATE_TOKEN = 'candidate-secret'
OWNER_KEY = 'owner-secret'
OTHER_KEY = 'other-secret'
PARTS = [{'part_number': 1, 'etag': '"etag-1"'}]


class MemoryDatabase:
    """Only the session contract used by the video routes; production requires PG."""

    def __init__(self):
        self.engine = create_engine(
            'sqlite+pysqlite:///:memory:',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
        )
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self, *, write=False):
        with self.sessions() as db:
            with db.begin():
                yield db


class FakeS3:
    def __init__(self):
        self.create_calls = []
        self.complete_calls = []
        self.presigned_calls = []
        self.head_calls = []
        self.object_exists = False
        self.fail_before_once = False
        self.fail_after_once = False

    def create_multipart_upload(self, **kwargs):
        self.create_calls.append(kwargs)
        return {'UploadId': 'upload-' + str(len(self.create_calls))}

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self.presigned_calls.append((operation, Params, ExpiresIn))
        return f'https://storage.invalid/{operation}/{Params["Key"]}'

    def complete_multipart_upload(self, **kwargs):
        self.complete_calls.append(kwargs)
        if self.fail_before_once:
            self.fail_before_once = False
            raise RuntimeError('temporary S3 failure before completion')
        self.object_exists = True
        if self.fail_after_once:
            self.fail_after_once = False
            raise RuntimeError('response lost after completion')

    def head_object(self, **kwargs):
        self.head_calls.append(kwargs)
        if not self.object_exists:
            raise RuntimeError('object does not exist')
        return {'ContentLength': 123}


@pytest.fixture
def video_api(monkeypatch):
    database = MemoryDatabase()
    tables = [
        Company.__table__,
        CandidateProfile.__table__,
        Opportunity.__table__,
        AISession.__table__,
        CandidateAssessment.__table__,
        media.VideoRecording.__table__,
    ]
    Company.metadata.create_all(database.engine, tables=tables)
    now = time.time()
    with database.session(write=True) as db:
        db.add_all([
            Company(id='owner', name='Owner', contact_email='owner@example.test',
                    status='approved', key_hash=credential_hash(OWNER_KEY),
                    claim_hash=None, claim_expires=None, created=now, approved=now),
            Company(id='other', name='Other', contact_email='other@example.test',
                    status='approved', key_hash=credential_hash(OTHER_KEY),
                    claim_hash=None, claim_expires=None, created=now, approved=now),
            CandidateProfile(id='candidate', token_hash=hashlib.sha256(CANDIDATE_TOKEN.encode()).hexdigest(),
                             name='Candidate', level='middle', stack='["Python"]',
                             years_experience=3, github_url=None, desired_salary_rub=None,
                             discoverable=0, created=now),
            Opportunity(id='vacancy-owned', company_id='owner', company_name='Owner',
                        title='Python developer', description='Python and APIs',
                        level='middle', stack='["Python"]', salary_min_rub=None,
                        salary_max_rub=None, employment_type='full_time',
                        status='open', created=now),
            AISession(id=SESSION_ID, token_hash=hashlib.sha256(CANDIDATE_TOKEN.encode()).hexdigest(),
                      model='gpt://test/deepseek-v4.1-flash', started=now,
                      state='{}', trace='[]', pending=None, candidate_id='candidate',
                      opportunity_id='vacancy-owned', archived=0),
            CandidateAssessment(candidate_id='candidate', opportunity_id='vacancy-owned',
                                session_id=SESSION_ID, consent_at=now, created=now),
        ])
    fake_s3 = FakeS3()
    monkeypatch.setattr(media, '_client', lambda: fake_s3)
    monkeypatch.setenv('MIMAS_S3_BUCKET', 'test-bucket')
    app = FastAPI()
    media.register_video_routes(
        app, database, lambda key: company_from_key(database, key)
    )
    with TestClient(app) as client:
        yield client, database, fake_s3
    database.engine.dispose()


def path(suffix):
    return f'/api/ai/sessions/{SESSION_ID}/recording/{suffix}'


def candidate_headers(token=CANDIDATE_TOKEN):
    return {'X-Interview-Token': token}


def company_headers(key):
    return {'X-Company-Key': key}


def test_init_and_presigned_part_url_require_candidate_and_are_idempotent(video_api):
    client, _, s3 = video_api

    assert client.post(path('init')).status_code == 401
    assert client.post(path('init'), headers=candidate_headers('wrong')).status_code == 404

    first = client.post(path('init'), headers=candidate_headers())
    assert first.status_code == 200
    assert first.json() == {
        'upload_id': 'upload-1',
        'part_size': media.PART_SIZE,
        'status': 'uploading',
    }
    second = client.post(path('init'), headers=candidate_headers())
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(s3.create_calls) == 1
    assert s3.create_calls[0]['ContentType'] == 'video/webm'

    assert client.post(path('parts/1/url'), headers=candidate_headers('wrong')).status_code == 404
    assert client.post(path('parts/0/url'), headers=candidate_headers()).status_code == 422
    part = client.post(path('parts/1/url'), headers=candidate_headers())
    assert part.status_code == 200
    assert part.json()['expires_in'] == 900
    assert part.json()['url'].startswith('https://storage.invalid/upload_part/')
    operation, params, ttl = s3.presigned_calls[-1]
    assert operation == 'upload_part'
    assert params['Bucket'] == 'test-bucket'
    assert params['UploadId'] == 'upload-1'
    assert params['PartNumber'] == 1
    assert ttl == 900


def test_completion_retry_tenant_isolation_and_duplicate_completion(video_api):
    client, _, s3 = video_api
    assert client.post(path('complete'), headers=candidate_headers(),
                       json={'parts': PARTS}).status_code == 409
    assert client.post(path('init'), headers=candidate_headers()).status_code == 200

    s3.fail_before_once = True
    failed = client.post(path('complete'), headers=candidate_headers(),
                         json={'parts': PARTS, 'interrupted': True})
    assert failed.status_code == 503
    assert client.get(path('status'), headers=candidate_headers()).json()['status'] == 'uploading'
    assert client.get(path('url'), headers=candidate_headers()).status_code == 404

    before = time.time()
    completed = client.post(path('complete'), headers=candidate_headers(),
                            json={'parts': PARTS, 'interrupted': True})
    assert completed.status_code == 200
    assert completed.json()['status'] == 'completed'
    assert completed.json()['recording_incomplete'] is True
    assert before + 29 * 86400 < completed.json()['expires_at'] < before + 31 * 86400
    repeated = client.post(path('complete'), headers=candidate_headers(),
                           json={'parts': PARTS, 'interrupted': True})
    assert repeated.status_code == 200
    assert repeated.json()['expires_at'] == completed.json()['expires_at']
    assert len(s3.complete_calls) == 2
    assert client.get(path('parts/1/url'), headers=candidate_headers()).status_code == 405
    assert client.post(path('parts/1/url'), headers=candidate_headers()).status_code == 409

    owner_status = client.get(path('status'), headers=company_headers(OWNER_KEY))
    assert owner_status.status_code == 200
    assert owner_status.json()['status'] == 'completed'
    assert owner_status.json()['incomplete'] is True
    candidate_url = client.get(path('url'), headers=candidate_headers())
    owner_url = client.get(path('url'), headers=company_headers(OWNER_KEY))
    assert candidate_url.status_code == owner_url.status_code == 200
    assert candidate_url.json()['expires_in'] == owner_url.json()['expires_in'] == 300
    authorized_urls = len([call for call in s3.presigned_calls if call[0] == 'get_object'])

    assert client.get(path('status'), headers=company_headers(OTHER_KEY)).status_code == 404
    assert client.get(path('url'), headers=company_headers(OTHER_KEY)).status_code == 404
    assert client.get(path('status'), headers=company_headers('wrong')).status_code == 401
    assert client.get(path('url'), headers=candidate_headers('wrong')).status_code == 404
    assert client.get(path('url')).status_code == 401
    assert len([call for call in s3.presigned_calls if call[0] == 'get_object']) == authorized_urls


def test_lost_complete_response_is_reconciled_and_expired_video_is_private(video_api):
    client, database, s3 = video_api
    assert client.post(path('init'), headers=candidate_headers()).status_code == 200
    s3.fail_after_once = True
    response = client.post(path('complete'), headers=candidate_headers(),
                           json={'parts': PARTS})
    assert response.status_code == 200
    assert response.json()['status'] == 'completed'
    assert len(s3.head_calls) == 1
    assert client.post(path('complete'), headers=candidate_headers(),
                       json={'parts': PARTS}).status_code == 200
    assert len(s3.complete_calls) == 1

    with database.session(write=True) as db:
        db.get(media.VideoRecording, SESSION_ID).expires_at = time.time() - 1
    before = len(s3.presigned_calls)
    assert client.get(path('url'), headers=candidate_headers()).status_code == 404
    assert client.get(path('url'), headers=company_headers(OWNER_KEY)).status_code == 404
    assert len(s3.presigned_calls) == before
    assert client.get(path('status'), headers=candidate_headers()).json()['status'] == 'completed'



def test_expired_multipart_rotates_and_old_etags_are_invalid(video_api):
    client, database, s3 = video_api
    first = client.post(path('init'), headers=candidate_headers()).json()
    assert first['upload_id'] == 'upload-1'
    with database.session(write=True) as db:
        db.get(media.VideoRecording, SESSION_ID).created = time.time() - 21 * 3600
    renewed = client.post(path('init'), headers=candidate_headers()).json()
    assert renewed['status'] == 'uploading'
    assert renewed['restarted'] is True
    assert renewed['upload_id'] == 'upload-2'
    assert len(s3.create_calls) == 2
    client.post(path('parts/1/url'), headers=candidate_headers())
    assert s3.presigned_calls[-1][1]['UploadId'] == 'upload-2'
