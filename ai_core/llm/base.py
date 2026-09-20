from typing import Protocol


class ProviderError(Exception):
    """Expected transport/provider failure, without credentials or raw response."""
    def __init__(self, message: str, code: str = 'provider_error'):
        super().__init__(message)
        self.code = code


class LLMProvider(Protocol):
    async def generate(self, *, system: str, payload: dict, schema: dict) -> str:
        """Return JSON text. Callers validate both schema and evidence grounding."""
        ...
