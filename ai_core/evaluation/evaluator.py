import logging

from ai_core.evaluation import prompts
from ai_core.evaluation.normalization import validate_grounding, no_answer_result, normalize_response, validate_scope, scoped_question_text
from pydantic import ValidationError
from ai_core.evaluation.code_checks import check_materialization
from ai_core.evaluation.schemas import EvaluationAttempt, EvaluationResult
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
                       verification: dict | None = None) -> EvaluationAttempt:
        abstention = no_answer_result(answer, question.difficulty)
        metadata = {'provider':getattr(self.provider, 'name', None), 'model':getattr(self.provider, 'model', None)}
        if abstention:
            return EvaluationAttempt(result=abstention, status='evaluated', attempts=1, provider='deterministic')
        payload = {'question': question.model_dump(mode='json'), 'answer': answer,
                   'expected_level': level.value, 'previous_evidence': previous_evidence,
                   'misconception_to_verify': misconception}
        payload['previous_answers_for_context_only'] = previous_answers or []
        payload['assessment_scope'] = question.goal
        payload['verification_target'] = verification
        payload['question']['text'] = scoped_question_text(question.text, question.goal)
        failures: list[str] = []
        for attempt in range(1, 3):
            try:
                raw = await self.provider.generate(system=prompts.SYSTEM, payload=payload,
                                                   schema=EvaluationResult.model_json_schema(),
                                                   operation='verification' if verification or misconception else 'evaluation')
                result = validate_grounding(normalize_response(EvaluationResult.model_validate_json(raw)), answer)
                validate_scope(result, question.goal)
                for item in result.contradictions:
                    previous = next((a for a in previous_answers or [] if a.get('question_id') == item.previous_question_id), None)
                    if not previous or item.previous_quote not in previous['answer'] or item.quote not in answer:
                        raise ValueError('Contradiction must cite both actual answers')
                result = check_materialization(result, answer)
                if not (question.type == 'verification' or question.misconception_id) and result.verification_outcome != 'uncertain':
                    raise ValueError('Unexpected verification outcome')
                return EvaluationAttempt(result=result, status='evaluated', attempts=attempt, failures=failures, **metadata)
            except (ProviderError, ValueError) as exc:
                if isinstance(exc, ProviderError) and exc.retryable:
                    raise
                category = (exc.code if isinstance(exc, ProviderError) else
                            'invalid_output' if isinstance(exc, ValidationError) else 'unsupported_evidence')
                failures.append(category)
                payload['retry_feedback'] = {'error': category, 'instruction': 'Return valid JSON; copy exact short quotes from current answer. Assess ONLY assessment_scope. Ignore unrelated tasks added in question text; do not demand tests/context managers for a mutability goal.'}
                # Deliberately exclude answer text, provider response and credentials.
                log.warning('evaluation_failed question=%s attempt=%s error=%s',
                            question.id, attempt, category)
                if category in ('rate_limit','authentication_error','access_denied','model_unavailable') or (isinstance(exc, ProviderError) and exc.exhausted):
                    return EvaluationAttempt(status='unavailable', attempts=attempt, failures=failures, **metadata)
        return EvaluationAttempt(status='unavailable', attempts=2, failures=failures, **metadata)
