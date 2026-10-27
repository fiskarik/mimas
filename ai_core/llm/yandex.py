"""Yandex AI Studio OpenAI-compatible adapter for DeepSeek-V4.1-Flash.

Only the transport is provider-specific. Domain validation and evidence checks
continue in ai_core. Requests never print API credentials or candidate content.
"""

import asyncio
import json
import logging
import time
from decimal import Decimal

import httpx
from jsonschema import Draft202012Validator, ValidationError, SchemaError

from ai_core.llm.base import ProviderError

log = logging.getLogger(__name__)
CHAT_URL = 'https://ai.api.cloud.yandex.net/v1/chat/completions'
DEFAULT_MODEL = 'deepseek-v4.1-flash'
INPUT_RUB_PER_1K = Decimal('0.30')
OUTPUT_RUB_PER_1K = Decimal('0.50')
# DeepSeek reasons before answering. At the model default an answer evaluation spent
# ~1000 hidden tokens and 20-70 s; even 'low' sometimes reasoned 2000+ tokens (3 min).
# 'none' answers in 6-15 s, so a candidate is never left waiting past the timeout.
REASONING_EFFORTS = ('none', 'low', 'medium', 'high')


def model_uri(folder_id: str, model: str = DEFAULT_MODEL) -> str:
    if not folder_id:
        raise ValueError('Set YANDEX_FOLDER_ID')
    if model.startswith('gpt://'):
        if not model.startswith(f'gpt://{folder_id}/'):
            raise ValueError('Yandex model belongs to another folder')
        return model
    if '/' in model or not model:
        raise ValueError('Invalid Yandex model name')
    return f'gpt://{folder_id}/{model}'


def estimated_cost(input_tokens: int, output_tokens: int) -> Decimal:
    return ((Decimal(input_tokens) * INPUT_RUB_PER_1K +
             Decimal(output_tokens) * OUTPUT_RUB_PER_1K) / Decimal('1000'))


class YandexProvider:
    name = 'yandex'

    def __init__(self, api_key: str, folder_id: str, model: str = DEFAULT_MODEL, *,
                 transport: httpx.AsyncBaseTransport | None = None,
                 timeout_seconds: float = 60, budget=None, reasoning_effort: str | None = 'none',
                 max_attempts: int = 2, sleep=asyncio.sleep):
        if not api_key or not folder_id:
            raise ValueError('Set YANDEX_API_KEY and YANDEX_FOLDER_ID')
        if not 1 <= timeout_seconds <= 180:
            raise ValueError('Invalid Yandex timeout')
        if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
            raise ValueError('Invalid Yandex reasoning effort')
        if not 1 <= max_attempts <= 3:
            raise ValueError('Invalid Yandex attempt count')
        self.api_key = api_key
        self.folder_id = folder_id
        self.model = model_uri(folder_id, model)
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.budget = budget
        self.reasoning_effort = reasoning_effort
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.telemetry_sink = None
        self.last_usage = {}

    async def generate(self, *, system: str, payload: dict, schema: dict,
                       operation: str = 'question') -> str:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await self._generate_once(system=system, payload=payload, schema=schema,
                                                 operation=operation)
            except ProviderError as exc:
                # A dropped connection or a busy model is usually brief. One quick
                # retry keeps a voice interview going instead of breaking the turn.
                if not exc.retryable or attempt == self.max_attempts:
                    raise
                log.warning('yandex_retry operation=%s attempt=%s error=%s', operation, attempt, exc.code)
                await self.sleep(attempt)

    async def _generate_once(self, *, system: str, payload: dict, schema: dict, operation: str) -> str:
        if not isinstance(payload, dict) or not isinstance(schema, dict):
            raise ValueError('Yandex input must be JSON objects')
        if schema:
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                raise ValueError('Invalid domain JSON Schema') from exc
        max_output_tokens = 512 if operation == 'health' else (
            8192 if operation == 'template' else 3072)
        prompt = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        schema_json = json.dumps(schema, ensure_ascii=False, separators=(',', ':'))
        if len(system) + len(prompt) + len(schema_json) > 120_000:
            raise ProviderError('Yandex request exceeds the MIMAS input limit.', 'input_too_large')
        instructions = system + '\nОтвечай только объектом JSON.'
        if schema:
            instructions += '\nJSON Schema:\n' + schema_json
        messages = [{'role': 'system', 'content': instructions},
                    {'role': 'user', 'content': prompt}]
        input_estimate = (len(instructions) + len(prompt)) * 2 + 256
        reserve_cost = estimated_cost(input_estimate, max_output_tokens)
        formats = ([{'type': 'json_schema',
                     'json_schema': {'name': 'mimas_result', 'schema': schema, 'strict': False}},
                    {'type': 'json_object'}] if schema else [{'type': 'json_object'}])
        index = -1
        while formats:
            index += 1
            response_format = formats.pop(0)
            started = time.monotonic()
            reservation_id = self.budget.reserve('llm', operation, reserve_cost) if self.budget else None
            error_code = None
            usage = {}
            request = {'model': self.model, 'temperature': 0.2, 'max_tokens': max_output_tokens,
                       'stream': False, 'response_format': response_format, 'messages': messages}
            # Interview turns wait for the answer; a vacancy template may think longer.
            effort = None if operation == 'template' else self.reasoning_effort
            if effort:
                request['reasoning_effort'] = effort
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                    response = await client.post(
                        CHAT_URL,
                        headers={'Authorization': f'Api-Key {self.api_key}',
                                 'OpenAI-Project': self.folder_id},
                        json=request,
                    )
                if response.status_code >= 400:
                    if response.status_code in (400, 422) and effort and 'reasoning_effort' in response.text:
                        # A model without reasoning rejects the parameter: ask again without it.
                        self.reasoning_effort = None
                        if reservation_id:
                            self.budget.release(reservation_id)
                        self._emit(operation, started, False, index, {}, 'reasoning_unsupported')
                        formats.insert(0, response_format)
                        continue
                    # A schema rejection can occur for model-specific unsupported
                    # keywords; retry once in JSON-object mode, then validate locally.
                    if (response.status_code in (400, 422) and response_format['type'] == 'json_schema'
                            and formats):
                        if reservation_id:
                            self.budget.release(reservation_id)
                        self._emit(operation, started, False, index, {}, 'schema_fallback')
                        continue
                    code = {400: 'invalid_request', 401: 'authentication_error',
                            403: 'access_denied', 404: 'model_unavailable',
                            429: 'rate_limit'}.get(response.status_code, 'provider_error')
                    if reservation_id and response.status_code < 500:
                        self.budget.release(reservation_id)
                    raise ProviderError(f'Yandex AI Studio: HTTP {response.status_code}.',
                                        code, retryable=response.status_code in (429, 500, 502, 503, 504))
                body = response.json()
                usage = body.get('usage') or {}
                choices = body.get('choices') or []
                if not choices or not isinstance(choices[0], dict):
                    raise ProviderError('Yandex returned no answer.', 'invalid_provider_response')
                if choices[0].get('finish_reason') == 'length':
                    raise ProviderError('Yandex answer was truncated.', 'output_truncated')
                if choices[0].get('finish_reason') not in ('stop', None):
                    raise ProviderError('Yandex did not finish the answer.', 'blocked_response')
                raw = choices[0].get('message', {}).get('content')
                if not isinstance(raw, str):
                    raise ProviderError('Yandex returned non-text output.', 'invalid_provider_response')
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ProviderError('Yandex returned non-object JSON.', 'invalid_provider_response')
                if schema:
                    Draft202012Validator(schema).validate(parsed)
                self.last_usage = usage
                if reservation_id:
                    self.budget.settle(reservation_id, self._actual_cost(usage, reserve_cost),
                                       self._usage_summary(usage))
                self._emit(operation, started, True, index, usage, None)
                return raw
            except ProviderError as exc:
                error_code = exc.code
                if reservation_id and exc.code not in ('invalid_request', 'authentication_error',
                                                        'access_denied', 'model_unavailable', 'rate_limit'):
                    # The request may have reached Yandex. Conservatively account
                    # its reservation if actual usage is unavailable.
                    self.budget.settle(reservation_id, self._actual_cost(usage, reserve_cost),
                                       self._usage_summary(usage) | {'uncertain': not bool(usage)})
                self._emit(operation, started, False, index, usage, error_code)
                raise
            except (httpx.HTTPError, ValueError, TypeError, KeyError, ValidationError) as exc:
                error_code = ('network_error' if isinstance(exc, httpx.HTTPError)
                              else 'invalid_provider_response')
                if reservation_id:
                    self.budget.settle(reservation_id, self._actual_cost(usage, reserve_cost),
                                       self._usage_summary(usage) | {'uncertain': not bool(usage)})
                self._emit(operation, started, False, index, usage, error_code)
                raise ProviderError('Yandex AI Studio response unavailable.', error_code,
                                    retryable=isinstance(exc, httpx.HTTPError)) from None

    @staticmethod
    def _actual_cost(usage: dict, estimate: Decimal) -> Decimal:
        try:
            input_tokens = int(usage['prompt_tokens'])
            output_tokens = int(usage['completion_tokens'])
            if input_tokens < 0 or output_tokens < 0:
                raise ValueError()
            return estimated_cost(input_tokens, output_tokens)
        except (KeyError, TypeError, ValueError):
            return estimate

    @staticmethod
    def _usage_summary(usage: dict) -> dict:
        return {key: usage[key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                if isinstance(usage.get(key), int)}

    def _emit(self, operation, started, success, retry_count, usage, error_code):
        metrics = {'provider': self.name, 'model': self.model,
                   'operation': operation, 'thinking_level': None,
                   'latency_ms': round((time.monotonic() - started) * 1000),
                   'success': success, 'retry_count': retry_count,
                   'input_tokens': usage.get('prompt_tokens'),
                   'output_tokens': usage.get('completion_tokens'),
                   'total_tokens': usage.get('total_tokens'),
                   'error_code': error_code}
        log.info('llm_request %s', json.dumps(metrics))
        if self.telemetry_sink:
            try:
                self.telemetry_sink(metrics)
            except Exception:
                log.exception('Yandex telemetry sink failed')
