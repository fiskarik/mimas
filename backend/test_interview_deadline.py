"""A deadline and manual finish produce a report without spending AI budget."""
from datetime import datetime, timezone
import hashlib
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_core.interview.engine import InterviewEngine
from ai_core.interview.schemas import CandidateAnswer, Question
from ai_core.interview.state import InterviewState, Phase
from ai_core.llm.provider import FakeLLMProvider
from backend.ai_web import AISession, register_ai_routes
from backend.test_assessment_flow import EphemeralDatabase


def _app_with_session(*, started: float, phase: Phase, pending_in_state: bool = False,
                      pending_in_row: bool = False, old_limit: bool = False):
    database = EphemeralDatabase()
    app = FastAPI()
    register_ai_routes(app, database, lambda _: None)
    engine = InterviewEngine(FakeLLMProvider([]))
    state = engine.state
    state.phase = phase
    state.started_at = datetime.fromtimestamp(started, timezone.utc)
    if old_limit:
        state.limits.time_budget_seconds = 1800
    question = Question(skill=state.skills[0].skill, difficulty=3, type='scenario',
                        goal='Изменяемые аргументы', text='Когда создаётся список по умолчанию?')
    state.questions.append(question)
    answer = CandidateAnswer(question_id=question.id, text='Список создаётся один раз.')
    if pending_in_state:
        state.pending_answer = answer
    token = 'test-private-candidate-token'
    with database.session(write=True) as db:
        db.add(AISession(
            id='deadline-test', token_hash=hashlib.sha256(token.encode()).hexdigest(),
            model='test-model', started=started, state=state.model_dump_json(), trace='[]',
            pending=answer.model_dump_json() if pending_in_row else None,
            candidate_id='candidate', opportunity_id='vacancy', archived=0))
    return app, database, token, answer


@pytest.mark.parametrize('pending_in_state,pending_in_row', [(True, True), (False, True)])
def test_finish_without_ai_preserves_checkpointed_answer_ungraded(
        pending_in_state, pending_in_row, monkeypatch):
    app, database, token, answer = _app_with_session(
        started=time.time(), phase=Phase.EVALUATE_ANSWER if pending_in_state else Phase.WAITING_FOR_ANSWER,
        pending_in_state=pending_in_state, pending_in_row=pending_in_row)
    headers = {'X-Interview-Token': token}
    def unexpected_provider(**_):
        raise AssertionError('Finishing must not call the paid AI provider')
    monkeypatch.setattr('backend.ai_web.create_llm_provider', unexpected_provider)
    with TestClient(app) as client:
        response = client.post('/api/ai/sessions/deadline-test/finish', headers=headers)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['phase'] == 'COMPLETED'
        # No camera was used, so the report does not wait for a video.
        assert result['recording_required'] is False and result['recording_status'] == 'none'
        assert result['report']['stop_reason'] == 'candidate_stopped'
        assert result['answers'] == [answer.model_dump()]
        review = result['report']['answer_reviews'][0]
        assert review['answer'] == answer.text
        assert review['points'] is None
        assert review['status'] == 'not_assessed'
        assert 'не оценён' in review['reason']
        assert 'Ответ сохранён без оценки' in result['evaluation_notice']
        assert client.post('/api/ai/sessions/deadline-test/finish', headers=headers).json()['answers'] == result['answers']
    database.engine.dispose()


def test_old_thirty_minute_session_expires_after_twenty_minutes():
    app, database, token, _ = _app_with_session(
        started=time.time() - 1201, phase=Phase.WAITING_FOR_ANSWER, old_limit=True)
    headers = {'X-Interview-Token': token}
    with TestClient(app) as client:
        response = client.get('/api/ai/sessions/deadline-test', headers=headers)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['phase'] == 'COMPLETED'
        assert result['report']['stop_reason'] == 'time_budget'
        assert result['report']['answer_reviews'] == []
        assert client.post('/api/ai/sessions/deadline-test/answers', headers=headers, json={
            'question_id': result['questions'][0]['id'], 'text': 'late'}).status_code == 409
    database.engine.dispose()


def test_active_session_exposes_server_deadline():
    started = time.time() - 3
    app, database, token, _ = _app_with_session(started=started, phase=Phase.WAITING_FOR_ANSWER)
    with TestClient(app) as client:
        result = client.get('/api/ai/sessions/deadline-test', headers={'X-Interview-Token': token}).json()
        assert result['phase'] == 'WAITING_FOR_ANSWER'
        assert result['deadline_at'] == pytest.approx(started + 1200, abs=0.01)
    database.engine.dispose()


def test_background_sweep_expires_interview_with_closed_tab():
    app, database, _, _ = _app_with_session(
        started=time.time() - 1201, phase=Phase.WAITING_FOR_ANSWER)
    with TestClient(app):
        for _ in range(100):
            with database.session() as db:
                state = InterviewState.model_validate_json(db.get(AISession, 'deadline-test').state)
            if state.phase == Phase.COMPLETED:
                break
            time.sleep(0.01)
        assert state.phase == Phase.COMPLETED
        assert state.stop_reason == 'time_budget'
    database.engine.dispose()
