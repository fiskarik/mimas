import asyncio
import json

import httpx
import pytest

from ai_core.llm.base import ProviderError
from ai_core.llm.config import configured_groq
from ai_core.llm.provider import GroqProvider


def test_groq_request_contract():
    def handler(request):
        assert str(request.url) == 'https://api.groq.com/openai/v1/chat/completions'
        assert request.headers['Authorization'] == 'Bearer test-key'
        body = json.loads(request.content)
        assert body['response_format'] == {'type':'json_object'}
        assert body['model'] == 'test-model'
        assert json.loads(body['messages'][1]['content']) == {'answer':'example'}
        return httpx.Response(200, json={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}]})
    provider = GroqProvider('test-key', 'test-model', transport=httpx.MockTransport(handler))
    assert asyncio.run(provider.generate(system='JSON only', payload={'answer':'example'}, schema={})) == '{"ok":true}'


@pytest.mark.parametrize('status', [401,403,404,429,500])
def test_http_error_does_not_expose_response_or_key(status):
    provider = GroqProvider('secret-test-key', 'model', transport=httpx.MockTransport(
        lambda request: httpx.Response(status, text='private provider response')))
    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.generate(system='JSON',payload={},schema={}))
    assert 'secret-test-key' not in str(error.value)
    assert 'private provider response' not in str(error.value)
    assert 'Groq' in str(error.value)


def test_config_quotes_env_priority_and_missing_key(tmp_path, monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY',raising=False)
    monkeypatch.delenv('GROQ_MODEL',raising=False)
    env = tmp_path / '.env'
    env.write_text('GROQ_API_KEY="local-key"\nGROQ_MODEL=\n',encoding='utf-8')
    provider = configured_groq(env)
    assert provider.api_key == 'local-key'
    assert provider.model == 'openai/gpt-oss-120b'
    monkeypatch.setenv('GROQ_API_KEY','environment-key')
    assert configured_groq(env).api_key == 'environment-key'
    monkeypatch.setenv('GROQ_API_KEY','')
    with pytest.raises(ValueError, match='GROQ_API_KEY'):
        configured_groq(env)
