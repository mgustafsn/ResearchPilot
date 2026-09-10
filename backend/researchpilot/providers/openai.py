import logging

import httpx

from ..config import openai_base_url
from ..papers import ProviderError

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-small"
DIMENSION = 512
BATCH_SIZE = 256
MAX_CHARS = 30_000


class OpenAIEmbeddingProvider:
    name = "OpenAI"
    model = MODEL
    dimension = DIMENSION

    def __init__(self, client: httpx.AsyncClient, base_url: str | None = None):
        self.client = client
        self.base_url = (base_url or openai_base_url()).rstrip("/")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = [text[:MAX_CHARS] for text in texts[start : start + BATCH_SIZE]]
            logger.info("OpenAI embeddings batch=%s size=%s", start // BATCH_SIZE + 1, len(batch))
            try:
                response = await self.client.post(
                    f"{self.base_url}/embeddings",
                    json={"model": MODEL, "dimensions": DIMENSION, "input": batch},
                )
                if response.status_code in {401, 403}:
                    raise ProviderError("EMBEDDING_UNAUTHORIZED")
                if response.status_code == 429:
                    raise ProviderError("EMBEDDING_RATE_LIMITED")
                if response.status_code != 200:
                    raise ProviderError("EMBEDDING_UNAVAILABLE")
                payload = response.json()
            except httpx.HTTPError:
                raise ProviderError("EMBEDDING_UNAVAILABLE") from None
            except ValueError:
                raise ProviderError("EMBEDDING_INVALID_RESPONSE") from None
            vectors.extend(_vectors(payload, len(batch)))
        return vectors


def _vectors(payload, expected: int) -> list[list[float]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or len(data) != expected:
        raise ProviderError("EMBEDDING_INVALID_RESPONSE")
    try:
        ordered = sorted(data, key=lambda item: item["index"])
    except (KeyError, TypeError):
        raise ProviderError("EMBEDDING_INVALID_RESPONSE") from None
    result = []
    for item in ordered:
        vector = item.get("embedding") if isinstance(item, dict) else None
        if (
            not isinstance(vector, list)
            or len(vector) != DIMENSION
            or not all(
                isinstance(value, (int, float)) and not isinstance(value, bool) for value in vector
            )
        ):
            raise ProviderError("EMBEDDING_INVALID_RESPONSE")
        result.append([float(value) for value in vector])
    return result
