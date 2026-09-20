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
                       previous_answers: list[dict] | None = None) -> EvaluationAttempt:
        abstention = no_answer_result(answer, question.difficulty)
        if abstention:
            return EvaluationAttempt(result=abstention, status='evaluated', attempts=1)
        payload = {'question': question.model_dump(mode='json'), 'answer': answer,
                   'expected_level': level.value, 'previous_evidence': previous_evidence,
                   'misconception_to_verify': misconception}
        payload['previous_answers_for_context_only'] = previous_answers or []
        payload['assessment_scope'] = question.goal
        payload['question']['text'] = scoped_question_text(question.text, question.goal)
        failures: list[str] = []
        for attempt in range(1, 3):
            try:
                raw = await self.provider.generate(system=prompts.SYSTEM, payload=payload,
                                                   schema=EvaluationResult.model_json_schema())
                result = validate_grounding(normalize_response(EvaluationResult.model_validate_json(raw)), answer)
                validate_scope(result, question.goal)
                result = check_materialization(result, answer)
                if question.type != 'verification' and result.verification_outcome != 'uncertain':
                    raise ValueError('Unexpected verification outcome')
                return EvaluationAttempt(result=result, status='evaluated', attempts=attempt, failures=failures)
            except (ProviderError, ValueError) as exc:
                category = (exc.code if isinstance(exc, ProviderError) else
                            'invalid_output' if isinstance(exc, ValidationError) else 'unsupported_evidence')
                failures.append(category)
                payload['retry_feedback'] = {'error': category, 'instruction': 'Return valid JSON; copy exact short quotes from current answer. Assess ONLY assessment_scope. Ignore unrelated tasks added in question text; do not demand tests/context managers for a mutability goal.'}
                # Deliberately exclude answer text, provider response and credentials.
                log.warning('evaluation_failed question=%s attempt=%s error=%s',
                            question.id, attempt, category)
                if category in ('rate_limit','authentication_error','access_denied','model_unavailable'):
                    return EvaluationAttempt(status='unavailable', attempts=attempt, failures=failures)
        return EvaluationAttempt(status='unavailable', attempts=2, failures=failures)
