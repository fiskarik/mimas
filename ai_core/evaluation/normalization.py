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
    expectations = ' '.join([*result.missing_concepts, result.follow_up_goal,
                             result.follow_up_question or '']).casefold()
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
    for item in [*result.evidence, *result.misconceptions, *result.red_flags]:
        if item.quote not in answer:
            raise ValueError('Evidence quote absent from answer')
    return result


def prepare_card_output(data: dict, card: dict) -> dict:
    """Name the approved probe as the follow-up goal when the model left it empty."""
    if not isinstance(data, dict) or not data.get('follow_up_required'):
        return data
    probe = data.get('probe_index')
    if str(data.get('follow_up_goal') or '').strip():
        return data
    if isinstance(probe, int) and 0 <= probe < len(card['probes']):
        return {**data, 'follow_up_goal': card['probes'][probe]}
    return {**data, 'follow_up_required': False}


def apply_card(result: EvaluationResult, card: dict) -> EvaluationResult:
    """Enforce template v2 rules the model cannot be trusted to follow."""
    behavioral = card['type'] == 'behavioral'
    if behavioral and result.response_kind == 'substantive' and result.star is None:
        raise ValueError('Behavioral card requires a STAR check')
    if any(flag.index >= len(card['red_flags']) for flag in result.red_flags):
        raise ValueError('Unknown red flag')
    level = result.anchor_level
    if result.response_kind != 'substantive' or result.correctness == 'insufficient_evidence':
        level = None
    elif behavioral and not (result.star.situation and result.star.action):
        # No real example or own action: insufficient data, never a low score.
        level = None
    elif level is None:
        raise ValueError('Anchored card requires anchor_level')
    probe = result.probe_index if result.follow_up_required else None
    if probe is not None and probe >= len(card['probes']):
        probe = None
    return result.model_copy(update={
        'anchor_level': level, 'star': result.star if behavioral else None,
        'probe_index': probe, 'follow_up_required': probe is not None,
        'follow_up_goal': result.follow_up_goal if probe is not None else '',
        'follow_up_question': None})


def strip_card_fields(result: EvaluationResult) -> EvaluationResult:
    return result.model_copy(update={'anchor_level': None, 'red_flags': [],
                                     'probe_index': None, 'star': None})
