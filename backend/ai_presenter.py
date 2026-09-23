"""Allowlisted candidate view; internal assessment is only exposed in final reports."""
import json
from ai_core.interview.state import InterviewState, Phase
from ai_core.reports.generator import generate_report


def session_view(row) -> dict:
    state = InterviewState.model_validate_json(row.state)
    completed = state.phase == Phase.COMPLETED
    last = state.turns[-1] if state.turns else None
    def public_question(q):
        return q.model_dump(mode='json', include={'id', 'skill', 'type', 'text', 'generation'})
    return {'id': row.id, 'model': row.model, 'phase': state.phase,
            'interview_id': row.id, 'status': 'completed' if completed else 'created' if state.phase == Phase.CREATED else 'in_progress',
            'action': (state.next_action or {}).get('action', 'ASK_QUESTION'),
            'progress': {'questions_answered':len(state.turns), 'skills_completed':sum(s.completed for s in state.skills), 'skills_total':len(state.skills)},
            'resume_required': state.phase not in (Phase.CREATED, Phase.WAITING_FOR_ANSWER, Phase.COMPLETED),
            'questions': [public_question(q) for q in state.questions],
            'answers': [t.answer.model_dump(mode='json') for t in state.turns],
            'current_question': public_question(state.questions[-1]) if state.phase == Phase.WAITING_FOR_ANSWER else None,
            'pending_answer': json.loads(row.pending) if row.pending else None,
            'max_questions': state.limits.max_questions,
            'evaluation_notice': ('Ответ сохранён, но AI не смог его оценить. Причина: ' +
                                  ', '.join(last.evaluation.failures)) if last and last.evaluation.status == 'unavailable' else None,
            'report': generate_report(state, mode='live') if completed else None}
