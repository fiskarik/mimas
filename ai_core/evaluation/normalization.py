from ai_core.evaluation.schemas import EvaluationResult
import re


def no_answer_result(answer: str, difficulty: int) -> EvaluationResult | None:
    normalized = re.sub(r'[^\w\s]', '', answer.casefold()).strip()
    normalized = ' '.join(normalized.split())
    phrases = {'не знаю', 'я не знаю', 'не умею', 'я не умею', 'хз', 'не помню',
               'пропустить', 'не могу ответить', 'спросите у профессионалов',
               'спросите у професиналов', 'i dont know', 'i do not know'}
    if normalized not in phrases:
        return None
    return EvaluationResult(response_kind='no_answer', correctness='insufficient_evidence',
                            depth='low', follow_up_required=False,
                            recommended_difficulty=max(1, difficulty - 1))


def normalize_response(result: EvaluationResult) -> EvaluationResult:
    if result.response_kind != 'substantive':
        return EvaluationResult(response_kind=result.response_kind,
                                correctness='insufficient_evidence', depth='low',
                                follow_up_required=False,
                                recommended_difficulty=result.recommended_difficulty)
    return result


def validate_scope(result: EvaluationResult, goal: str) -> None:
    # These are additional task requirements, not missing technical knowledge.
    if not any(term in goal.casefold() for term in ('аргумент', 'default', 'mutability')):
        return
    expectations = ' '.join([*result.missing_concepts, result.follow_up_goal]).casefold()
    for terms in [('контекст', 'context manager'), ('тест', 'test script')]:
        if not any(term in goal.casefold() for term in terms) and any(term in expectations for term in terms):
            raise ValueError('Assessment added an unrelated task outside its goal')


def scoped_question_text(text: str, goal: str) -> str:
    """Exclude unrelated numbered assignments in legacy generated questions.

    Preserve the original question in the trace; only evaluation input is scoped.
    New questions already reject numbered lists at generation time.
    """
    if not any(term in goal.casefold() for term in ('аргумент', 'default', 'mutability')):
        return text
    parts = re.split(r'(?m)(?=^\s*\d+[.)]\s)', text)
    if len(parts) == 1:
        return text
    kept = []
    for part in parts:
        unrelated = any(term in part.casefold() and term not in goal.casefold()
                        for term in ('контекст', 'context manager', 'тест', 'test script'))
        if not unrelated or not re.match(r'^\s*\d+[.)]\s', part):
            kept.append(part)
    return ''.join(kept)


def validate_grounding(result: EvaluationResult, answer: str) -> EvaluationResult:
    """Reject the entire unsupported assessment, not just its citations."""
    for item in [*result.evidence, *result.misconceptions]:
        if item.quote not in answer:
            raise ValueError('Evidence quote absent from answer')
    return result
