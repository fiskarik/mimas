import json
import logging

from ai_core.evaluation import prompts
from ai_core.evaluation.normalization import (apply_card, no_answer_result, normalize_response, prepare_card_output,
                                              scoped_question_text, strip_card_fields, validate_grounding,
                                              validate_scope)
from pydantic import ValidationError
from ai_core.evaluation.code_checks import check_materialization
from ai_core.evaluation.schemas import EvaluationAttempt, EvaluationResult, evaluation_json_schema
from ai_core.interview.schemas import Question
from ai_core.llm.base import LLMProvider, ProviderError
from ai_core.models import Level

log = logging.getLogger(__name__)


class AnswerEvaluator:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def evaluate(self, question: Question, answer: str, level: Level,
                       previous_evidence: list[dict], misconception: dict | None = None,
                       previous_answers: list[dict] | None = None,
                       verification: dict | None = None, criteria: list[str] | None = None,
                       card: dict | None = None, parent: dict | None = None) -> EvaluationAttempt:
        abstention = no_answer_result(answer, question.difficulty)
        metadata = {'provider':getattr(self.provider, 'name', None), 'model':getattr(self.provider, 'model', None),
                    'prompt_version': prompts.CARD_VERSION if card else prompts.VERSION}
        if abstention:
            return EvaluationAttempt(result=abstention, status='evaluated', attempts=1, provider='deterministic',
                                     prompt_version=metadata['prompt_version'])
        if card:
            # The card is the whole scoring guide; earlier answers and levels only add input.
            payload = {'question': question.text, 'answer': answer, 'question_card': card}
            if parent:
                payload['parent_turn'] = parent
        else:
            payload = {'question': question.model_dump(mode='json'), 'answer': answer,
                       'expected_level': level.value, 'previous_evidence': previous_evidence,
                       'misconception_to_verify': misconception}
            payload['previous_answers_for_context_only'] = previous_answers or []
            payload['assessment_scope'] = question.goal
            if criteria:
                payload['approved_criteria'] = criteria
            payload['verification_target'] = verification
            payload['question']['text'] = scoped_question_text(question.text, question.goal)
        system = prompts.CARD_SYSTEM + prompts.CARD_RULES if card else prompts.SYSTEM
        schema = evaluation_json_schema(cards=bool(card))
        failures: list[str] = []
        for attempt in range(1, 3):
            try:
                raw = await self.provider.generate(system=system, payload=payload, schema=schema,
                                                   operation='verification' if verification or misconception else 'evaluation')
                data = json.loads(raw)
                if card:
                    data = prepare_card_output(data, card)
                result = validate_grounding(normalize_response(EvaluationResult.model_validate(data)), answer)
                validate_scope(result, question.goal)
                for item in result.contradictions:
                    previous = next((a for a in previous_answers or [] if a.get('question_id') == item.previous_question_id), None)
                    if not previous or item.previous_quote not in previous['answer'] or item.quote not in answer:
                        raise ValueError('Contradiction must cite both actual answers')
                result = check_materialization(result, answer)
                if not (question.type == 'verification' or question.misconception_id) and result.verification_outcome != 'uncertain':
                    raise ValueError('Unexpected verification outcome')
                result = apply_card(result, card) if card else strip_card_fields(result)
                return EvaluationAttempt(result=result, status='evaluated', attempts=attempt, failures=failures, **metadata)
            except (ProviderError, ValueError) as exc:
                if isinstance(exc, ProviderError) and exc.retryable:
                    raise
                category = (exc.code if isinstance(exc, ProviderError) else
                            'invalid_output' if isinstance(exc, (ValidationError, json.JSONDecodeError)) else 'unsupported_evidence')
                failures.append(category)
                payload['retry_feedback'] = {'error': category, 'instruction': (
                    'Return valid JSON; copy exact short quotes from current answer. Follow question_card: '
                    'anchor_level from its anchors, red_flags and probe_index only by valid index, star for '
                    'behavioral cards.' if card else
                    'Return valid JSON; copy exact short quotes from current answer. Assess ONLY assessment_scope. Ignore unrelated tasks added in question text; do not demand tests/context managers for a mutability goal.')}
                # Deliberately exclude answer text, provider response and credentials.
                log.warning('evaluation_failed question=%s attempt=%s error=%s',
                            question.id, attempt, category)
                if category in ('rate_limit','authentication_error','access_denied','model_unavailable') or (isinstance(exc, ProviderError) and exc.exhausted):
                    return EvaluationAttempt(status='unavailable', attempts=attempt, failures=failures, **metadata)
        return EvaluationAttempt(status='unavailable', attempts=2, failures=failures, **metadata)
