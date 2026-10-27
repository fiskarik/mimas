from ai_core.interview.planner import CompetencyPlan
from ai_core.interview.state import InterviewState, Phase, Turn
from ai_core.models import Level
from ai_core.reports.answer_review import RED_FLAG_CAP, RUBRIC, card_rubric, review_answer, review_card_answer


def generate_report(state: InterviewState, *, mode: str) -> dict:
    if state.phase != Phase.COMPLETED:
        raise ValueError('Report requires a completed interview')
    plan = state.plan_snapshot
    uses_cards = bool(plan and plan.uses_cards)
    skill_names = {skill.id: skill.name for skill in plan.skills} if plan else {}
    reviews = [_review(plan, turn) for turn in state.turns]
    card_scores = _card_scores(plan, reviews) if uses_cards else None
    skills = []
    for skill in state.skills:
        turns = [t for t in state.turns if t.question.skill == skill.skill]
        successful = [t for t in turns if t.evaluation.result
                      and t.evaluation.result.correctness == 'correct'
                      and t.evaluation.result.depth in ('medium', 'high')
                      and not t.evaluation.result.missing_concepts
                      and t.question.generation in ('llm', 'approved_template')]
        positive = [e for e in skill.evidence if e.type == 'positive']
        problems = any(m.status != 'resolved' for m in skill.misconceptions) or any(c.skill == skill.skill and c.status != 'resolved' for c in state.contradictions)
        level = None
        # A conservative prototype rubric: two different goals, no unresolved
        # contradictions and no negative evidence. Never extrapolate above target.
        if len({t.question.goal for t in successful}) >= 2 and not problems and not any(e.type == 'negative' for e in skill.evidence):
            difficulty = min(t.question.difficulty for t in successful)
            level = list(Level)[min(difficulty - 1, list(Level).index(skill.target_level))].value
        entry = {
            'runtime_status': skill.status,
            'skill': skill.skill, 'name': skill_names.get(skill.skill, skill.skill),
            'demonstrated_level': level,
            'conclusion_scope': 'Только проверенные темы; предварительное правило агрегации v1.',
            'status': 'provisional' if level else 'insufficient_evidence',
            'questions_asked': skill.questions_asked, 'answers_received': len(turns),
            'evaluated_answers': sum(t.evaluation.status == 'evaluated' for t in turns),
            'strengths': [{'claim': e.claim, 'evidence_id': e.id} for e in positive],
            'gaps': [{'claim': e.claim, 'evidence_id': e.id} for e in skill.evidence if e.type != 'positive'],
            'missing_concepts': sorted({c for t in turns if t.evaluation.result for c in t.evaluation.result.missing_concepts}),
            'misconceptions': [m.model_dump(mode='json') for m in skill.misconceptions],
            'evidence': [e.model_dump(mode='json') for e in skill.evidence],
        }
        if uses_cards:
            # Template v2 has no levels: a competency shows the mean of its question scores.
            points = [c['points'] for c in card_scores if c['skill'] == skill.skill and c['points'] is not None]
            score = round(sum(points) / len(points), 1) if points else None
            entry.update(demonstrated_level=None, score=score,
                         status='provisional' if score is not None else 'insufficient_evidence',
                         conclusion_scope='Баллы по утверждённым описаниям ответов; предварительная оценка.')
        skills.append(entry)
    report = {'schema_version': 'evidence_report_v2', 'mode': mode,
              'integrity': {'events_truncated': state.events_truncated,
                            'signals': [s.model_dump(mode='json') for s in state.integrity_signals],
                            'verifications': [v.model_dump(mode='json') for v in state.verification_history],
                            'note': 'Наблюдаемые события не доказывают использование внешней помощи. Результат проверки описывает только продемонстрированное понимание.'},
              'contradictions': [c.model_dump(mode='json') for c in state.contradictions],
              'scoring_rubric': RUBRIC,
              'answer_reviews': reviews,
              'role': state.config.role, 'target_level': state.config.target_level.value,
              'stop_reason': state.stop_reason, 'skills': skills,
              'overall_technical_summary': f'{_answer_count_summary(len(state.turns))}. Выводы ограничены проверенными темами; неопределённость сохранена.',
              'quality_status': 'prototype_not_expert_validated'}
    if uses_cards:
        report.update(template_format=2, card_scores=card_scores,
                      scoring_rubric=card_rubric(plan.not_assessed))
    return report


def _review(plan: CompetencyPlan | None, turn: Turn) -> dict:
    card = plan.card_for(turn.question.skill, turn.question.card_index) if plan else None
    return review_card_answer(turn, card, plan.not_assessed) if card else review_answer(turn)


def _card_scores(plan: CompetencyPlan, reviews: list[dict]) -> list[dict]:
    """One score per asked card: the best of its answers, capped by any red flag."""
    scores = []
    for competency in plan.skills:
        for index, card in enumerate(competency.cards):
            related = [r for r in reviews if r['skill'] == competency.id and r.get('card_index') == index]
            if not related:
                continue
            assessed = [r['points'] for r in related if r['status'] == 'assessed']
            flags = [flag for r in related for flag in r['red_flags']]
            points = max(assessed) if assessed else None
            if points is not None and flags:
                points = min(points, RED_FLAG_CAP)
            scores.append({'skill': competency.id, 'skill_name': competency.name, 'card_index': index,
                           'type': card.type, 'goal': card.goal, 'question': related[0]['question'],
                           'points': points, 'max_points': 5,
                           'status': 'assessed' if points is not None else 'not_assessed',
                           'answers': len(related), 'red_flags': flags})
    return scores


def _answer_count_summary(count: int) -> str:
    if count % 100 in (11, 12, 13, 14):
        noun = 'ответов'
    else:
        noun = {1: 'ответ', 2: 'ответа', 3: 'ответа', 4: 'ответа'}.get(count % 10, 'ответов')
    verb = 'Получен' if noun == 'ответ' else 'Получено'
    return f'{verb} {count} {noun}'
