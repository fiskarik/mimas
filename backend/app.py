"""MIMAS API: tenant-scoped marketplace and read-only legacy reports."""
import json
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select

from backend.database import Database, Interview, AnswerRecord, IntegrityEvent, RecordingChunk, as_dict
from backend.companies import company_from_key, ensure_legacy_company, register_company_routes
from backend.marketplace import register_marketplace_routes
from backend.ai_web import register_ai_routes
from backend.media import register_video_routes
from backend.monitor import register_monitor_routes
from ai_core.llm.factory import create_llm_provider

DATA = Path(os.getenv('DATA_DIR', Path(__file__).resolve().parents[1] / 'data'))
DATABASE_URL = os.getenv('DATABASE_URL')
COMPANY_KEY = os.getenv('COMPANY_KEY', '')
if os.getenv('MIMAS_ENV', '').lower() == 'production' and not COMPANY_KEY:
    raise RuntimeError('Production requires the legacy COMPANY_KEY to preserve its reports')
database = Database(DATABASE_URL)
app = FastAPI(title='MIMAS', version='0.3.0')

@app.on_event('startup')
def setup_legacy_company():
    # The startup script applies Alembic migrations before the API loads.
    ensure_legacy_company(database, COMPANY_KEY)

@app.middleware('http')
async def no_store_api(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response

def authorize_company(key: str | None):
    return company_from_key(database, key)

register_company_routes(app, database)
register_marketplace_routes(app, database, authorize_company)
register_ai_routes(app, database, authorize_company)
register_video_routes(app, database, authorize_company)
register_monitor_routes(app, database)

def configuration():
    try:
        provider = create_llm_provider(provider='yandex')
        ai_ready = provider.name == 'yandex'
    except (ValueError, ImportError):
        ai_ready = False
    return {'mode': 'live', 'ai_ready': ai_ready,
            'stt_ready': bool(os.getenv('YANDEX_API_KEY') and os.getenv('YANDEX_FOLDER_ID')),
            'voice_ready': bool(os.getenv('YANDEX_API_KEY') and os.getenv('YANDEX_FOLDER_ID')),
            'ocr_ready': bool(os.getenv('YANDEX_API_KEY') and os.getenv('YANDEX_FOLDER_ID')),
            'video_ready': all(os.getenv(x) for x in ('MIMAS_S3_BUCKET', 'MIMAS_S3_ACCESS_KEY', 'MIMAS_S3_SECRET_KEY')),
            'runner_ready': False}

@app.get('/api/health')
def health():
    # Readiness is configuration-only. It does not spend money on a provider call.
    readiness = configuration()
    if os.getenv('MIMAS_ENV', '').lower() == 'production' and not all((
        readiness['ai_ready'], readiness['stt_ready'], readiness['ocr_ready'],
        readiness['video_ready'], bool(os.getenv('MIMAS_ADMIN_KEY'))
    )):
        return JSONResponse(status_code=503, content={'status': 'configuration_required', **readiness})
    return {'status': 'ok', **readiness}

def _legacy_interview(iid: str):
    with database.session() as db:
        row = db.get(Interview, iid)
    if not row:
        raise HTTPException(404, 'Интервью не найдено')
    return as_dict(row)

def _legacy_candidate(iid: str, token: str | None):
    row = _legacy_interview(iid)
    if not token or not secrets.compare_digest(token, row['token']):
        raise HTTPException(401, 'Неверная ссылка приглашения')
    return row

def _public_legacy(row):
    return {key: value for key, value in row.items() if key != 'token'}

def _legacy_details(row):
    with database.session() as db:
        answers = [as_dict(answer) for answer in db.scalars(select(AnswerRecord).where(
            AnswerRecord.interview_id == row['id']).order_by(AnswerRecord.created))]
        events = [as_dict(event) for event in db.scalars(select(IntegrityEvent).where(
            IntegrityEvent.interview_id == row['id']).order_by(IntegrityEvent.elapsed))]
        chunks = database.count(db, RecordingChunk, row['id'])
    for answer in answers:
        answer['evaluation'] = json.loads(answer['evaluation']) if answer['evaluation'] else None
    return {'interview': _public_legacy(row), 'answers': answers, 'events': events,
            'uploaded_chunks': chunks, 'archived': True, 'read_only': True,
            'capabilities': configuration()}

@app.post('/api/interviews', status_code=410)
def legacy_create_closed():
    raise HTTPException(410, 'Новые интервью создаются по вакансиям в кабинете работодателя')

@app.get('/api/interviews')
def legacy_interviews(x_company_key: str | None = Header(None)):
    company = authorize_company(x_company_key)
    with database.session() as db:
        rows = list(db.scalars(select(Interview).where(Interview.company_id == company.id)
                               .order_by(Interview.created.desc())))
    return [_public_legacy(as_dict(row)) for row in rows]

@app.get('/api/interviews/{iid}')
def legacy_candidate_report(iid: str, x_interview_token: str | None = Header(None)):
    return _legacy_details(_legacy_candidate(iid, x_interview_token))

@app.get('/api/company/interviews/{iid}')
def legacy_company_report(iid: str, x_company_key: str | None = Header(None)):
    company = authorize_company(x_company_key)
    row = _legacy_interview(iid)
    if row['company_id'] != company.id:
        raise HTTPException(404, 'Интервью не найдено')
    return _legacy_details(row)

@app.get('/api/company/interviews/{iid}/recording')
def legacy_recording(iid: str, x_company_key: str | None = Header(None)):
    company = authorize_company(x_company_key)
    row = _legacy_interview(iid)
    if row['company_id'] != company.id or not row['recording_complete']:
        raise HTTPException(404, 'Видеозапись недоступна')
    target = DATA / 'recordings' / iid / 'interview.webm'
    if not target.is_file():
        raise HTTPException(404, 'Видеозапись недоступна')
    return FileResponse(target, media_type='video/webm', filename=f'interview-{iid}.webm')

@app.post('/api/interviews/{iid}/{action}', status_code=410)
def legacy_action_closed(iid: str, action: str):
    raise HTTPException(410, 'Старое интервью доступно только для чтения. Начните новое по вакансии.')
