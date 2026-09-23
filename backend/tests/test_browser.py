"""Real Chromium against the app with deterministic, local providers."""

import asyncio
import socket
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import sync_playwright, expect
from sqlalchemy import create_engine

from researchpilot.api import create_app
from researchpilot.persistence import Base
from test_search import (
    DATA,
    RecordingProvider,
    RecordingEmbeddingProvider,
    RecordingLlmProvider,
    _grouped_papers,
)


@pytest.fixture
def browser_app(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'browser.db'}")
    Base.metadata.create_all(engine)
    provider = RecordingProvider()
    provider.papers = _grouped_papers()
    embedder = RecordingEmbeddingProvider()
    llm = RecordingLlmProvider()
    gate = threading.Event()
    gate.set()
    original = embedder.embed

    async def embed(texts):
        while not gate.is_set():
            await asyncio.sleep(0.01)
        return await original(texts)

    embedder.embed = embed
    app = create_app(engine, provider, embedder, llm)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        project = page.request.post(base + "/api/projects", data=DATA).json()
        url = base + "/api/projects/" + project["id"]
        page.goto(base + "/projects/" + project["id"])
        yield page, url, gate, embedder, llm
        gate.set()
        browser.close()
    server.should_exit = True
    thread.join(timeout=5)
    sock.close()
    engine.dispose()


def test_progress_and_locked_open_drawer(browser_app):
    page, url, gate, embedder, _ = browser_app
    page.get_by_role("button", name="Find papers", exact=True).click()
    expect(page.locator(".paper-row")).to_have_count(15)
    page.locator(".paper-row").first.click()
    expect(page.locator(".drawer-organize select")).to_be_enabled()
    gate.clear()
    embedder.model = "force-new-vectors"
    # Keep drawer open while exercising the search action underneath it.
    page.get_by_role("button", name="Find papers", exact=True).evaluate(
        "(button) => button.click()"
    )
    expect(page.locator(".drawer-organize select")).to_be_disabled()
    expect(page.get_by_role("button", name="Set aside as irrelevant")).to_be_disabled()
    expect(page.locator(".search-status")).to_have_text("Generating paper embeddings…")
    gate.set()
    expect(page.get_by_role("button", name="Find papers", exact=True)).to_be_enabled()


def test_empty_categories_filters_uncategorized_and_retry(browser_app):
    from researchpilot.papers import ProviderError

    page, url, _, _, llm = browser_app
    page.request.post(url + "/search")
    papers = page.request.get(url + "/papers").json()
    topics = page.request.get(url + "/subtopics").json()
    empty = topics[0]
    for paper in papers:
        if paper["clusterId"] == empty["clusterId"]:
            page.request.patch(url + "/papers/" + paper["id"], data={"clusterId": None})
    page.reload()
    page.get_by_role("button", name="Open access only", exact=True).click()
    tab = page.locator(".cluster-tab").filter(has_text=empty["name"])
    expect(tab).to_be_visible()
    tab.click()
    expect(page.get_by_role("button", name="Rename subtopic")).to_be_enabled()
    page.get_by_role("button", name="Open access only", exact=True).click()
    page.locator(".paper-row").first.click()
    options = page.locator(".drawer-organize select option")
    assert "Uncategorized" in options.all_text_contents()
    assert empty["name"] in options.all_text_contents()
    page.locator(".drawer-organize select").select_option(str(empty["clusterId"]))
    expect(page.locator(".cluster-tab").filter(has_text=empty["name"])).to_contain_text("1")
    llm.explain_error = ProviderError("TIMEOUT")
    page.locator(".paper-row").first.click()
    expect(page.get_by_role("button", name="Retry", exact=True)).to_be_visible()
    llm.explain_error = None
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_role("button", name="Retry", exact=True)).to_have_count(0)
    expect(page.locator(".drawer-panel")).to_contain_text("fits Topic")


def test_pending_request_survives_early_history_and_poll_failure(browser_app):
    page, url, gate, _, _ = browser_app
    gate.clear()
    calls = []

    def history(route):
        calls.append(1)
        if len(calls) == 1:
            route.fulfill(json=[])
        elif len(calls) == 2:
            route.fulfill(status=503, json={"detail": "Transient failure"})
        else:
            route.continue_()

    page.route("**/searches", history)
    page.get_by_role("button", name="Find papers", exact=True).click()
    expect(page.locator(".search-status")).to_have_text("Generating paper embeddings…")
    assert len(calls) >= 3
    expect(page.get_by_role("button", name="Searching OpenAlex…", exact=True)).to_be_disabled()
    gate.set()
    expect(page.get_by_role("button", name="Find papers", exact=True)).to_be_enabled()
