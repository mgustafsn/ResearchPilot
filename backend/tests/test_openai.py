import asyncio
import json

import httpx
import pytest

from researchpilot.config import openai_headers
from researchpilot.papers import ProviderError
from researchpilot.providers.openai import DIMENSION, MODEL, OpenAIEmbeddingProvider


def embed(handler, texts):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await OpenAIEmbeddingProvider(client).embed(texts)

    return asyncio.run(run())


def _vector(seed):
    return [float(seed)] * DIMENSION


def test_embeds_texts_and_requests_the_configured_model():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == MODEL
        assert body["dimensions"] == DIMENSION
        return httpx.Response(
            200,
            json={
                "data": [{"index": i, "embedding": _vector(i)} for i in range(len(body["input"]))]
            },
        )

    assert embed(handler, ["a", "b", "c"]) == [_vector(0), _vector(1), _vector(2)]


def test_batches_requests_and_restores_global_order():
    sizes = []

    def handler(request):
        body = json.loads(request.content)
        sizes.append(len(body["input"]))
        data = [
            {"index": i, "embedding": _vector(len(sizes) * 1000 + i)}
            for i in range(len(body["input"]))
        ]
        return httpx.Response(200, json={"data": list(reversed(data))})

    result = embed(handler, [f"t{i}" for i in range(300)])
    assert sizes == [256, 44]
    assert result[0] == _vector(1000)
    assert result[256] == _vector(2000)
    assert len(result) == 300


def test_empty_input_makes_no_request():
    calls = []
    assert embed(lambda request: calls.append(request) or httpx.Response(500), []) == []
    assert calls == []


def test_long_text_is_truncated_not_rejected():
    seen = []

    def handler(request):
        seen.append(len(json.loads(request.content)["input"][0]))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": _vector(0)}]})

    embed(handler, ["z" * 100_000])
    assert seen[0] <= 30_000


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "EMBEDDING_UNAUTHORIZED"),
        (403, "EMBEDDING_UNAUTHORIZED"),
        (429, "EMBEDDING_RATE_LIMITED"),
        (500, "EMBEDDING_UNAVAILABLE"),
        (503, "EMBEDDING_UNAVAILABLE"),
    ],
)
def test_http_failures_map_to_safe_codes(status, code):
    with pytest.raises(ProviderError) as error:
        embed(lambda request: httpx.Response(status, text="secret upstream body"), ["x"])
    assert error.value.code == code
    assert "secret" not in str(error.value)


def test_timeout_maps_to_unavailable():
    def handler(request):
        raise httpx.ReadTimeout("secret URL")

    with pytest.raises(ProviderError) as error:
        embed(handler, ["x"])
    assert error.value.code == "EMBEDDING_UNAVAILABLE"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": "x"},
        {"data": [{"index": 0}]},
        {"data": [{"index": 0, "embedding": [1.0]}]},
        {"data": [{"index": 0, "embedding": ["not-a-number"] * DIMENSION}]},
    ],
)
def test_malformed_response_is_rejected(payload):
    with pytest.raises(ProviderError) as error:
        embed(lambda request: httpx.Response(200, json=payload), ["x"])
    assert error.value.code == "EMBEDDING_INVALID_RESPONSE"


def test_invalid_json_is_rejected():
    with pytest.raises(ProviderError) as error:
        embed(lambda request: httpx.Response(200, text="<html>bad</html>"), ["x"])
    assert error.value.code == "EMBEDDING_INVALID_RESPONSE"


def test_api_key_uses_header(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    assert openai_headers()["Authorization"] == "Bearer sk-secret"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert "Authorization" not in openai_headers()
