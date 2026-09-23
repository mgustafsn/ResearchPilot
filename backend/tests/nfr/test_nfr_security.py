"""NFR-SEC-1..4 (docs/requirements.md §31): secrets stay server-side, input is inert."""

import logging

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine

from nfr_support import OPENAI_KEY, OPENALEX_KEY
from fakes import (
    WORK,
    grouped_papers,
    RecordingEmbeddingProvider,
    RecordingLlmProvider,
    RecordingProvider,
)
from live import live_browser
from researchpilot.api import create_app
from researchpilot.persistence import Base
from researchpilot.providers.openalex import normalize_work

pytestmark = pytest.mark.nfr
SECRETS = (OPENAI_KEY, OPENALEX_KEY)


def test_nfr_sec_1_api_keys_never_leave_the_server(real_adapter_app, caplog):
    app = real_adapter_app
    caplog.set_level(logging.DEBUG)
    client, url = app.client, app.url
    responses = [
        client.post(url + "/queries"),
        client.post(url + "/search"),
        client.get(url + "/papers"),
        client.get(url + "/subtopics"),
        client.get(url + "/searches"),
        client.get(url + "/queries"),
        client.get("/api/settings/status"),
        client.get(url.replace("/api/projects/", "/projects/")),
        client.get("/static/app.js"),
        client.get("/static/styles.css"),
    ]
    paper = next(p for p in client.get(url + "/papers").json() if p["clusterId"] is not None)
    responses.append(client.post(f"{url}/papers/{paper['id']}/explanation"))
    assert all(r.status_code < 400 for r in responses), [(r.url, r.status_code) for r in responses]
    # The keys really were used upstream...
    sent = " ".join(r.headers.get("authorization", "") for r in app.requests)  # repr masks it
    assert OPENAI_KEY in sent and OPENALEX_KEY in sent
    # ...but never reach a response, header or log line.
    for response in responses:
        exposed = response.text + " ".join(f"{k}:{v}" for k, v in response.headers.items())
        assert not any(secret in exposed for secret in SECRETS), response.url
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert not any(secret in logged for secret in SECRETS)


INJECTION = '<img src=x onerror="window.__xss=1">'


def _hostile_papers():
    hostile = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W8001",
            "doi": "https://doi.org/10.8000/hostile",
            "title": f"alpha {INJECTION} hostile title",
            "abstract_inverted_index": {"<script>window.__xss=1</script>": [0]},
        }
    )
    return [hostile, *grouped_papers()]


def test_nfr_sec_2_metadata_html_is_inert(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sec.db'}")
    Base.metadata.create_all(engine)
    provider = RecordingProvider()
    provider.papers = _hostile_papers()
    app = create_app(engine, provider, RecordingEmbeddingProvider(), RecordingLlmProvider())
    with live_browser(app) as (page, base):
        dialogs = []
        page.on("dialog", lambda dialog: (dialogs.append(dialog), dialog.dismiss()))
        project = page.request.post(
            base + "/api/projects", data={"title": "T", "researchQuestion": "q"}
        ).json()
        page.request.post(f"{base}/api/projects/{project['id']}/search")
        page.goto(f"{base}/projects/{project['id']}")
        row = page.locator(".paper-row").filter(has_text="hostile title")
        expect(row).to_contain_text(INJECTION)
        row.click()
        expect(page.locator(".drawer-panel")).to_contain_text(INJECTION)
        assert page.locator("img[src='x']").count() == 0
        assert page.evaluate("window.__xss") is None
        assert dialogs == []
    engine.dispose()


@pytest.mark.parametrize("field", ["doi", "landing_page_url", "oa_url"])
@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "data:text/html,<b>x</b>", "ftp://example.org/x"]
)
def test_nfr_sec_3_only_http_links_survive_normalization(field, url):
    work = dict(WORK)
    if field == "doi":
        work["doi"] = url
    elif field == "landing_page_url":
        work["primary_location"] = {**(WORK.get("primary_location") or {}), "landing_page_url": url}
    else:
        work["open_access"] = {**(WORK.get("open_access") or {}), "oa_url": url}
    paper = normalize_work(work)
    for value in (paper.doiUrl, paper.publicationUrl, paper.openAccessUrl, paper.sourceUrl):
        assert value is None or value.startswith(("http://", "https://"))


def test_nfr_sec_3_manual_reference_rejects_script_urls(search_client):
    client, _, url = search_client
    response = client.post(url + "/references", json={"title": "x", "url": "javascript:alert(1)"})
    assert response.status_code == 422


def test_nfr_sec_3_rendered_links_are_http_or_local(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'links.db'}")
    Base.metadata.create_all(engine)
    provider = RecordingProvider()
    provider.papers = grouped_papers()
    app = create_app(engine, provider, RecordingEmbeddingProvider(), RecordingLlmProvider())
    with live_browser(app) as (page, base):
        project = page.request.post(
            base + "/api/projects", data={"title": "T", "researchQuestion": "q"}
        ).json()
        page.request.post(f"{base}/api/projects/{project['id']}/search")
        page.goto(f"{base}/projects/{project['id']}")
        page.locator(".paper-row").first.click()
        expect(page.locator(".drawer-panel")).to_be_visible()
        hrefs = page.eval_on_selector_all(
            "a[href]", "links => links.map(a => a.getAttribute('href'))"
        )
        assert hrefs
        # "#content" is the static accessibility skip-link (frontend/index.html); a same-page
        # fragment has no scheme and cannot carry a javascript:/data: navigation, so it is not
        # the class of link SEC-3 guards against.
        assert all(h.startswith(("http://", "https://", "/", "#")) for h in hrefs), hrefs
    engine.dispose()


def _write_targets(client, url):
    papers = client.get(url + "/papers").json()
    query = client.post(url + "/queries/custom", json={"query": "valid query"}).json()
    reference = client.post(url + "/references", json={"title": "A reference"}).json()
    return papers[0]["id"], query["id"], reference["id"]


def test_nfr_sec_4_write_endpoints_reject_bad_input(search_client_named):
    client, provider, _, _, url = search_client_named
    provider.papers = grouped_papers()
    client.post(url + "/search")
    paper_id, query_id, reference_id = _write_targets(client, url)
    cases = [
        ("post", "/api/projects", {"title": "t", "researchQuestion": "q", "bogus": 1}),
        ("post", "/api/projects", {"title": "t", "researchQuestion": "q", "maxPaperCount": 0}),
        ("put", url, {"title": "", "researchQuestion": "q"}),
        ("post", url + "/subtopics", {"name": "n", "bogus": 1}),
        ("patch", url + "/subtopics/0", {"name": "x" * 81}),
        ("post", url + "/subtopics/0/merge", {"targetClusterId": -1}),
        ("patch", f"{url}/papers/{paper_id}", {"clusterId": -1}),
        ("patch", f"{url}/papers/{paper_id}", {"isRelevant": "yes"}),
        ("post", url + "/queries/custom", {"query": "x" * 161}),
        ("patch", f"{url}/queries/{query_id}", {}),
        ("post", url + "/references", {"title": "t", "bogus": 1}),
        ("patch", f"{url}/references/{reference_id}", {"number": 0}),
    ]
    for method, path, body in cases:
        response = getattr(client, method)(path, json=body)
        assert response.status_code == 422, (method, path, body, response.status_code)
