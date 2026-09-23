import json
import logging

import httpx
from pydantic import ValidationError

from ..config import openai_base_url
from ..llm import ClusterNaming, PaperBrief, PaperExplanation, QueryExpansion
from ..papers import ProviderError
from ..prompts import cluster_naming_messages, paper_explanation_messages, query_expansion_messages

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-small"
DIMENSION = 512
BATCH_SIZE = 256
MAX_CHARS = 30_000

LLM_MODEL = "gpt-4o-mini"
_NAMING_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "description", "keywords"],
    "additionalProperties": False,
}
_EXPLANATION_SCHEMA = {
    "type": "object",
    "properties": {"explanation": {"type": "string"}},
    "required": ["explanation"],
    "additionalProperties": False,
}
_QUERY_SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
    "additionalProperties": False,
}


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


class OpenAILlmProvider:
    name = "OpenAI"
    model = LLM_MODEL

    def __init__(self, client: httpx.AsyncClient, base_url: str | None = None):
        self.client = client
        self.base_url = (base_url or openai_base_url()).rstrip("/")

    async def _completion(self, schema_name: str, schema: dict, messages: list[dict]) -> dict:
        body = {
            "model": LLM_MODEL,
            "temperature": 0,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        try:
            response = await self.client.post(f"{self.base_url}/chat/completions", json=body)
            if response.status_code in {401, 403}:
                raise ProviderError("LLM_UNAUTHORIZED")
            if response.status_code == 429:
                raise ProviderError("LLM_RATE_LIMITED")
            if response.status_code != 200:
                raise ProviderError("LLM_UNAVAILABLE")
            payload = response.json()
        except httpx.TimeoutException:
            raise ProviderError("TIMEOUT") from None
        except httpx.HTTPError:
            raise ProviderError("LLM_UNAVAILABLE") from None
        except ValueError:
            raise ProviderError("LLM_INVALID_RESPONSE") from None
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if isinstance(usage, dict):
            logger.info(
                "OpenAI completion usage prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )
        try:
            return json.loads(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("LLM_INVALID_RESPONSE") from None

    async def name_cluster(self, question: str, papers: list[PaperBrief]) -> ClusterNaming:
        logger.info("OpenAI cluster naming papers=%s", len(papers))
        parsed = await self._completion(
            "subtopic", _NAMING_SCHEMA, cluster_naming_messages(question, papers)
        )
        try:
            return ClusterNaming.model_validate(parsed)
        except ValidationError:
            raise ProviderError("LLM_INVALID_RESPONSE") from None

    async def expand_queries(self, question: str, keywords: list[str]) -> QueryExpansion:
        logger.info("OpenAI query expansion")
        parsed = await self._completion(
            "query_expansion", _QUERY_SCHEMA, query_expansion_messages(question, keywords)
        )
        try:
            return QueryExpansion.model_validate(parsed)
        except ValidationError:
            raise ProviderError("LLM_INVALID_RESPONSE") from None

    async def explain_paper(self, question: str, subtopic: str, paper: PaperBrief) -> str:
        logger.info("OpenAI paper explanation")
        parsed = await self._completion(
            "explanation",
            _EXPLANATION_SCHEMA,
            paper_explanation_messages(question, subtopic, paper),
        )
        try:
            return PaperExplanation.model_validate(parsed).explanation
        except ValidationError:
            raise ProviderError("LLM_INVALID_RESPONSE") from None


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
