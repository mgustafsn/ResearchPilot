import json as jsonlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from fakes import DATA, WORK, RecordingLlmProvider, RecordingProvider, grouped_papers
from live import live_browser
from nfr_support import OPENAI_KEY, OPENALEX_KEY, SIX_GROUPS, SixGroupEmbeddingProvider
from researchpilot.api import create_app
from researchpilot.persistence import Base

LARGE = {**DATA, "maxPaperCount": 252}


def _large_app(engine):
    provider = RecordingProvider()
    provider.papers = grouped_papers(SIX_GROUPS, per_group=42)
    return create_app(engine, provider, SixGroupEmbeddingProvider(), RecordingLlmProvider())


@pytest.fixture
def large_api(engine):
    with TestClient(_large_app(engine)) as client:
        project = client.post("/api/projects", json=LARGE).json()
        url = f"/api/projects/{project['id']}"
        run = client.post(url + "/search").json()
        assert run["status"] == "COMPLETED" and run["paperCount"] == 252, run
        yield client, url


@pytest.fixture
def large_browser(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'large.db'}")
    Base.metadata.create_all(engine)
    with live_browser(_large_app(engine), viewport={"width": 1400, "height": 1000}) as (page, base):
        project = page.request.post(base + "/api/projects", data=LARGE).json()
        run = page.request.post(f"{base}/api/projects/{project['id']}/search").json()
        assert run["status"] == "COMPLETED" and run["paperCount"] == 252, run
        yield page, base, project["id"]
    engine.dispose()


def _works(count=12):
    groups = ("alpha", "bravo", "charlie")
    return [
        WORK
        | {
            "id": f"https://openalex.org/W{7000 + n}",
            "doi": f"https://doi.org/10.7000/{groups[n % 3]}-{n}",
            "title": f"{groups[n % 3]} study {n} of large language models",
        }
        for n in range(count)
    ]


def _vector(text):
    vector = [0.0] * 512
    for index, marker in enumerate(("alpha", "bravo", "charlie")):
        if marker in text:
            vector[index] = 1.0
    vector[511] = 1.0
    return vector


@pytest.fixture
def real_adapter_app(engine, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    monkeypatch.setenv("OPENALEX_API_KEY", OPENALEX_KEY)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    requests, fail = [], {}

    def handler(request):
        requests.append(request)
        if request.url.host == "api.openalex.org":
            if "openalex" in fail:
                status, body = fail["openalex"]
                return httpx.Response(status, text=body)
            return httpx.Response(
                200, json={"results": _works(), "meta": {"count": 12, "next_cursor": None}}
            )
        body = jsonlib.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            data = [{"index": i, "embedding": _vector(t)} for i, t in enumerate(body["input"])]
            return httpx.Response(200, json={"data": data})
        schema = body["response_format"]["json_schema"]["name"]
        content = {
            "query_expansion": {"queries": ["llm code generation", "llm software testing"]},
            "subtopic": {"name": "Named topic", "description": "A topic.", "keywords": ["llm"]},
            "explanation": {"explanation": "It studies language models."},
        }[schema]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": jsonlib.dumps(content)}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    real_client = httpx.AsyncClient

    def mocked_client(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mocked_client)
    with TestClient(create_app(engine)) as client:
        created = client.post("/api/projects", json=DATA)
        project = created.json()
        yield SimpleNamespace(
            client=client,
            url=f"/api/projects/{project['id']}",
            requests=requests,
            fail=fail,
            created=created,
        )
