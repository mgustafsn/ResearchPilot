"""Provider-neutral embedding contract."""

from typing import Protocol


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimension: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
