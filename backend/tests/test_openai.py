import asyncio
import json

import httpx
import pytest

from researchpilot.config import openai_headers
from researchpilot.llm import PaperBrief
from researchpilot.papers import ProviderError
from researchpilot.providers.openai import (
    DIMENSION,
    LLM_MODEL,
    MODEL,
    OpenAIEmbeddingProvider,
    OpenAILlmProvider,
)


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


def name_cluster(handler, question="How are LLMs used in software engineering?", papers=None):
    papers = papers or [
        PaperBrief(title="LLMs for test generation", abstract="We study unit tests.")
    ]

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await OpenAILlmProvider(client).name_cluster(question, papers)

    return asyncio.run(run())


def _completion(obj):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(obj)}}]})


def test_names_a_cluster_with_structured_output():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == LLM_MODEL
        assert body["temperature"] == 0
        assert body["response_format"]["type"] == "json_schema"
        assert "test generation" in body["messages"][-1]["content"]
        assert "software engineering" in body["messages"][-1]["content"]
        return _completion(
            {
                "name": "LLMs for Software Testing",
                "description": "Papers on using language models to generate and evaluate tests.",
                "keywords": ["testing", "test generation", "llm"],
            }
        )

    result = name_cluster(handler)
    assert result.name == "LLMs for Software Testing"
    assert result.description.startswith("Papers on using language models")
    assert result.keywords == ["testing", "test generation", "llm"]


def test_output_is_trimmed_and_deduped():
    result = name_cluster(
        lambda request: _completion(
            {
                "name": "  Very  " + "long " * 40 + "name",
                "description": "d " * 400,
                "keywords": ["  A ", "a", "b", "", "b", "c", "d", "e", "f", "g", "h", "i"],
            }
        )
    )
    assert len(result.name) <= 80
    assert len(result.description) <= 500
    assert result.keywords == ["A", "b", "c", "d", "e", "f", "g", "h"]


@pytest.mark.parametrize(
    "obj", [{"name": "  ", "description": "x", "keywords": []}, {"description": "x"}]
)
def test_missing_or_blank_name_is_rejected(obj):
    with pytest.raises(ProviderError) as error:
        name_cluster(lambda request: _completion(obj))
    assert error.value.code == "LLM_INVALID_RESPONSE"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "LLM_UNAUTHORIZED"),
        (403, "LLM_UNAUTHORIZED"),
        (429, "LLM_RATE_LIMITED"),
        (500, "LLM_UNAVAILABLE"),
        (503, "LLM_UNAVAILABLE"),
    ],
)
def test_llm_http_failures_map_to_safe_codes(status, code):
    with pytest.raises(ProviderError) as error:
        name_cluster(lambda request: httpx.Response(status, text="secret upstream body"))
    assert error.value.code == code
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}),
    ],
)
def test_malformed_llm_response_is_rejected(response):
    with pytest.raises(ProviderError) as error:
        name_cluster(lambda request: response)
    assert error.value.code == "LLM_INVALID_RESPONSE"


def test_llm_timeout_maps_to_unavailable():
    def handler(request):
        raise httpx.ReadTimeout("secret URL")

    with pytest.raises(ProviderError) as error:
        name_cluster(handler)
    assert error.value.code == "LLM_UNAVAILABLE"


def explain_paper(handler, question="How are LLMs used in software engineering?"):
    paper = PaperBrief(
        title="GPT-based unit test generation for Java", abstract="We generate JUnit tests."
    )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await OpenAILlmProvider(client).explain_paper(
                question, "LLMs for Software Testing", paper
            )

    return asyncio.run(run())


def test_explain_paper_returns_a_grounded_sentence():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == LLM_MODEL
        assert body["temperature"] == 0
        assert body["response_format"]["type"] == "json_schema"
        content = body["messages"][-1]["content"]
        assert "GPT-based unit test generation" in content
        assert "LLMs for Software Testing" in content
        return _completion(
            {"explanation": "  It evaluates GPT-generated JUnit tests, squarely test generation.  "}
        )

    assert (
        explain_paper(handler)
        == "It evaluates GPT-generated JUnit tests, squarely test generation."
    )


def test_explain_paper_truncates_and_rejects_blank():
    assert len(explain_paper(lambda r: _completion({"explanation": "word " * 200}))) <= 400
    with pytest.raises(ProviderError) as error:
        explain_paper(lambda r: _completion({"explanation": "   "}))
    assert error.value.code == "LLM_INVALID_RESPONSE"


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "LLM_UNAUTHORIZED"), (429, "LLM_RATE_LIMITED"), (500, "LLM_UNAVAILABLE")],
)
def test_explain_paper_http_failures_map_to_safe_codes(status, code):
    with pytest.raises(ProviderError) as error:
        explain_paper(lambda r: httpx.Response(status, text="secret upstream body"))
    assert error.value.code == code
    assert "secret" not in str(error.value)


def test_explain_paper_rejects_malformed_response():
    with pytest.raises(ProviderError) as error:
        explain_paper(lambda r: _completion({"wrong": "key"}))
    assert error.value.code == "LLM_INVALID_RESPONSE"
