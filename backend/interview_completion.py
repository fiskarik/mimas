"""Finish a persisted AI interview without any provider call."""
import json
from datetime import datetime, timezone

from ai_core.evaluation.schemas import EvaluationAttempt
from ai_core.interview.events import RuntimeEvent
from ai_core.interview.schemas import CandidateAnswer
from ai_core.interview.state import InterviewState, Phase, Turn


class CompletionError(ValueError):
    pass


def complete_without_ai(state: InterviewState, pending_json: str | None,
                        trace_json: str, reason: str) -> tuple[InterviewState, str]:
    """Return completed copies; pending text is retained as ungraded evidence."""
    state = state.model_copy(deep=True)
    if state.phase == Phase.COMPLETED:
        return state, trace_json
    if state.phase == Phase.CREATED:
        raise CompletionError('Сначала начните интервью.')
    pending = state.pending_answer or (
        CandidateAnswer.model_validate_json(pending_json) if pending_json else None)
    if pending and not any(turn.question.id == pending.question_id for turn in state.turns):
        question = next((item for item in state.questions if item.id == pending.question_id), None)
        if question is None:
            raise CompletionError('Сохранённый ответ не относится к вопросу интервью.')
        state.turns.append(Turn(
            question=question, answer=pending,
            evaluation=EvaluationAttempt(
                provider=state.llm_provider, status='unavailable', attempts=1,
                failures=['evaluation_skipped_on_finish'])))
        if not any(event.type == 'ANSWER_SUBMITTED' and event.question_id == pending.question_id
                   for event in state.events):
            state.events.append(RuntimeEvent(type='ANSWER_SUBMITTED', question_id=pending.question_id))
    if reason == 'candidate_stopped':
        state.events.append(RuntimeEvent(type='INTERVIEW_FINISH_REQUESTED'))
    state.phase = Phase.COMPLETED
    state.stop_reason = reason
    state.pending_answer = None
    state.pending_spec = None
    state.next_action = {'action': 'FINISH', 'reason': reason}
    state.updated_at = datetime.now(timezone.utc)
    for skill in state.skills:
        if skill.status == 'IN_PROGRESS':
            skill.status = 'INSUFFICIENT_EVIDENCE'
    trace = json.loads(trace_json)
    trace.append({'event': 'interview_completed', 'created_at': state.updated_at.isoformat(),
                  'phase': Phase.COMPLETED.value, 'reason': reason})
    return state, json.dumps(trace, ensure_ascii=False)
