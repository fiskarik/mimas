"""Load only Groq settings; never print or serialize credentials."""
import os
from pathlib import Path

from ai_core.llm.provider import GroqProvider

DEFAULT_MODEL = 'openai/gpt-oss-120b'


def configured_groq(env_file: Path | None = None) -> GroqProvider:
    env_file = env_file or Path(__file__).resolve().parents[2] / '.env'
    values: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8-sig').splitlines():
            key, separator, value = line.partition('=')
            if separator and key.strip() in ('GROQ_API_KEY', 'GROQ_MODEL'):
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                values[key.strip()] = value
    key = os.getenv('GROQ_API_KEY', values.get('GROQ_API_KEY', '')).strip()
    model = os.getenv('GROQ_MODEL', values.get('GROQ_MODEL', '')).strip() or DEFAULT_MODEL
    if not key:
        raise ValueError('Добавьте GROQ_API_KEY в локальный .env. Создать ключ: https://console.groq.com/keys')
    return GroqProvider(key, model)
