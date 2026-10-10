"""Transparent per-answer points derived from validated AI observations."""
from ai_core.interview.state import Turn

RUBRIC = {
    'version': 'answer_points_v1', 'max_points': 5,
    'description': 'Балл рассчитывается по корректности и глубине, определённым AI. Это оценка отдельного ответа, а не уровня специалиста.',
    'rules': [
        '5 — корректно, глубокое объяснение, без отмеченных пробелов.',
        '4 — корректно, объяснение средней глубины, без отмеченных пробелов.',
        '3 — корректно, но кратко или с пробелами; либо частично верно с глубоким объяснением.',
        '2 — частично верно, объяснение средней глубины.',
        '1 — частично верно, поверхностное объяснение.',
        '0 — неверный ответ с подтверждённой цитатой ошибки.',
        'Не оценено — отказ, ответ не по теме, недостаточно оснований или сбой AI.',
    ],
}


def review_answer(turn: Turn) -> dict:
    result = turn.evaluation.result
    review = {'question_id': turn.question.id, 'skill': turn.question.skill,
              'question': turn.question.text, 'answer': turn.answer.text,
              'points': None, 'max_points': 5, 'status': 'not_assessed',
              'reason': 'AI не смог оценить ответ. Балл не выставлен.',
              'strengths': [], 'errors': [], 'uncertainties': [], 'missing_concepts': [],
              'follow_up_goal': '', 'failures': turn.evaluation.failures}
    if turn.evaluation.status != 'evaluated' or result is None:
        if 'evaluation_skipped_on_finish' in turn.evaluation.failures:
            review['reason'] = 'Ответ сохранён, но не оценён: интервью завершилось до обработки AI.'
        return review
    if result.response_kind != 'substantive' or result.correctness == 'insufficient_evidence':
        review['reason'] = 'В ответе недостаточно проверяемых оснований. Это не ноль баллов.'
        return review
    # Legacy sessions may contain unsupported citations: never turn those into points.
    if not result.evidence or any(e.quote not in turn.answer.text for e in result.evidence):
        review['reason'] = 'Не удалось подтвердить основания оценки цитатами из ответа.'
        return review
    positive = [e.model_dump(mode='json') for e in result.evidence if e.type == 'positive']
    negative = [e.model_dump(mode='json') for e in result.evidence if e.type == 'negative']
    uncertain = [e.model_dump(mode='json') for e in result.evidence if e.type == 'uncertain']
    if result.correctness == 'incorrect' and not negative:
        return review
    if result.correctness in ('correct', 'partial') and not positive and not negative:
        review['reason'] = 'Есть только неопределённые наблюдения — балл не выставлен.'
        return review
    if result.correctness == 'correct':
        points = {'low': 3, 'medium': 4, 'high': 5}[result.depth]
        reason = {'low': 'Ответ корректный, но объяснение краткое.',
                  'medium': 'Ответ корректный, механизм объяснён.',
                  'high': 'Ответ корректный, дано глубокое объяснение.'}[result.depth]
        if result.missing_concepts or negative or result.misconceptions or uncertain:
            points = min(points, 3)
            reason = 'Основная идея верна, но AI отметил пробелы или противоречия; балл ограничен 3.'
    elif result.correctness == 'partial':
        points = {'low': 1, 'medium': 2, 'high': 3}[result.depth]
        reason = 'Ответ частично верный. Балл учитывает глубину объяснения; ошибки и пробелы перечислены ниже.'
    else:
        points, reason = 0, 'AI отметил ошибку. Основания приведены в цитатах ниже.'
    review.update(points=points, status='assessed', reason=reason, strengths=positive,
                  errors=negative, uncertainties=uncertain, missing_concepts=result.missing_concepts,
                  follow_up_goal=result.follow_up_goal if result.follow_up_required else '')
    return review
