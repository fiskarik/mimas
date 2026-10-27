"""Transparent per-answer points (1-10) derived from validated AI observations."""
from ai_core.evaluation.prompts import LEGACY_CARD_VERSION
from ai_core.interview.planner import QuestionCard
from ai_core.interview.state import Turn

MAX_POINTS = 10
RUBRIC = {
    'version': 'answer_points_v2', 'max_points': MAX_POINTS,
    'description': 'Балл от 1 до 10 рассчитывается по корректности и глубине, определённым AI. Это оценка отдельного ответа, а не уровня специалиста.',
    'rules': [
        '10 — корректно, глубокое объяснение, без отмеченных пробелов.',
        '8 — корректно, объяснение средней глубины, без отмеченных пробелов.',
        '6 — корректно, но кратко или с пробелами; либо частично верно с глубоким объяснением.',
        '4 — частично верно, объяснение средней глубины.',
        '2 — частично верно, поверхностное объяснение.',
        '1 — неверный ответ с подтверждённой цитатой ошибки.',
        'Не оценено — отказ, ответ не по теме, недостаточно оснований или сбой AI. Это не ноль баллов.',
    ],
}


def review_answer(turn: Turn) -> dict:
    result = turn.evaluation.result
    review = {'question_id': turn.question.id, 'skill': turn.question.skill,
              'question': turn.question.text, 'answer': turn.answer.text,
              'points': None, 'max_points': MAX_POINTS, 'status': 'not_assessed',
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
        points = {'low': 6, 'medium': 8, 'high': 10}[result.depth]
        reason = {'low': 'Ответ корректный, но объяснение краткое.',
                  'medium': 'Ответ корректный, механизм объяснён.',
                  'high': 'Ответ корректный, дано глубокое объяснение.'}[result.depth]
        if result.missing_concepts or negative or result.misconceptions or uncertain:
            points = min(points, 6)
            reason = 'Основная идея верна, но AI отметил пробелы или противоречия; балл ограничен 6.'
    elif result.correctness == 'partial':
        points = {'low': 2, 'medium': 4, 'high': 6}[result.depth]
        reason = 'Ответ частично верный. Балл учитывает глубину объяснения; ошибки и пробелы перечислены ниже.'
    else:
        points, reason = 1, 'AI отметил ошибку. Основания приведены в цитатах ниже.'
    review.update(points=points, status='assessed', reason=reason, strengths=positive,
                  errors=negative, uncertainties=uncertain, missing_concepts=result.missing_concepts,
                  follow_up_goal=result.follow_up_goal if result.follow_up_required else '')
    return review


RED_FLAG_CAP = 4
CARD_RUBRIC = {
    'version': 'anchored_points_v2', 'max_points': MAX_POINTS,
    'description': 'Балл от 1 до 10 ставится по описаниям сильного, приемлемого и слабого ответа, утверждённым в шаблоне вопроса. Это оценка решения рабочей ситуации, а не уровня специалиста.',
    'rules': [
        '9–10 — ответ соответствует описанию сильного ответа; 10 — полностью.',
        '7–8 — ответ между сильным и приемлемым.',
        '5–6 — ответ соответствует описанию приемлемого ответа; 6 — полностью.',
        '3–4 — ответ между приемлемым и слабым. 4 — также максимум, если в ответе есть красный флаг.',
        '1–2 — ответ соответствует описанию слабого ответа; 1 — если описанные действия могут навредить покупателю, магазину или нарушают закон.',
        'Не оценено — отказ, ответ не по теме, нет примера из личного опыта в вопросе об опыте или сбой AI. Это не ноль баллов.',
        'Ответ на уточнение оценивается вместе с исходным; по вопросу засчитывается лучший балл, но красный флаг ограничивает его.',
        'Балл по навыку и итоговый балл — среднее по оценённым вопросам.',
    ],
}
_BETWEEN = {'strong_acceptable': 'Между сильным и приемлемым ответом.',
            'acceptable_weak': 'Между приемлемым и слабым ответом.'}
_LEVEL_REASONS = {
    10: 'Ответ полностью соответствует описанию сильного ответа.',
    9: 'Ответ соответствует описанию сильного ответа, но одного небольшого элемента не хватает.',
    8: 'Ответ ближе к сильному, но не всё из описания сильного ответа прозвучало.',
    7: 'Ответ лучше приемлемого, но до сильного не хватает важных действий.',
    6: 'Ответ соответствует описанию приемлемого ответа.',
    5: 'Ответ в целом приемлемый, но часть описания приемлемого ответа не прозвучала.',
    4: 'Ответ слабее приемлемого: важные действия из описания не прозвучали.',
    3: 'Ответ ближе к слабому, чем к приемлемому.',
    2: 'Ответ соответствует описанию слабого ответа.',
    1: 'Слабый ответ: описанные действия могут навредить покупателю или магазину либо нарушают закон.',
}


def card_rubric(not_assessed: list[str]) -> dict:
    return {**CARD_RUBRIC, 'not_assessed': list(not_assessed)}


def card_level(turn: Turn) -> int | None:
    """Anchor level on the 1-10 scale; sessions scored on the old 1-5 scale are doubled."""
    level = turn.evaluation.result.anchor_level if turn.evaluation.result else None
    if level is not None and turn.evaluation.prompt_version == LEGACY_CARD_VERSION:
        return level * 2
    return level


def _anchor_description(card: QuestionCard, level: int) -> str:
    if level >= 9:
        return card.anchors.strong
    if level >= 7:
        return _BETWEEN['strong_acceptable']
    if level >= 5:
        return card.anchors.acceptable
    if level >= 3:
        return _BETWEEN['acceptable_weak']
    return card.anchors.weak


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
    level = card_level(turn)
    points = min(level, RED_FLAG_CAP) if flags else level
    reason = _LEVEL_REASONS[level]
    if flags and points < level:
        reason = f'В ответе есть красный флаг, поэтому балл ограничен {RED_FLAG_CAP}. ' + reason
    review.update(points=points, status='assessed', reason=reason, red_flags=flags,
                  anchor={'level': level, 'description': _anchor_description(card, level)},
                  strengths=[e.model_dump(mode='json') for e in result.evidence if e.type == 'positive'],
                  errors=[e.model_dump(mode='json') for e in result.evidence if e.type == 'negative'],
                  uncertainties=[e.model_dump(mode='json') for e in result.evidence if e.type == 'uncertain'],
                  missing_concepts=result.missing_concepts,
                  follow_up_goal=result.follow_up_goal if result.follow_up_required else '')
    return review
