"""Private multipart video uploads for vacancy assessments.

The browser uploads WebM parts directly to S3; Render never keeps the video on disk.
"""
import hashlib
import os
import secrets
import time
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Float, ForeignKey, Integer, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base, Database


PART_SIZE = 5 * 1024 * 1024
MAX_PARTS = 200


class VideoRecording(Base):
    __tablename__ = 'video_recordings'
    session_id: Mapped[str] = mapped_column(Text, ForeignKey('ai_sessions.id'), primary_key=True)
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    upload_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float)
    completed: Mapped[float | None] = mapped_column(Float)
    expires_at: Mapped[float | None] = mapped_column(Float)
    part_count: Mapped[int] = mapped_column(Integer, default=0)
    interrupted: Mapped[int] = mapped_column(Integer, default=0, server_default='0')


class VideoParts(BaseModel):
    interrupted: bool = False
    parts: list[dict] = Field(min_length=1, max_length=MAX_PARTS)


def _client():
    try:
        import boto3
    except ImportError:
        raise HTTPException(503, 'Хранилище видео не установлено') from None
    required = ('MIMAS_S3_BUCKET', 'MIMAS_S3_ACCESS_KEY', 'MIMAS_S3_SECRET_KEY')
    if not all(os.getenv(name) for name in required):
        raise HTTPException(503, 'Хранилище видео не настроено')
    return boto3.client(
        's3', endpoint_url=os.getenv('MIMAS_S3_ENDPOINT', 'https://storage.yandexcloud.net'),
        region_name=os.getenv('MIMAS_S3_REGION', 'ru-central1'),
        aws_access_key_id=os.environ['MIMAS_S3_ACCESS_KEY'],
        aws_secret_access_key=os.environ['MIMAS_S3_SECRET_KEY'],
    )


def _bucket():
    return os.environ['MIMAS_S3_BUCKET']


def _candidate_session(database: Database, iid: str, token: str | None):
    from backend.ai_web import AISession
    from backend.marketplace import CandidateAssessment
    from backend.general_interview import GeneralAssessment
    if not token:
        raise HTTPException(401, 'Требуется ключ интервью')
    digest = hashlib.sha256(token.encode()).hexdigest()
    with database.session() as db:
        row = db.get(AISession, iid)
        assessment = db.scalar(select(CandidateAssessment).where(CandidateAssessment.session_id == iid))
        general = (db.scalar(select(GeneralAssessment).where(GeneralAssessment.session_id == iid))
                   if row and not assessment else None)
    if not row or not (assessment or general) or not secrets.compare_digest(row.token_hash, digest):
        raise HTTPException(404, 'Интервью не найдено')
    return row


def _company_session(database: Database, iid: str, key: str | None, authorize_company):
    from backend.marketplace import CandidateAssessment, Opportunity
    company = authorize_company(key)
    with database.session() as db:
        match = db.scalar(
            select(CandidateAssessment.session_id)
            .join(Opportunity, CandidateAssessment.opportunity_id == Opportunity.id)
            .where(CandidateAssessment.session_id == iid, Opportunity.company_id == company.id)
        )
    if not match:
        raise HTTPException(404, 'Интервью не найдено')
    return match


def register_video_routes(app: FastAPI, database: Database, authorize_company):
    @app.post('/api/ai/sessions/{iid}/recording/init')
    def init_recording(iid: str, x_interview_token: str | None = Header(None)):
        _candidate_session(database, iid, x_interview_token)
        with database.session() as db:
            existing = db.get(VideoRecording, iid)
        if existing:
            if existing.status != 'uploading' or time.time() - existing.created < 20 * 3600:
                return {'upload_id': existing.upload_id, 'part_size': PART_SIZE, 'status': existing.status}
            # Bucket lifecycle aborts incomplete uploads after a day. Rotate
            # the upload before that deadline; the browser re-uploads its
            # locally saved parts when the upload_id changes.
            with database.session(write=True) as db:
                current = db.scalar(select(VideoRecording).where(
                    VideoRecording.session_id == iid).with_for_update())
                if current.status != 'uploading' or time.time() - current.created < 20 * 3600:
                    return {'upload_id': current.upload_id, 'part_size': PART_SIZE,
                            'status': current.status}
                key = f'recordings/{iid}/{uuid4().hex}.webm'
                try:
                    started = _client().create_multipart_upload(
                        Bucket=_bucket(), Key=key, ContentType='video/webm')
                except Exception:
                    raise HTTPException(503, 'Не удалось восстановить загрузку видео') from None
                current.object_key = key
                current.upload_id = started['UploadId']
                current.created = time.time()
                current.part_count = 0
                return {'upload_id': current.upload_id, 'part_size': PART_SIZE,
                        'status': 'uploading', 'restarted': True}
        client = _client()
        key = f'recordings/{iid}/{uuid4().hex}.webm'
        try:
            started = client.create_multipart_upload(Bucket=_bucket(), Key=key, ContentType='video/webm')
        except Exception:
            raise HTTPException(503, 'Не удалось начать загрузку видео') from None
        row = VideoRecording(session_id=iid, object_key=key, upload_id=started['UploadId'],
                             status='uploading', created=time.time())
        with database.session(write=True) as db:
            if db.get(VideoRecording, iid):
                # Another request won the race; bucket lifecycle cleans this orphan upload.
                existing = db.get(VideoRecording, iid)
                return {'upload_id': existing.upload_id, 'part_size': PART_SIZE, 'status': existing.status}
            db.add(row)
        return {'upload_id': row.upload_id, 'part_size': PART_SIZE, 'status': row.status}

    @app.post('/api/ai/sessions/{iid}/recording/parts/{part_number}/url')
    def part_url(iid: str, part_number: int, x_interview_token: str | None = Header(None)):
        _candidate_session(database, iid, x_interview_token)
        if not 1 <= part_number <= MAX_PARTS:
            raise HTTPException(422, 'Недопустимый номер части видео')
        with database.session() as db:
            recording = db.get(VideoRecording, iid)
        if not recording or recording.status != 'uploading':
            raise HTTPException(409, 'Загрузка видео не начата или завершена')
        try:
            url = _client().generate_presigned_url(
                'upload_part',
                Params={'Bucket': _bucket(), 'Key': recording.object_key,
                        'UploadId': recording.upload_id, 'PartNumber': part_number},
                ExpiresIn=900,
            )
        except Exception:
            raise HTTPException(503, 'Не удалось подготовить загрузку видео') from None
        return {'url': url, 'expires_in': 900}

    @app.post('/api/ai/sessions/{iid}/recording/complete')
    def complete_recording(iid: str, body: VideoParts, x_interview_token: str | None = Header(None)):
        _candidate_session(database, iid, x_interview_token)
        with database.session() as db:
            recording = db.get(VideoRecording, iid)
        if not recording:
            raise HTTPException(409, 'Загрузка видео не начата')
        if recording.status == 'completed':
            return {'status': 'completed', 'expires_at': recording.expires_at}
        if recording.status != 'uploading':
            raise HTTPException(409, 'Загрузка видео недоступна')
        parts = body.parts
        numbers = [part.get('part_number') for part in parts]
        if numbers != list(range(1, len(parts) + 1)) or any(
            not isinstance(part.get('etag'), str) or len(part['etag']) > 200 for part in parts
        ):
            raise HTTPException(422, 'Неверный список частей видео')
        try:
            _client().complete_multipart_upload(
                Bucket=_bucket(), Key=recording.object_key, UploadId=recording.upload_id,
                MultipartUpload={'Parts': [
                    {'PartNumber': part['part_number'], 'ETag': part['etag']} for part in parts
                ]},
            )
        except Exception:
            # A lost response may mean completion succeeded. Check the object
            # before telling the browser to retry.
            pass
        try:
            metadata = _client().head_object(Bucket=_bucket(), Key=recording.object_key)
        except Exception:
            raise HTTPException(503, 'Не удалось завершить загрузку видео; повторите') from None
        if int(metadata.get('ContentLength', 0)) <= 0:
            raise HTTPException(503, 'Хранилище не подтвердило непустую запись')
        now = time.time()
        with database.session(write=True) as db:
            row = db.get(VideoRecording, iid)
            row.status = 'completed'
            row.upload_id = None
            row.completed = now
            row.expires_at = now + 30 * 86400
            row.part_count = len(parts)
            row.interrupted = int(body.interrupted)
        return {'status': 'completed', 'expires_at': now + 30 * 86400, 'recording_incomplete': body.interrupted}

    @app.get('/api/ai/sessions/{iid}/recording/url')
    def playback_url(iid: str, x_interview_token: str | None = Header(None),
                     x_company_key: str | None = Header(None)):
        if x_interview_token:
            _candidate_session(database, iid, x_interview_token)
        else:
            _company_session(database, iid, x_company_key, authorize_company)
        with database.session() as db:
            recording = db.get(VideoRecording, iid)
        if not recording or recording.status != 'completed' or (
            recording.expires_at is not None and recording.expires_at <= time.time()
        ):
            raise HTTPException(404, 'Видеозапись недоступна')
        try:
            url = _client().generate_presigned_url(
                'get_object', Params={'Bucket': _bucket(), 'Key': recording.object_key},
                ExpiresIn=300,
            )
        except Exception:
            raise HTTPException(503, 'Не удалось открыть видеозапись') from None
        return {'url': url, 'expires_in': 300}


    @app.get('/api/ai/sessions/{iid}/recording/status')
    def recording_status(iid: str, x_interview_token: str | None = Header(None),
                         x_company_key: str | None = Header(None)):
        if x_interview_token:
            _candidate_session(database, iid, x_interview_token)
        else:
            _company_session(database, iid, x_company_key, authorize_company)
        with database.session() as db:
            recording = db.get(VideoRecording, iid)
        if not recording:
            return {'status': 'none', 'incomplete': False, 'expires_at': None}
        return {'status': recording.status, 'incomplete': bool(recording.interrupted),
                'expires_at': recording.expires_at}
