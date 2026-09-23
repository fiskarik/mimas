"""Official google-genai adapter. Domain schemas and decisions stay outside the SDK."""
import asyncio
import json
import logging
import time
from dataclasses import dataclass

import httpx
from google import genai
from google.genai import errors, types

from ai_core.llm.base import ProviderError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeminiThinkingPolicy:
    question: str = 'low'
    follow_up: str = 'medium'
    evaluation: str = 'medium'
    verification: str = 'medium'
    code_review: str = 'high'

    def __post_init__(self):
        if any(value not in ('low', 'medium', 'high') for value in vars(self).values()):
            raise ValueError('Gemini thinking levels must be low, medium or high')

    def for_operation(self, operation):
        if operation == 'health':
            return 'low'
        if operation not in vars(self):
            raise ValueError('Unsupported LLM operation')
        return getattr(self, operation)


class GeminiProvider:
    name = 'gemini'

    def __init__(self, api_key, model='gemini-3.8-flash', *, thinking=None, timeout_seconds=60,
                 max_attempts=2, client_factory=genai.Client, sleep=asyncio.sleep):
        if not api_key or not model:
            raise ValueError('Set GEMINI_API_KEY and MIMAS_GEMINI_MODEL')
        if not 1 <= max_attempts <= 3 or not 1 <= timeout_seconds <= 180:
            raise ValueError('Invalid Gemini timeout or attempt limit')
        self.api_key, self.model = api_key, model
        self.thinking = thinking or GeminiThinkingPolicy()
        self.timeout_seconds, self.max_attempts = timeout_seconds, max_attempts
        self.client_factory, self.sleep = client_factory, sleep
        self.telemetry_sink = None

    async def generate(self, *, system, payload, schema, operation='question'):
        level = self.thinking.for_operation(operation)
        # A domain-validation retry gets one more request, not another retry tree.
        attempts = 1 if payload.get('retry_feedback') else self.max_attempts
        http_options = types.HttpOptions(timeout=int(self.timeout_seconds * 1000),
                                         retry_options=types.HttpRetryOptions(attempts=1))
        config = types.GenerateContentConfig(
            system_instruction=system, response_mime_type='application/json',
            response_json_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_level=level.upper(), include_thoughts=False),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=512 if operation == 'health' else 8192,
        )
        # Per-call context closes transports on success, exceptions and cancellation.
        async with self.client_factory(api_key=self.api_key, http_options=http_options).aio as client:
            for attempt in range(1, attempts + 1):
                started = time.monotonic()
                usage = None
                error = None
                try:
                    async with asyncio.timeout(self.timeout_seconds):
                        response = await client.models.generate_content(
                            model=self.model, contents=json.dumps(payload, ensure_ascii=False), config=config)
                    usage = response.usage_metadata
                    candidates = response.candidates or []
                    if not candidates:
                        raise ProviderError('Gemini returned no candidate.', 'invalid_provider_response')
                    reason = getattr(candidates[0].finish_reason, 'value', candidates[0].finish_reason)
                    if reason == 'MAX_TOKENS':
                        raise ProviderError('Gemini output was truncated.', 'output_truncated')
                    if reason != 'STOP':
                        raise ProviderError('Gemini did not complete the response.', 'blocked_response')
                    # Read text parts explicitly: never expose thinking or SDK raw diagnostics.
                    content = candidates[0].content
                    raw = ''.join(p.text for p in (content.parts or []) if p.text and not p.thought) if content else ''
                    if not raw or not isinstance(json.loads(raw), dict):
                        raise ValueError('Expected JSON object')
                except (TimeoutError, httpx.TimeoutException):
                    error = ProviderError('Gemini request timed out.', 'timeout', retryable=True)
                except httpx.HTTPError:
                    error = ProviderError('Gemini connection failed.', 'network_error', retryable=True)
                except errors.APIError as exc:
                    code = {400:'invalid_request',401:'authentication_error',403:'access_denied',404:'model_unavailable',429:'rate_limit'}.get(exc.code, 'provider_error')
                    error = ProviderError('Gemini API request failed: ' + code, code, retryable=exc.code == 429 or exc.code >= 500)
                except (ValueError, TypeError):
                    error = ProviderError('Gemini returned invalid JSON.', 'invalid_provider_response')
                except ProviderError as exc:
                    error = exc
                metrics = {'provider':self.name, 'model':self.model, 'operation':operation,
                           'thinking_level':level, 'latency_ms':round((time.monotonic()-started)*1000),
                           'success':error is None, 'retry_count':attempt-1,
                           'input_tokens':getattr(usage, 'prompt_token_count', None),
                           'output_tokens':getattr(usage, 'candidates_token_count', None),
                           'thinking_tokens':getattr(usage, 'thoughts_token_count', None),
                           'total_tokens':getattr(usage, 'total_token_count', None),
                           'error_code':error.code if error else None}
                log.info('llm_request %s', json.dumps(metrics))
                if self.telemetry_sink:
                    self.telemetry_sink(metrics)
                if error is None:
                    return raw
                retry = error.retryable or error.code == 'invalid_provider_response'
                if not retry or attempt == attempts:
                    error.exhausted = True
                    raise error from None
                await self.sleep(min(2 ** (attempt-1), 4))
