import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from google import genai
from google.genai import errors, types

from ai_core.evaluation.schemas import EvaluationResult
from ai_core.interview.schemas import GeneratedQuestion
from ai_core.llm.gemini import GeminiProvider, GeminiThinkingPolicy
from ai_core.llm.factory import create_llm_provider
from ai_core.llm.base import ProviderError


def response(text='{"text":"Question?"}', reason='STOP'):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(parts=[types.Part(text=text)]), finish_reason=reason)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=10, candidates_token_count=7,
                                                                 thoughts_token_count=5, total_token_count=22))


class ClientStub:
    def __init__(self, responses):
        self.models = SimpleNamespace(generate_content=AsyncMock(side_effect=responses))
        self.closed = False
        self.options = None

    def factory(self, **kwargs):
        self.options = kwargs
        return SimpleNamespace(aio=self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True


def provider(stub, **kwargs):
    return GeminiProvider('private-key', client_factory=stub.factory, sleep=AsyncMock(), **kwargs)


@pytest.mark.parametrize(('operation','expected'), [('question','low'),('follow_up','medium'),
    ('evaluation','medium'),('verification','medium'),('code_review','high'),('health','low')])
def test_schema_thinking_usage_and_no_sensitive_logging(operation, expected, caplog):
    caplog.set_level('INFO', logger='ai_core.llm.gemini')
    stub = ClientStub([response()])
    p = provider(stub)
    metrics = []
    p.telemetry_sink = metrics.append
    schema = EvaluationResult.model_json_schema()
    raw = asyncio.run(p.generate(system='private prompt', payload={'answer':'private answer'}, schema=schema, operation=operation))
    assert json.loads(raw)['text'] == 'Question?'
    config = stub.models.generate_content.call_args.kwargs['config']
    assert config.response_json_schema == schema
    assert config.response_mime_type == 'application/json'
    assert config.thinking_config.thinking_level.value.lower() == expected
    assert stub.options['http_options'].timeout == 60000
    assert stub.options['http_options'].retry_options.attempts == 1
    assert stub.closed
    assert metrics[0]['thinking_tokens'] == 5
    assert metrics[0]['input_tokens'] == 10
    assert all(secret not in caplog.text for secret in ('private-key','private answer','private prompt'))


@pytest.mark.parametrize(('error','code','retryable','attempts'), [
    (TimeoutError(), 'timeout', True, 2),
    (httpx.ReadTimeout('private'), 'timeout', True, 2),
    (httpx.ConnectError('private'), 'network_error', True, 2),
    (errors.APIError(429, {'error':{'message':'private-key'}}), 'rate_limit', True, 2),
    (errors.APIError(503, {'error':{'message':'private-key'}}), 'provider_error', True, 2),
    (errors.APIError(403, {'error':{'message':'private-key'}}), 'access_denied', False, 1),
    (errors.APIError(404, {'error':{'message':'private-key'}}), 'model_unavailable', False, 1),
])
def test_error_mapping_and_bounded_retries(error, code, retryable, attempts):
    stub = ClientStub([error, error])
    p = provider(stub)
    with pytest.raises(ProviderError) as caught:
        asyncio.run(p.generate(system='test', payload={}, schema=GeneratedQuestion.model_json_schema()))
    assert caught.value.code == code
    assert caught.value.retryable == retryable
    assert caught.value.exhausted
    assert 'private-key' not in str(caught.value)
    assert stub.models.generate_content.await_count == attempts
    assert stub.closed


def test_invalid_response_retried_then_valid_and_parsed():
    stub = ClientStub([response('not json'), response()])
    raw = asyncio.run(provider(stub).generate(system='test', payload={}, schema=GeneratedQuestion.model_json_schema()))
    assert GeneratedQuestion.model_validate_json(raw).text == 'Question?'
    assert stub.models.generate_content.await_count == 2


@pytest.mark.parametrize(('value','code'), [(response('[]'),'invalid_provider_response'),
    (response('', 'MAX_TOKENS'),'output_truncated'), (response('', 'SAFETY'),'blocked_response'),
    (types.GenerateContentResponse(),'invalid_provider_response')])
def test_unusable_responses_never_become_evidence(value, code):
    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider(ClientStub([value, value])).generate(system='test', payload={}, schema={}))
    assert caught.value.code == code


def test_validation_retry_does_not_multiply_transport_retries():
    stub = ClientStub([TimeoutError(), response()])
    with pytest.raises(ProviderError):
        asyncio.run(provider(stub).generate(system='test', payload={'retry_feedback':{'error':'invalid_output'}}, schema={}))
    assert stub.models.generate_content.await_count == 1


def test_real_sdk_schema_serialization_with_mock_transport():
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'candidates':[{'content':{'role':'model','parts':[{'text':'{"text":"Question?"}'}]},'finishReason':'STOP'}]})
    def client_factory(**kwargs):
        kwargs['http_options'].async_client_args = {'transport':httpx.MockTransport(handler)}
        return genai.Client(**kwargs)
    p = GeminiProvider('fake-key', client_factory=client_factory)
    raw = asyncio.run(p.generate(system='test', payload={}, schema=EvaluationResult.model_json_schema()))
    assert json.loads(raw)['text'] == 'Question?'
    config = requests[0]['generationConfig']
    assert config['responseMimeType'] == 'application/json'
    assert config['responseJsonSchema']['properties']['correctness']
    # google-genai 2.24 uses protobuf snake_case for nested thinking fields.
    assert config['thinkingConfig']['thinking_level'] == 'LOW'


def test_factory_selects_provider_and_environment_overrides_file(tmp_path, monkeypatch):
    for key in ('MIMAS_LLM_PROVIDER','GEMINI_API_KEY','GROQ_API_KEY','GROQ_MODEL','MIMAS_GEMINI_MODEL'):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path/'settings'
    env.write_text('GEMINI_API_KEY=fake-google\nGROQ_API_KEY=fake-groq\n', encoding='utf-8')
    assert create_llm_provider(provider='gemini', env_file=env).name == 'gemini'
    assert create_llm_provider(provider='gemini', env_file=env).model == 'gemini-3.8-flash'
    monkeypatch.setenv('MIMAS_LLM_PROVIDER','groq')
    assert create_llm_provider(env_file=env).name == 'groq'
    assert create_llm_provider(provider='gemini', env_file=env).name == 'gemini'
    monkeypatch.setenv('MIMAS_LLM_PROVIDER','unknown')
    with pytest.raises(ValueError):
        create_llm_provider(env_file=env)
    monkeypatch.setenv('GEMINI_API_KEY','')
    with pytest.raises(ValueError, match='GEMINI_API_KEY'):
        create_llm_provider(provider='gemini', env_file=env)


def test_custom_thinking_policy_and_invalid_values():
    assert GeminiThinkingPolicy(evaluation='high').for_operation('evaluation') == 'high'
    with pytest.raises(ValueError):
        GeminiThinkingPolicy(question='minimal')


def test_gemini_retry_does_not_duplicate_runtime_evidence():
    from ai_core.tests.test_core import evaluation
    from ai_core.interview.engine import InterviewEngine
    from ai_core.interview.schemas import Limits
    stub = ClientStub([response(), TimeoutError(), response(json.dumps(evaluation()))])
    async def run():
        engine = InterviewEngine(provider(stub), limits=Limits(max_questions=1))
        question = await engine.start()
        await engine.submit(question.id, 'created once')
        assert len(engine.state.turns) == 1
        assert len(engine.state.skills[0].evidence) == 1
        assert len(engine.state.questions) == 1
        assert engine.state.turns[0].evaluation.provider == 'gemini'
        assert engine.state.turns[0].evaluation.model == 'gemini-3.8-flash'
        assert len([event for event in engine.trace if event['event']=='llm_request']) == 3
    asyncio.run(run())
