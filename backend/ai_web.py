"""Persistent text interview API for the local, single-worker demo."""
import asyncio
import hashlib
import json
import secrets
import time
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from sqlalchemy import Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base, Database
from ai_core.interview.engine import InterviewEngine
from ai_core.interview.schemas import CandidateAnswer
from ai_core.interview.state import InterviewState, Phase
from ai_core.llm.factory import create_llm_provider, llm_readiness
from ai_core.llm.base import ProviderError
from fastapi.responses import JSONResponse
from backend.ai_presenter import session_view as view
from ai_core.interview.events import RuntimeEvent


class AISession(Base):
    __tablename__ = 'ai_sessions'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    started: Mapped[float] = mapped_column(Float)
    state: Mapped[str] = mapped_column(Text)
    trace: Mapped[str] = mapped_column(Text, default='[]')
    pending: Mapped[str | None] = mapped_column(Text)


def register_ai_routes(app: FastAPI, database: Database, authorize_company):
    @app.exception_handler(ProviderError)
    async def llm_error(request, exc):
        return JSONResponse(status_code=503, content={'detail':'AI временно недоступен. Состояние сохранено; повторите обработку.', 'code':exc.code})

    @app.get('/api/ai/health')
    async def ai_health():
        return llm_readiness()

    # Fixed lock pool avoids accumulating locks per session. Deployment is one worker.
    locks = [asyncio.Lock() for _ in range(32)]

    def lock_for(iid: str):
        return locks[int(hashlib.sha256(iid.encode()).hexdigest()[:8], 16) % len(locks)]

    def load(iid: str, token: str | None) -> AISession:
        with database.session() as db:
            row = db.get(AISession, iid)
        if not row or not token or not secrets.compare_digest(row.token_hash, hashlib.sha256(token.encode()).hexdigest()):
            raise HTTPException(401, 'Сессия недоступна: проверьте ссылку или начните новую.')
        return row

    def restore(row: AISession) -> InterviewEngine:
        state = InterviewState.model_validate_json(row.state)
        try:
            # Legacy sessions predate provider selection and were always Groq.
            provider = create_llm_provider(provider=state.llm_provider or 'groq', model=row.model)
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from None
        provider.model = row.model
        engine = InterviewEngine(provider, config=state.config, limits=state.limits,
                                 plan=state.plan_snapshot, clock=time.time)
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

    @app.post('/api/ai/sessions')
    async def create_ai_session(x_company_key: str | None = Header(None)):
        authorize_company(x_company_key)
        try:
            provider = create_llm_provider()
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from None
        engine = InterviewEngine(provider, clock=time.time)
        engine.state.llm_provider = getattr(provider, 'name', 'groq')
        token = secrets.token_urlsafe(32)
        row = AISession(id=uuid4().hex, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                        model=provider.model, started=time.time(), state=engine.state.model_dump_json(), trace='[]')
        engine.state.interview_id = row.id
        row.state = engine.state.model_dump_json()
        with database.session(write=True) as db:
            db.add(row)
        return {'id': row.id, 'token': token}

    @app.get('/api/ai/sessions/{iid}')
    async def get_ai_session(iid: str, x_interview_token: str | None = Header(None)):
        return view(load(iid, x_interview_token))

    @app.post('/api/ai/sessions/{iid}/start')
    async def start_ai_session(iid: str, x_interview_token: str | None = Header(None)):
        async with lock_for(iid):
            row = load(iid, x_interview_token)
            if InterviewState.model_validate_json(row.state).phase == Phase.CREATED:
                engine = restore(row)
                await engine.handle(RuntimeEvent(type='INTERVIEW_STARTED'))
                with database.session(write=True) as db:
                    db.get(AISession, iid).started = engine.started
                save(row, engine)
            elif InterviewState.model_validate_json(row.state).phase not in (Phase.WAITING_FOR_ANSWER, Phase.COMPLETED):
                engine = restore(row)
                await engine.resume()
                save(row, engine)
            return view(load(iid, x_interview_token))

    @app.post('/api/ai/sessions/{iid}/answers')
    async def answer_ai_session(iid: str, body: CandidateAnswer, x_interview_token: str | None = Header(None)):
        async with lock_for(iid):
            row = load(iid, x_interview_token)
            state = InterviewState.model_validate_json(row.state)
            existing = next((t for t in state.turns if t.question.id == body.question_id), None)
            if existing:
                if existing.answer.text != body.text:
                    raise HTTPException(409, 'Ответ уже сохранён и не может быть изменён.')
                if state.phase not in (Phase.WAITING_FOR_ANSWER, Phase.COMPLETED):
                    engine = restore(row)
                    await engine.resume()
                    save(row, engine)
                return view(load(iid, x_interview_token))
            if state.pending_answer:
                if state.pending_answer != body:
                    raise HTTPException(409, 'Повторите обработку сохранённого ответа.')
                engine = restore(row)
                await engine.resume()
                save(row, engine)
                return view(load(iid, x_interview_token))
            if state.phase != Phase.WAITING_FOR_ANSWER or state.questions[-1].id != body.question_id:
                raise HTTPException(409, 'Сначала ответьте на текущий вопрос.')
            if row.pending and CandidateAnswer.model_validate_json(row.pending) != body:
                raise HTTPException(409, 'Предыдущий ответ сохранён. Повторите его обработку.')
            engine = restore(row)
            # Commit before network I/O; retries after disconnection/restart use this answer.
            save(row, engine, body.model_dump_json())
            await engine.handle(RuntimeEvent(type='ANSWER_SUBMITTED', question_id=body.question_id), body.text)
            save(row, engine)
            return view(load(iid, x_interview_token))

    @app.post('/api/ai/sessions/{iid}/events')
    async def runtime_event(iid: str, body: RuntimeEvent, x_interview_token: str | None = Header(None)):
        if body.type not in ('PASTE_DETECTED', 'COPY_DETECTED', 'FOCUS_LOST', 'FOCUS_RETURNED'):
            raise HTTPException(422, 'Это событие не поддерживается данным endpoint.')
        async with lock_for(iid):
            row = load(iid, x_interview_token)
            engine = restore(row)
            try:
                outcome = await engine.handle(body)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
            return {'accepted': True, 'event_id': body.id, **(outcome or {})}

    @app.post('/api/ai/sessions/{iid}/finish')
    async def finish_ai_session(iid: str, x_interview_token: str | None = Header(None)):
        async with lock_for(iid):
            row = load(iid, x_interview_token)
            state = InterviewState.model_validate_json(row.state)
            if row.pending:
                raise HTTPException(409, 'Сначала повторите обработку сохранённого ответа.')
            if state.phase == Phase.CREATED:
                raise HTTPException(409, 'Сначала начните интервью.')
            if state.phase != Phase.COMPLETED:
                engine = restore(row)
                if state.phase != Phase.WAITING_FOR_ANSWER:
                    raise HTTPException(409, 'Сначала продолжите обработку интервью.')
                await engine.handle(RuntimeEvent(type='INTERVIEW_FINISH_REQUESTED'))
                save(row, engine)
            return view(load(iid, x_interview_token))
