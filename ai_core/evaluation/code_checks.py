"""Narrow static observations. Never execute candidate code or infer unknown values."""
import re

from ai_core.evaluation.schemas import EvaluationResult, EvidenceDraft


def check_materialization(result: EvaluationResult, answer: str) -> EvaluationResult:
    # Exact syntax proves allocation, independently of the language model's prose.
    # Only flag the contradiction if the answer explicitly claims no list storage.
    match = re.search(r'list\s*\(\s*itertools\.islice\([^\n)]*\)\s*\)', answer)
    claims_no_storage = any(phrase in answer.casefold() for phrase in
                            ('без сохранения в список', 'without storing in a list', 'without materializing'))
    if not match or not claims_no_storage:
        return result
    quote = match.group(0)
    evidence = [e for e in result.evidence if not (e.type == 'positive' and quote in e.quote)]
    evidence = evidence[:7] + [EvidenceDraft(type='negative',
        claim='Вызов list(itertools.islice(...)) сохраняет извлечённые элементы в список; утверждение об отсутствии сохранения противоречит коду.',
        quote=quote)]
    values = result.model_dump()
    values.update(correctness='partial', evidence=[e.model_dump() for e in evidence],
                  follow_up_required=True, follow_up_goal='Как потребить элементы итератора без накопления списка?')
    return EvaluationResult.model_validate(values)
