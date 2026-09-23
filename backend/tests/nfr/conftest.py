import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from fakes import DATA, RecordingLlmProvider, RecordingProvider, grouped_papers
from live import live_browser
from nfr_support import SIX_GROUPS, SixGroupEmbeddingProvider
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
