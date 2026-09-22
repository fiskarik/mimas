from typing import Protocol


class ProviderError(Exception):
    """Expected transport/provider failure, without credentials or raw response."""
    def __init__(self, message: str, code: str = 'provider_error', *, retryable: bool = False, exhausted: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.exhausted = exhausted


class LLMProvider(Protocol):
    async def generate(self, *, system: str, payload: dict, schema: dict, operation: str = 'question') -> str:
        """Return JSON text. Callers validate both schema and evidence grounding."""
        ...
