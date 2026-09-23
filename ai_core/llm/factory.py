"""Backend-only configuration. No credential is stored in a session or public metadata."""
import os
from pathlib import Path

from ai_core.llm.config import configured_groq


def setting(name, default='', env_file=None):
    if name in os.environ:
        return os.environ[name].strip()
    path = env_file or Path(__file__).resolve().parents[2] / '.env'
    values = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.lstrip().startswith('#'):
                continue
            key, sep, value = line.partition('=')
            if sep:
                values[key.strip()] = value.strip().strip('\"\'')
    return values.get(name, default)


def create_llm_provider(*, provider=None, model=None, env_file=None):
    name = provider or setting('MIMAS_LLM_PROVIDER', 'gemini', env_file)
    if name == 'groq':
        result = configured_groq(env_file)
        if model:
            result.model = model
        return result
    if name != 'gemini':
        raise ValueError('MIMAS_LLM_PROVIDER must be gemini or groq')
    key = setting('GEMINI_API_KEY', env_file=env_file)
    if not key:
        raise ValueError('Добавьте GEMINI_API_KEY в локальный .env для Gemini.')
    from ai_core.llm.gemini import GeminiProvider, GeminiThinkingPolicy
    defaults = GeminiThinkingPolicy()
    policy = GeminiThinkingPolicy(**{op:setting(f'MIMAS_GEMINI_{op.upper()}_THINKING', value, env_file)
                                    for op, value in vars(defaults).items()})
    return GeminiProvider(key, model or setting('MIMAS_GEMINI_MODEL', 'gemini-3.8-flash', env_file), thinking=policy,
                          timeout_seconds=float(setting('MIMAS_LLM_TIMEOUT_SECONDS', '60', env_file)))


def llm_readiness():
    """Configuration check only: explicitly does not claim a working API connection."""
    try:
        result = create_llm_provider()
        return {'configured':True, 'provider':result.name, 'model':result.model, 'connection_checked':False}
    except (ValueError, ImportError):
        return {'configured':False, 'connection_checked':False}
