from ai_core.interview.state import InterviewState, Phase
from ai_core.models import Level
from ai_core.reports.answer_review import RUBRIC, review_answer


def generate_report(state: InterviewState, *, mode: str) -> dict:
    if state.phase != Phase.COMPLETED:
        raise ValueError('Report requires a completed interview')
    skills = []
    for skill in state.skills:
        turns = [t for t in state.turns if t.question.skill == skill.skill]
        successful = [t for t in turns if t.evaluation.result
                      and t.evaluation.result.correctness == 'correct'
                      and t.evaluation.result.depth in ('medium', 'high')
                      and not t.evaluation.result.missing_concepts
                      and t.question.generation == 'llm']
        positive = [e for e in skill.evidence if e.type == 'positive']
        problems = any(m.status != 'resolved' for m in skill.misconceptions) or any(c.skill == skill.skill and c.status != 'resolved' for c in state.contradictions)
        level = None
        # A conservative prototype rubric: two different goals, no unresolved
        # contradictions and no negative evidence. Never extrapolate above target.
        if len({t.question.goal for t in successful}) >= 2 and not problems and not any(e.type == 'negative' for e in skill.evidence):
            difficulty = min(t.question.difficulty for t in successful)
            level = list(Level)[min(difficulty - 1, list(Level).index(skill.target_level))].value
        skills.append({
            'runtime_status': skill.status,
            'skill': skill.skill, 'demonstrated_level': level,
            'conclusion_scope': 'Только проверенные темы; предварительное правило агрегации v1.',
            'status': 'provisional' if level else 'insufficient_evidence',
            'questions_asked': skill.questions_asked, 'answers_received': len(turns),
            'evaluated_answers': sum(t.evaluation.status == 'evaluated' for t in turns),
            'strengths': [{'claim': e.claim, 'evidence_id': e.id} for e in positive],
            'gaps': [{'claim': e.claim, 'evidence_id': e.id} for e in skill.evidence if e.type != 'positive'],
            'missing_concepts': sorted({c for t in turns if t.evaluation.result for c in t.evaluation.result.missing_concepts}),
            'misconceptions': [m.model_dump(mode='json') for m in skill.misconceptions],
            'evidence': [e.model_dump(mode='json') for e in skill.evidence],
        })
    return {'schema_version': 'evidence_report_v2', 'mode': mode,
            'integrity': {'events_truncated': state.events_truncated,
                          'signals': [s.model_dump(mode='json') for s in state.integrity_signals],
                          'verifications': [v.model_dump(mode='json') for v in state.verification_history],
                          'note': 'Наблюдаемые события не доказывают использование внешней помощи. Результат проверки описывает только продемонстрированное понимание.'},
            'contradictions': [c.model_dump(mode='json') for c in state.contradictions],
            'scoring_rubric': RUBRIC,
            'answer_reviews': [review_answer(t) for t in state.turns],
            'role': state.config.role, 'target_level': state.config.target_level.value,
            'stop_reason': state.stop_reason, 'skills': skills,
            'overall_technical_summary': f'Получено {len(state.turns)} ответов. Выводы ограничены проверенными темами; неопределённость сохранена.',
            'quality_status': 'prototype_not_expert_validated'}
