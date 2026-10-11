"""Persistent text interview API for the local, single-worker demo."""
import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from contextlib import suppress
from uuid import uuid4

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import Float, Integer, Text, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base, Database
from backend.marketplace import CandidateAssessment, CandidateInterest, InterviewSettings, candidate_from_token
from backend.general_interview import GeneralAssessment, Profession, profession_id_for_name
from ai_core.interview.engine import InterviewEngine
from ai_core.interview.schemas import CandidateAnswer, InterviewInput, Limits, MAX_INTERVIEW_SECONDS
from ai_core.models import Level
from ai_core.interview.state import InterviewState, Phase
from backend.interview_completion import CompletionError, complete_without_ai
from ai_core.llm.factory import create_llm_provider, llm_readiness
from ai_core.llm.base import ProviderError
from backend.yandex_budget import BudgetExceeded, YandexBudget
from fastapi.responses import JSONResponse
from backend.ai_presenter import session_view as view
from ai_core.interview.events import RuntimeEvent

LOGGER = logging.getLogger(__name__)


class AISession(Base):
    __tablename__ = 'ai_sessions'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    started: Mapped[float] = mapped_column(Float)
    state: Mapped[str] = mapped_column(Text)
    trace: Mapped[str] = mapped_column(Text, default='[]')
    pending: Mapped[str | None] = mapped_column(Text)
    candidate_id: Mapped[str | None] = mapped_column(Text)
    opportunity_id: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[int] = mapped_column(Integer, default=0, server_default='0')


def interview_deadline(row: AISession, state: InterviewState) -> float | None:
    """Absolute deadline; old sessions with a 30-minute setting are capped too."""
    if state.phase == Phase.CREATED or state.started_at is None:
        return None
    return row.started + min(state.limits.time_budget_seconds, MAX_INTERVIEW_SECONDS)


class SessionCreate(BaseModel):
    opportunity_id: str
    consent: bool


class GeneralSessionCreate(BaseModel):
    profession_id: str
    consent: bool
    share_with_companies: bool

def register_ai_routes(app: FastAPI, database: Database, authorize_company):
    @app.exception_handler(ProviderError)
    async def llm_error(request, exc):
        return JSONResponse(status_code=503, content={'detail':'AI временно недоступен. Состояние сохранено; повторите обработку.', 'code':exc.code})

    @app.exception_handler(BudgetExceeded)
    async def budget_error(request, exc):
        return JSONResponse(status_code=429, content={'detail': 'Месячный лимит AI исчерпан. Ответы сохранены; продолжите позже.'})

    @app.get('/api/ai/health')
    async def ai_health():
        return llm_readiness()

    # Fixed lock pool avoids accumulating locks per session. Deployment is one worker.
    locks = [asyncio.Lock() for _ in range(32)]
    assessment_gate = asyncio.Lock()
    daily_limit = int(os.getenv('MIMAS_MAX_ASSESSMENTS_PER_DAY', '0'))
    if daily_limit < 0:
        raise ValueError('MIMAS_MAX_ASSESSMENTS_PER_DAY must be nonnegative')

    def lock_for(iid: str):
        return locks[int(hashlib.sha256(iid.encode()).hexdigest()[:8], 16) % len(locks)]

    def load(iid: str, token: str | None, *, allow_archived: bool = False) -> AISession:
        with database.session() as db:
            row = db.get(AISession, iid)
        if not row or not token or not secrets.compare_digest(row.token_hash, hashlib.sha256(token.encode()).hexdigest()):
            raise HTTPException(401, 'Сессия недоступна: проверьте ссылку или начните новую.')
        if row.archived and not allow_archived:
            raise HTTPException(410, 'Это старое интервью переведено в архив. Начните новое по вакансии.')
        return row

    def restore(row: AISession) -> InterviewEngine:
        state = InterviewState.model_validate_json(row.state)
        try:
            # Archived sessions are read-only; all active sessions use Yandex.
            provider = create_llm_provider(provider='yandex', model=row.model, budget=YandexBudget(database))
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from None
        provider.model = row.model
        engine = InterviewEngine(provider, config=state.config, limits=state.limits,
                                 plan=state.plan_snapshot, clock=time.time,
                                 approved_primary_questions=bool(row.opportunity_id or (
                                     state.plan_snapshot and state.plan_snapshot.version.startswith('profession-'))))
        engine.state = state
        engine.state.interview_id = row.id
        engine.limits = engine.state.limits
        engine.started = row.started
        engine.trace = json.loads(row.trace)
        engine.checkpoint_sink = lambda current: save(row, current)
        return engine

    def save(row: AISession, engine: InterviewEngine, pending: str | None = None):
        with database.session(write=True) as db:
            stored = db.get(AISession, row.id)
            stored.state = engine.state.model_dump_json()
            stored.trace = json.dumps(engine.trace, ensure_ascii=False)
            stored.pending = pending or (engine.state.pending_answer.model_dump_json() if engine.state.pending_answer else None)
            if engine.started is not None:
                stored.started = engine.started

    def finish_without_ai(row: AISession, reason: str) -> AISession:
        """The caller holds the session lock; completion never calls the provider."""
        try:
            state, trace = complete_without_ai(
                InterviewState.model_validate_json(row.state), row.pending, row.trace, reason)
        except CompletionError as exc:
            raise HTTPException(409, str(exc)) from None
        with database.session(write=True) as db:
            stored = db.get(AISession, row.id)
            stored.state = state.model_dump_json()
            stored.trace = trace
            stored.pending = None
        return _reload(row.id)

    def _reload(iid: str) -> AISession:
        with database.session() as db:
            return db.get(AISession, iid)

    def expire_locked(row: AISession) -> AISession:
        state = InterviewState.model_validate_json(row.state)
        deadline = interview_deadline(row, state)
        if deadline is not None and state.phase != Phase.COMPLETED and time.time() >= deadline:
            return finish_without_ai(row, 'time_budget')
        return row

    async def expire_if_due(iid: str, token: str) -> dict | None:
        """Voice runtime can invoke this at the deadline while its socket is open."""
        async with lock_for(iid):
            row = load(iid, token)
            state = InterviewState.model_validate_json(row.state)
            deadline = interview_deadline(row, state)
            if deadline is None or time.time() < deadline:
                return None
            return public_view(expire_locked(row))

    def public_view(row: AISession):
        result = view(row)
        state = InterviewState.model_validate_json(row.state)
        is_general = bool(state.plan_snapshot and state.plan_snapshot.version.startswith('profession-'))
        if row.opportunity_id or is_general:
            from backend.media import VideoRecording
            with database.session() as db:
                recording = db.get(VideoRecording, row.id)
            if not recording or recording.status != 'completed':
                # Uploading video must not hide an already completed text report.
                result['recording_required'] = True
                result['recording_status'] = recording.status if recording else 'none'
            else:
                result['recording_required'] = False
                result['recording_status'] = 'completed'
                result['recording_incomplete'] = bool(recording.interrupted)
        return result

    @app.post('/api/ai/general-sessions')
    async def create_general_session(body: GeneralSessionCreate,
                                     x_candidate_token: str | None = Header(None)):
        from ai_core.interview.planner import CompetencyPlan
        if not body.consent:
            raise HTTPException(422, 'Подтвердите согласие на запись общего интервью.')
        profile = candidate_from_token(database, x_candidate_token)
        async with lock_for(profile.id + ':general:' + body.profession_id):
            with database.session() as db:
                previous = db.get(GeneralAssessment, (profile.id, body.profession_id))
                profession = db.get(Profession, body.profession_id)
            if previous:
                return {'id': previous.session_id, 'token': x_candidate_token}
            if not profession:
                raise HTTPException(404, 'Профессия не найдена')
            if json.loads(profile.stack)[0].casefold() != profession.name.casefold():
                raise HTTPException(409, 'Общее интервью должно соответствовать профессии в профиле.')
            plan = CompetencyPlan.model_validate_json(profession.plan_json)
            settings = InterviewSettings.model_validate_json(profession.settings_json)
            limits = Limits(max_questions=settings.max_questions,
                            max_follow_ups_per_question=settings.max_follow_ups,
                            time_budget_seconds=settings.duration_minutes * 60)
            try:
                provider = create_llm_provider(provider='yandex', budget=YandexBudget(database))
            except ValueError as exc:
                raise HTTPException(503, str(exc)) from None
            config = InterviewInput(role=plan.role, target_level=Level(profile.level))
            context = {'candidate_level': profile.level, 'candidate_stack': json.loads(profile.stack),
                       'years_experience': profile.years_experience,
                       'profession': profession.name}
            engine = InterviewEngine(provider, config=config, limits=limits, plan=plan,
                                     candidate_context=context, clock=time.time,
                                     approved_primary_questions=True)
            engine.state.llm_provider = 'yandex'
            now = time.time()
            row = AISession(id=uuid4().hex, token_hash=hashlib.sha256(x_candidate_token.encode()).hexdigest(),
                            model=provider.model, started=now, state=engine.state.model_dump_json(),
                            trace='[]', candidate_id=profile.id, opportunity_id=None, archived=0)
            engine.state.interview_id = row.id
            row.state = engine.state.model_dump_json()
            async with assessment_gate:
                try:
                    with database.session(write=True) as db:
                        if daily_limit:
                            if db.bind.dialect.name == 'postgresql':
                                db.execute(text('SELECT pg_advisory_xact_lock(62714622)'))
                            active_today = db.scalar(select(func.count()).select_from(GeneralAssessment).where(
                                GeneralAssessment.created >= now - 86400))
                            active_today += db.scalar(select(func.count()).select_from(CandidateAssessment).where(
                                CandidateAssessment.created >= now - 86400))
                            if active_today >= daily_limit:
                                raise HTTPException(429, 'Дневной лимит интервью исчерпан. Повторите позже.')
                        db.add(row)
                        db.add(GeneralAssessment(candidate_id=profile.id, profession_id=profession.id,
                                                 session_id=row.id,
                                                 share_with_companies=int(body.share_with_companies),
                                                 consent_at=now, created=now))
                except IntegrityError:
                    with database.session() as db:
                        existing = db.get(GeneralAssessment, (profile.id, profession.id))
                    if existing:
                        return {'id': existing.session_id, 'token': x_candidate_token}
                    raise
            return {'id': row.id, 'token': x_candidate_token}

    @app.post('/api/ai/sessions')
    async def create_ai_session(body: SessionCreate,
                                x_candidate_token: str | None = Header(None)):
        from backend.marketplace import Opportunity, VacancyTemplate
        from ai_core.interview.planner import CompetencyPlan
        from backend.yandex_budget import YandexBudget

        profile = candidate_from_token(database, x_candidate_token)
        if body.consent is not True:
            raise HTTPException(422, 'Подтвердите согласие на запись и передачу результата компании.')

        async with lock_for(profile.id + ':' + body.opportunity_id):
            with database.session() as db:
                previous = db.get(CandidateAssessment, (profile.id, body.opportunity_id))
                opportunity = db.get(Opportunity, body.opportunity_id)
                interested = db.get(CandidateInterest, (profile.id, body.opportunity_id))
                template = db.scalar(select(VacancyTemplate).where(
                    VacancyTemplate.opportunity_id == body.opportunity_id,
                    VacancyTemplate.status == 'approved').order_by(VacancyTemplate.version.desc()).limit(1))
            if previous:
                return {'id': previous.session_id, 'token': x_candidate_token}
            if not opportunity or opportunity.status != 'open' or not interested or not template:
                raise HTTPException(409, 'Выберите опубликованную вакансию с утверждённым тестом.')
            required_id = profession_id_for_name(json.loads(opportunity.stack)[0])
            if required_id:
                with database.session() as db:
                    profession = db.get(Profession, required_id)
                    general = db.get(GeneralAssessment, (profile.id, required_id))
                    general_session = db.get(AISession, general.session_id) if general else None
                if profession:
                    if json.loads(profile.stack)[0].casefold() != profession.name.casefold():
                        raise HTTPException(409, 'Для этой вакансии нужен профиль соответствующей профессии.')
                    if not general_session or InterviewState.model_validate_json(general_session.state).phase != Phase.COMPLETED:
                        raise HTTPException(409, 'Сначала завершите общее интервью по профессии.')
            plan = CompetencyPlan.model_validate_json(template.plan_json)
            settings = InterviewSettings.model_validate_json(template.settings_json)
            limits = Limits(max_questions=settings.max_questions,
                            max_follow_ups_per_question=settings.max_follow_ups,
                            time_budget_seconds=settings.duration_minutes * 60)
            try:
                provider = create_llm_provider(provider='yandex', budget=YandexBudget(database))
            except ValueError as exc:
                raise HTTPException(503, str(exc)) from None
            config = InterviewInput(role=plan.role, target_level=Level(profile.level))
            context = {'candidate_level': profile.level, 'candidate_stack': json.loads(profile.stack),
                       'years_experience': profile.years_experience,
                       'vacancy_title': opportunity.title, 'vacancy_stack': json.loads(opportunity.stack)}
            engine = InterviewEngine(provider, config=config, limits=limits, plan=plan,
                                     candidate_context=context, clock=time.time,
                                     approved_primary_questions=True)
            engine.state.llm_provider = 'yandex'
            now = time.time()
            row = AISession(id=uuid4().hex, token_hash=hashlib.sha256(x_candidate_token.encode()).hexdigest(),
                            model=provider.model, started=now, state=engine.state.model_dump_json(),
                            trace='[]', candidate_id=profile.id, opportunity_id=opportunity.id, archived=0)
            engine.state.interview_id = row.id
            row.state = engine.state.model_dump_json()
            async with assessment_gate:
                try:
                    with database.session(write=True) as db:
                        if daily_limit:
                            if db.bind.dialect.name == 'postgresql':
                                db.execute(text('SELECT pg_advisory_xact_lock(62714622)'))
                            active_today = db.scalar(select(func.count()).select_from(CandidateAssessment).where(
                                CandidateAssessment.created >= now - 86400))
                            if active_today >= daily_limit:
                                raise HTTPException(429, 'Дневной лимит интервью исчерпан. Повторите позже.')
                        db.add(row)
                        db.add(CandidateAssessment(candidate_id=profile.id, opportunity_id=opportunity.id,
                                                   session_id=row.id, consent_at=now, created=now))
                except IntegrityError:
                    # Another worker may have created this candidate/vacancy pair.
                    with database.session() as db:
                        existing = db.get(CandidateAssessment, (profile.id, opportunity.id))
                    if existing:
                        return {'id': existing.session_id, 'token': x_candidate_token}
                    raise
            return {'id': row.id, 'token': x_candidate_token}
    @app.get('/api/ai/sessions/{iid}')
    async def get_ai_session(iid: str, x_interview_token: str | None = Header(None)):
        async with lock_for(iid):
            row = load(iid, x_interview_token, allow_archived=True)
            return public_view(row if row.archived else expire_locked(row))

    @app.post('/api/ai/sessions/{iid}/start')
    async def start_ai_session(iid: str, request: Request, x_interview_token: str | None = Header(None)):
        async with lock_for(iid):
            row = expire_locked(load(iid, x_interview_token))
            if InterviewState.model_validate_json(row.state).phase == Phase.CREATED:
                from backend.media import VideoRecording
                with database.session() as db:
                    video = db.get(VideoRecording, iid)
                if not video or video.status not in ('uploading', 'completed'):
                    raise HTTPException(409, 'Включите камеру и начните запись перед интервью.')
                from backend.monitor import assert_start_ready
                assert_start_ready(database, iid, request.headers.get('user-agent', ''))
                engine = restore(row)
                await engine.handle(RuntimeEvent(type='INTERVIEW_STARTED'))
                with database.session(write=True) as db:
                    db.get(AISession, iid).started = engine.started
                save(row, engine)
            elif InterviewState.model_validate_json(row.state).phase not in (Phase.WAITING_FOR_ANSWER, Phase.COMPLETED):
                engine = restore(row)
                await engine.resume()
                save(row, engine)
            return public_view(load(iid, x_interview_token))

    async def submit_answer(iid: str, body: CandidateAnswer, token: str | None):
        async with lock_for(iid):
            row = expire_locked(load(iid, token))
            state = InterviewState.model_validate_json(row.state)
            if state.phase == Phase.COMPLETED:
                saved = next((t for t in state.turns if t.question.id == body.question_id), None)
                if saved and saved.answer == body:
                    return public_view(row)
                raise HTTPException(409, 'Интервью завершено; этот ответ не сохранён.')
            existing = next((t for t in state.turns if t.question.id == body.question_id), None)
            if existing:
                if existing.answer.text != body.text:
                    raise HTTPException(409, 'Ответ уже сохранён и не может быть изменён.')
                if state.phase not in (Phase.WAITING_FOR_ANSWER, Phase.COMPLETED):
                    engine = restore(row)
                    await engine.resume()
                    save(row, engine)
                return public_view(load(iid, token))
            if state.pending_answer:
                if state.pending_answer != body:
                    raise HTTPException(409, 'Повторите обработку сохранённого ответа.')
                engine = restore(row)
                await engine.resume()
                save(row, engine)
                return public_view(load(iid, token))
            if state.phase != Phase.WAITING_FOR_ANSWER or state.questions[-1].id != body.question_id:
                raise HTTPException(409, 'Сначала ответьте на текущий вопрос.')
            if row.pending and CandidateAnswer.model_validate_json(row.pending) != body:
                raise HTTPException(409, 'Предыдущий ответ сохранён. Повторите его обработку.')
            engine = restore(row)
            # Commit before network I/O; retries after disconnection/restart use this answer.
            save(row, engine, body.model_dump_json())
            await engine.handle(RuntimeEvent(type='ANSWER_SUBMITTED', question_id=body.question_id), body.text)
            save(row, engine)
            return public_view(load(iid, token))


    @app.post('/api/ai/sessions/{iid}/answers')
    async def answer_ai_session(iid: str, body: CandidateAnswer, x_interview_token: str | None = Header(None)):
        return await submit_answer(iid, body, x_interview_token)

    @app.post('/api/ai/sessions/{iid}/events')
    async def runtime_event(iid: str, body: RuntimeEvent, x_interview_token: str | None = Header(None)):
        if body.type not in ('PASTE_DETECTED', 'COPY_DETECTED', 'FOCUS_LOST', 'FOCUS_RETURNED'):
            raise HTTPException(422, 'Это событие не поддерживается данным endpoint.')
        async with lock_for(iid):
            row = expire_locked(load(iid, x_interview_token))
            if InterviewState.model_validate_json(row.state).phase == Phase.COMPLETED:
                raise HTTPException(409, 'Интервью уже завершено.')
            engine = restore(row)
            try:
                outcome = await engine.handle(body)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
            return {'accepted': True, 'event_id': body.id, **(outcome or {})}

    @app.post('/api/ai/sessions/{iid}/finish')
    async def finish_ai_session(iid: str, x_interview_token: str | None = Header(None)):
        async with lock_for(iid):
            row = expire_locked(load(iid, x_interview_token))
            if InterviewState.model_validate_json(row.state).phase != Phase.COMPLETED:
                row = finish_without_ai(row, 'candidate_stopped')
            return public_view(row)






    @app.post('/api/ai/sessions/{iid}/transcribe')
    async def transcribe_ai_answer(iid: str, audio: UploadFile = File(...),
                                   x_interview_token: str | None = Header(None)):
        from backend.yandex_services import configured_yandex_services, YandexServiceError, MAX_AUDIO_BYTES
        async with lock_for(iid):
            row = expire_locked(load(iid, x_interview_token))
            if InterviewState.model_validate_json(row.state).phase != Phase.WAITING_FOR_ANSWER:
                raise HTTPException(409, 'Интервью не ожидает ответа.')
        if audio.content_type not in ('audio/webm', 'video/webm', 'audio/webm;codecs=opus'):
            raise HTTPException(415, 'Загрузите запись WebM.')
        payload = await audio.read(MAX_AUDIO_BYTES + 1)
        if not payload or len(payload) > MAX_AUDIO_BYTES:
            raise HTTPException(413, 'Аудио должно быть не больше 12 МБ.')
        try:
            transcript = await configured_yandex_services(database).transcribe_webm(payload)
        except ValueError:
            raise HTTPException(503, 'SpeechKit не настроен. Введите ответ текстом.') from None
        except YandexServiceError as exc:
            raise HTTPException(503, str(exc)) from None
        return {'text': transcript}

    from backend.voice_runtime import register_voice_route
    register_voice_route(app, database, load, public_view, submit_answer, expire_if_due)

    sweep_task: asyncio.Task | None = None

    async def sweep_expired_interviews():
        # Browser timers are advisory: this also completes an interview if its
        # tab closes, so the candidate and employer can later see the report.
        while True:
            try:
                cutoff = time.time() - MAX_INTERVIEW_SECONDS
                with database.session() as db:
                    ids = list(db.scalars(
                        select(AISession.id).where(
                            AISession.archived == 0, AISession.started <= cutoff,
                            AISession.state.like('%"started_at":"%'),
                            AISession.state.not_like('%"phase":"COMPLETED"%'))
                        .order_by(AISession.started).limit(100)))
                for iid in ids:
                    async with lock_for(iid):
                        row = _reload(iid)
                        if row and not row.archived:
                            expire_locked(row)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception('Failed to complete expired interviews')
            await asyncio.sleep(10)

    async def start_expiration_sweep():
        nonlocal sweep_task
        sweep_task = asyncio.create_task(sweep_expired_interviews())

    async def stop_expiration_sweep():
        nonlocal sweep_task
        if sweep_task is not None:
            sweep_task.cancel()
            with suppress(asyncio.CancelledError):
                await sweep_task
            sweep_task = None

    app.router.add_event_handler('startup', start_expiration_sweep)
    app.router.add_event_handler('shutdown', stop_expiration_sweep)
