"""Persistent text interview API for the local, single-worker demo."""
import asyncio
import hashlib
import json
import secrets
import time
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base, Database
from ai_core.interview.engine import InterviewEngine
from ai_core.interview.schemas import CandidateAnswer
from ai_core.interview.state import InterviewState, Phase
from ai_core.llm.config import configured_groq
from ai_core.reports.generator import generate_report


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
        try:
            provider = configured_groq()
        except ValueError:
            raise HTTPException(503, 'Добавьте GROQ_API_KEY в локальный .env.') from None
        provider.model = row.model
        engine = InterviewEngine(provider, clock=time.time)
        engine.state = InterviewState.model_validate_json(row.state)
        engine.started = row.started
        engine.trace = json.loads(row.trace)
        return engine

    def save(row: AISession, engine: InterviewEngine, pending: str | None = None):
        with database.session(write=True) as db:
            stored = db.get(AISession, row.id)
            stored.state = engine.state.model_dump_json()
            stored.trace = json.dumps(engine.trace, ensure_ascii=False)
            stored.pending = pending

    def view(row: AISession) -> dict:
        state = InterviewState.model_validate_json(row.state)
        completed = state.phase == Phase.COMPLETED
        last = state.turns[-1] if state.turns else None
        return {'id': row.id, 'model': row.model, 'phase': state.phase,
                'questions': [q.model_dump(mode='json') for q in state.questions],
                'answers': [t.answer.model_dump(mode='json') for t in state.turns],
                'current_question': state.questions[-1].model_dump(mode='json') if state.phase == Phase.WAITING_FOR_ANSWER else None,
                'pending_answer': json.loads(row.pending) if row.pending else None,
                'max_questions': 20,
                'evaluation_notice': ('Ответ сохранён, но AI не смог его оценить. Причина: ' +
                                      ', '.join(last.evaluation.failures)) if last and last.evaluation.status == 'unavailable' else None,
                'report': generate_report(state, mode='live') if completed else None}

    @app.post('/api/ai/sessions')
    async def create_ai_session(x_company_key: str | None = Header(None)):
        authorize_company(x_company_key)
        try:
            provider = configured_groq()
        except ValueError:
            raise HTTPException(503, 'Для AI-интервью добавьте GROQ_API_KEY в локальный .env.') from None
        engine = InterviewEngine(provider, clock=time.time)
        token = secrets.token_urlsafe(32)
        row = AISession(id=uuid4().hex, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                        model=provider.model, started=time.time(), state=engine.state.model_dump_json(), trace='[]')
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
                await engine.start()
                with database.session(write=True) as db:
                    db.get(AISession, iid).started = engine.started
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
                return view(row)
            if state.phase != Phase.WAITING_FOR_ANSWER or state.questions[-1].id != body.question_id:
                raise HTTPException(409, 'Сначала ответьте на текущий вопрос.')
            if row.pending and CandidateAnswer.model_validate_json(row.pending) != body:
                raise HTTPException(409, 'Предыдущий ответ сохранён. Повторите его обработку.')
            engine = restore(row)
            # Commit before network I/O; retries after disconnection/restart use this answer.
            save(row, engine, body.model_dump_json())
            await engine.submit(body.question_id, body.text)
            save(row, engine)
            return view(load(iid, x_interview_token))

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
                engine.complete()
                save(row, engine)
            return view(load(iid, x_interview_token))
