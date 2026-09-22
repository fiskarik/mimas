import json
import logging
import time

import httpx

from ai_core.llm.base import ProviderError


class GroqProvider:
    """Same endpoint as the existing demo; no provider-specific domain logic."""
    name = 'groq'

    def __init__(self, api_key: str, model: str, *, transport: httpx.AsyncBaseTransport | None = None):
        if not api_key or not model:
            raise ValueError('Set GROQ_API_KEY and GROQ_MODEL for live mode')
        self.api_key = api_key
        self.model = model
        self.transport = transport
        self.telemetry_sink = None

    async def generate(self, *, system: str, payload: dict, schema: dict, operation: str = 'question') -> str:
        started = time.monotonic()
        self.last_usage = {}
        error = None
        try:
            return await self._generate(system=system, payload=payload, schema=schema)
        except ProviderError as exc:
            error = exc.code
            raise
        finally:
            metrics = {'provider':self.name, 'model':self.model, 'operation':operation,
                       'thinking_level':None, 'latency_ms':round((time.monotonic()-started)*1000),
                       'success':error is None, 'retry_count':int(bool(payload.get('retry_feedback'))),
                       'input_tokens':self.last_usage.get('prompt_tokens'),
                       'output_tokens':self.last_usage.get('completion_tokens'),
                       'total_tokens':self.last_usage.get('total_tokens'), 'error_code':error}
            logging.getLogger(__name__).info('llm_request %s', json.dumps(metrics))
            if self.telemetry_sink:
                self.telemetry_sink(metrics)

    async def _generate(self, *, system: str, payload: dict, schema: dict) -> str:
        try:
            async with httpx.AsyncClient(timeout=35, transport=self.transport) as client:
                response = await client.post(
                    'https://api.groq.com/openai/v1/chat/completions',
                    headers={'Authorization': f'Bearer {self.api_key}'},
                    json={'model': self.model, 'temperature': 0.2, 'max_tokens': 2200,
                          'response_format': {'type': 'json_object'},
                          'messages': [
                              {'role': 'system', 'content': system + '\nJSON Schema:\n' + json.dumps(schema)},
                              {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]},
                )
                if response.status_code >= 400:
                    messages = {401: 'Groq: неверный API-ключ.', 403: 'Groq: доступ запрещён для аккаунта.',
                                404: 'Groq: модель не найдена. Проверьте GROQ_MODEL.',
                                429: 'Groq: исчерпан лимит запросов или токенов. Повторите позже.'}
                    code = {401:'authentication_error',403:'access_denied',404:'model_unavailable',429:'rate_limit'}.get(response.status_code,'provider_error')
                    raise ProviderError(messages.get(response.status_code, f'Groq: ошибка HTTP {response.status_code}.'), code)
                content = response.json()['choices'][0]['message']['content']
                self.last_usage = response.json().get('usage') or {}
                if not isinstance(content, str):
                    raise ValueError('Non-text response')
                if response.json()['choices'][0].get('finish_reason') == 'length':
                    raise ProviderError('Groq: ответ обрезан лимитом токенов.', 'output_truncated')
                return content
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            code = 'network_error' if isinstance(exc,httpx.HTTPError) else 'invalid_provider_response'
            raise ProviderError(type(exc).__name__, code) from None


class OfflineProvider:
    """Flow preview only: deliberately produces no fabricated evaluations."""

    async def generate(self, *, system: str, payload: dict, schema: dict, operation: str = 'question') -> str:
        raise ProviderError('Offline mode: evaluation unavailable')


class FakeLLMProvider:
    """Queued responses for domain tests, never presented as live intelligence."""

    def __init__(self, responses: list[str | Exception]):
        self.responses = iter(responses)
        self.calls: list[dict] = []

    async def generate(self, *, system: str, payload: dict, schema: dict, operation: str = 'question') -> str:
        self.calls.append({'system': system, 'payload': payload, 'schema': schema, 'operation':operation})
        try:
            result = next(self.responses)
        except StopIteration:
            raise ProviderError('No scripted response') from None
        if isinstance(result, Exception):
            raise result
        return result
