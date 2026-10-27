"""Transparent per-answer points derived from validated AI observations."""
from ai_core.interview.planner import QuestionCard
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


RED_FLAG_CAP = 2
CARD_RUBRIC = {
    'version': 'anchored_points_v1', 'max_points': 5,
    'description': 'Балл ставится по описаниям сильного, приемлемого и слабого ответа, утверждённым в шаблоне вопроса. Это оценка решения рабочей ситуации, а не уровня специалиста.',
    'rules': [
        '5 — ответ соответствует описанию сильного ответа.',
        '4 — ответ между сильным и приемлемым.',
        '3 — ответ соответствует описанию приемлемого ответа.',
        '2 — ответ между приемлемым и слабым. Это также максимум, если в ответе есть красный флаг.',
        '1 — ответ соответствует описанию слабого ответа.',
        'Не оценено — отказ, ответ не по теме, нет примера из личного опыта в вопросе об опыте или сбой AI. Это не ноль баллов.',
        'Ответ на уточнение оценивается вместе с исходным; по вопросу засчитывается лучший балл, но красный флаг ограничивает его.',
    ],
}
_LEVEL_DESCRIPTIONS = {4: 'Между сильным и приемлемым ответом.', 2: 'Между приемлемым и слабым ответом.'}
_LEVEL_REASONS = {
    5: 'Ответ соответствует описанию сильного ответа.',
    4: 'Ответ ближе к сильному, но не всё из описания сильного ответа прозвучало.',
    3: 'Ответ соответствует описанию приемлемого ответа.',
    2: 'Ответ слабее приемлемого: важные действия из описания не прозвучали.',
    1: 'Ответ соответствует описанию слабого ответа.',
}


def card_rubric(not_assessed: list[str]) -> dict:
    return {**CARD_RUBRIC, 'not_assessed': list(not_assessed)}


def review_card_answer(turn: Turn, card: QuestionCard, plan_not_assessed: list[str]) -> dict:
    """Template v2: points come from the card anchors; red flags cap them."""
    review = review_answer(turn)
    review.update(points=None, status='not_assessed', card_index=turn.question.card_index,
                  question_type=card.type, variant=turn.question.variant, anchor=None,
                  red_flags=[], star=None, not_assessed=[*plan_not_assessed, *card.not_assessed],
                  strengths=[], errors=[], uncertainties=[], missing_concepts=[], follow_up_goal='')
    result = turn.evaluation.result
    if turn.evaluation.status != 'evaluated' or result is None:
        return review
    review['star'] = result.star.model_dump() if result.star else None
    if result.response_kind != 'substantive' or result.correctness == 'insufficient_evidence':
        review['reason'] = 'В ответе недостаточно проверяемых оснований. Это не ноль баллов.'
        return review
    if card.type == 'behavioral' and result.star and not (result.star.situation and result.star.action):
        review['reason'] = ('В ответе нет реального случая или ваших собственных действий, поэтому '
                            'по вопросу об опыте балл не выставлен. Это не ноль баллов.')
        return review
    flags = [{'claim': card.red_flags[flag.index], 'quote': flag.quote} for flag in result.red_flags
             if flag.index < len(card.red_flags)]
    if (result.anchor_level is None or not result.evidence
            or any(e.quote not in turn.answer.text for e in [*result.evidence, *result.red_flags])):
        review['reason'] = 'Не удалось подтвердить основания оценки цитатами из ответа.'
        return review
    level = result.anchor_level
    points = min(level, RED_FLAG_CAP) if flags else level
    reason = _LEVEL_REASONS[level]
    if flags and points < level:
        reason = f'В ответе есть красный флаг, поэтому балл ограничен {RED_FLAG_CAP}. ' + reason
    description = {5: card.anchors.strong, 3: card.anchors.acceptable, 1: card.anchors.weak}.get(
        level, _LEVEL_DESCRIPTIONS.get(level))
    review.update(points=points, status='assessed', reason=reason, red_flags=flags,
                  anchor={'level': level, 'description': description},
                  strengths=[e.model_dump(mode='json') for e in result.evidence if e.type == 'positive'],
                  errors=[e.model_dump(mode='json') for e in result.evidence if e.type == 'negative'],
                  uncertainties=[e.model_dump(mode='json') for e in result.evidence if e.type == 'uncertain'],
                  missing_concepts=result.missing_concepts,
                  follow_up_goal=result.follow_up_goal if result.follow_up_required else '')
    return review
