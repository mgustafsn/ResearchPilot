"""Real Chromium against the app with deterministic, local providers."""

import asyncio
import re
import threading

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine

from fakes import (
    DATA,
    RecordingEmbeddingProvider,
    RecordingLlmProvider,
    RecordingProvider,
    _grouped_papers,
)
from live import live_browser
from researchpilot.api import create_app
from researchpilot.persistence import Base


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
    with live_browser(app) as (page, base):
        project = page.request.post(base + "/api/projects", data=DATA).json()
        url = base + "/api/projects/" + project["id"]
        page.goto(base + "/projects/" + project["id"])
        yield page, url, gate, embedder, llm
        gate.set()
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
    expect(page.locator(".search-status")).to_have_text("Embedding papers and scoring relevance…")
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
    page.locator(".subtopic-menu summary").click()
    expect(page.get_by_role("button", name="Rename subtopic")).to_be_enabled()
    page.get_by_role("button", name="Open access only", exact=True).click()
    # The selected subtopic survives re-renders, so return to All explicitly.
    page.locator(".cluster-tab").first.click()
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


def test_settings_and_project_references(browser_app):
    page, url, _, _, _ = browser_app
    page.goto(page.url.split("/projects/")[0] + "/settings")
    expect(page.get_by_role("heading", name="Settings")).to_be_visible()
    expect(page.locator(".settings-active-name")).to_have_text("Test scholarly provider")
    expect(page.get_by_role("heading", name="Research assistance")).to_be_visible()
    expect(page.get_by_role("heading", name="How to configure")).to_be_visible()
    page.goto(page.url.replace("/settings", "/projects/" + url.rsplit("/", 1)[-1]))
    page.get_by_role("button", name="References", exact=True).click()
    page.get_by_role("button", name="Add reference").click()
    page.locator('.reference-form [name="title"]').fill("My draft paper")
    page.locator('.reference-form [name="authors"]').fill("A. Researcher\nB. Researcher")
    page.get_by_role("button", name="Save reference").click()
    expect(page.locator(".reference-row")).to_contain_text("My draft paper")
    page.get_by_role("button", name="Overview").click()
    page.get_by_role("button", name="Find papers", exact=True).click()
    expect(page.locator(".paper-row")).to_have_count(15)
    page.locator(".paper-row .card-save").first.click()
    page.get_by_role("button", name="References", exact=True).click()
    expect(page.locator(".reference-row")).to_have_count(2)


def test_settings_shows_provider_configuration_without_credentials(browser_app):
    page, url, _, _, _ = browser_app
    page.route(
        "**/api/settings/status",
        lambda route: route.fulfill(
            json={
                "scholarlyProvider": "Scopus",
                "openAlexApiKeyConfigured": False,
                "openAlexEmailConfigured": False,
                "elsevierApiKeyConfigured": True,
                "llmProvider": "OpenAI",
                "openAiApiKeyConfigured": False,
                "customOpenAiEndpointConfigured": False,
            }
        ),
    )
    page.goto(url.split("/api/projects/")[0] + "/settings")
    expect(page.locator(".settings-active-name")).to_have_text("Scopus")
    expect(page.locator(".settings-service-row").filter(has_text="Scopus")).to_contain_text(
        "In use"
    )
    expect(
        page.locator(".settings-service-row").filter(
            has=page.get_by_role("heading", name="OpenAI", exact=True)
        )
    ).to_contain_text("Needs setup")
    expect(page.locator(".settings-service-row").filter(has_text="OpenAlex")).to_contain_text(
        "No API key needed"
    )
    expect(page.get_by_text("ELSEVIER_API_KEY", exact=True)).to_be_visible()
    expect(page.get_by_text("Statuses show configuration only", exact=False)).to_be_visible()


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
    expect(page.locator(".search-status")).to_have_text("Embedding papers and scoring relevance…")
    assert len(calls) >= 3
    expect(page.get_by_role("button", name="Searching papers…", exact=True)).to_be_disabled()
    gate.set()
    expect(page.get_by_role("button", name="Find papers", exact=True)).to_be_enabled()


def test_query_editor_and_description_label(browser_app):
    page, url, _, _, llm = browser_app
    page.locator(".project-details > summary").click()
    expect(page.get_by_text("Research description", exact=True)).to_be_visible()
    page.get_by_placeholder("Add a search query").fill("terraform provisioning")
    page.get_by_role("button", name="Add", exact=True).click()
    row = page.locator(".query-option").filter(
        has=page.locator("input[value='terraform provisioning']")
    )
    expect(row.locator(".query-tag")).to_have_text("Yours")
    row.get_by_role("checkbox").uncheck()
    expect(page.get_by_text("Enable at least one search query.")).to_be_visible()
    expect(page.get_by_role("button", name="Find papers", exact=True)).to_be_disabled()
    row.get_by_role("checkbox").check()
    expect(page.get_by_role("button", name="Find papers", exact=True)).to_be_enabled()
    queries = page.request.get(url + "/queries").json()
    assert [(q["query"], q["enabled"]) for q in queries] == [("terraform provisioning", True)]


def test_selected_subtopic_survives_a_refresh(browser_app):
    page, url, _, _, _ = browser_app
    page.request.post(url + "/search")
    page.reload()
    tab = page.locator(".cluster-tab").nth(1)
    tab.click()
    expect(page.locator(".subtopic-menu summary")).to_be_visible()
    # Any full re-render (reference saves, polling, edits) must keep the chosen subtopic.
    previous = page.locator(".paper-list").element_handle()
    page.evaluate("window.dispatchEvent(new Event('references-changed'))")
    page.wait_for_function("list => !list.isConnected", arg=previous)
    expect(page.locator(".cluster-tab").nth(1)).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator(".subtopic-menu summary")).to_be_visible()


def test_papers_can_be_sorted_across_tabs_and_refreshes(browser_app):
    page, url, _, _, _ = browser_app
    page.request.post(url + "/search")
    original = page.request.get(url + "/papers").json()
    assert len(original) == 15

    def add_sort_values(route):
        response = route.fetch()
        papers = response.json()
        for index, paper in enumerate(papers):
            paper["citationCount"] = index * 10
            paper["publicationYear"] = 2000 + index
            paper["publicationDate"] = f"{2000 + index}-01-01"
        route.fulfill(response=response, json=papers)

    page.route("**/papers", add_sort_values)
    page.reload()
    sort = page.get_by_label("Sort papers")
    titles = page.locator(".paper-list .paper-row h3")
    expect(page.locator(".paper-results-heading h3")).to_have_text("All papers")
    sort.select_option("citations")
    expect(titles.first).to_have_text(original[-1]["title"])
    first_group = [paper for paper in original if paper["clusterId"] == original[0]["clusterId"]]
    page.locator(".cluster-tab").nth(1).click()
    expect(page.locator(".paper-results-count")).to_have_text(f"{len(first_group)} results")
    expect(titles.first).to_have_text(first_group[-1]["title"])
    page.get_by_role("button", name="Open access only", exact=True).click()
    expect(sort).to_have_value("citations")
    page.locator(".cluster-tab").first.click()
    page.get_by_role("button", name="Open access only", exact=True).click()
    sort.select_option("newest")
    expect(titles.first).to_have_text(original[-1]["title"])
    sort.select_option("oldest")
    expect(titles.first).to_have_text(original[0]["title"])
    sort.select_option("relevance")
    expect(titles.first).to_have_text(original[0]["title"])
    sort.select_option("title")
    assert titles.all_text_contents() == sorted(titles.all_text_contents(), key=str.casefold)


def test_reference_reading_workflow(browser_app):
    page, url, _, _, _ = browser_app
    page.get_by_role("button", name="References", exact=True).click()
    expect(page.get_by_text("No references yet.", exact=False)).to_be_visible()
    for title in ["First paper", "Second paper"]:
        page.request.post(url + "/references", data={"title": title})
    page.reload()
    page.get_by_role("button", name="References", exact=True).click()
    rows = page.locator(".reference-row")
    status = rows.first.get_by_label("Reading status", exact=True)
    status.select_option("READING")
    expect(status).to_be_enabled()
    expect(status).to_have_value("READING")
    status.select_option("READ")
    expect(status).to_be_enabled()
    filter_control = page.get_by_label("Filter by reading status")
    filter_control.select_option("READ")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("First paper")
    expect(page.get_by_role("heading", name="Saved references (1 of 2)")).to_be_visible()
    page.get_by_role("button", name="Overview", exact=True).click()
    page.get_by_role("button", name="References", exact=True).click()
    expect(filter_control).to_have_value("READ")
    page.get_by_role("button", name="Add reference", exact=True).click()
    expect(page.get_by_label("Title", exact=True)).to_have_value("")
    expect(page.get_by_label("Publication status", exact=True)).to_have_value("Draft")
    page.get_by_label("Title", exact=True).fill("Third paper")
    page.get_by_role("button", name="Save reference", exact=True).click()
    expect(page.get_by_role("heading", name="Saved references (1 of 3)")).to_be_visible()
    expect(filter_control).to_have_value("READ")
    rows.first.get_by_label("Reading status", exact=True).select_option("READING")
    expect(rows).to_have_count(0)
    expect(page.get_by_text("No references match these filters.")).to_be_visible()
    page.reload()
    page.get_by_role("button", name="References", exact=True).click()
    expect(filter_control).to_have_value("ALL")
    expect(rows).to_have_count(3)
    expect(status).to_have_value("READING")

    def reject(route):
        route.fulfill(status=503, json={"detail": "Reading update unavailable"})

    page.route("**/references/*", reject)
    status.select_option("READ")
    expect(status).to_be_enabled()
    expect(status).to_have_value("READING")
    expect(page.get_by_text("Reading update unavailable", exact=True)).to_be_visible()


def test_reference_citation_controls_filters_and_restore_conflict(browser_app):
    page, url, _, _, _ = browser_app
    first = page.request.post(
        url + "/references",
        data={
            "title": "Alpha methods",
            "year": 2024,
            "notes": "Important baseline",
            "isCited": True,
            "citationNumber": 3,
        },
    ).json()
    second = page.request.post(
        url + "/references", data={"title": "Beta findings", "year": 2023}
    ).json()
    page.reload()
    page.get_by_role("button", name="References", exact=True).click()
    expect(page.get_by_role("heading", name="Reference library")).to_be_visible()
    rows = page.locator(".reference-row")
    expect(rows).to_have_count(2)
    assert rows.locator("h3").all_text_contents() == ["Alpha methods", "Beta findings"]

    page.get_by_label("Filter by citation status").select_option("CITED")
    expect(rows).to_have_count(1)
    page.get_by_label("Filter by reading status").select_option("TO_READ")
    page.get_by_label("Search library").fill("baseline")
    page.locator(".reference-library-year input").fill("2024")
    expect(rows).to_have_count(1)
    page.get_by_label("Search library").fill("")
    page.locator(".reference-library-year input").fill("")
    page.get_by_label("Filter by citation status").select_option("ALL")

    alpha = rows.filter(has_text="Alpha methods")
    cited = alpha.get_by_label("Cited in paper")
    cited.focus()
    cited.press("Space")
    expect(alpha.get_by_text("Previously cited as 3")).to_be_visible()
    page.request.patch(
        url + "/references/" + second["id"], data={"isCited": True, "citationNumber": 3}
    )
    alpha.get_by_role("button", name="Restore number").click()
    expect(alpha.get_by_label("Cited in paper")).to_be_checked()
    expect(alpha.get_by_label("Citation number (optional)")).to_have_value("")
    expect(alpha.get_by_text("Number not restored:", exact=False)).to_be_visible()
    stored = page.request.get(url + "/references").json()
    restored = next(item for item in stored if item["id"] == first["id"])
    assert restored["isCited"] is True
    assert restored["citationNumber"] is None
    assert restored["previousCitationNumber"] == 3


def test_reference_notes_editor_keeps_drafts_and_saves(browser_app):
    page, url, _, _, _ = browser_app
    page.request.post(url + "/references", data={"title": "Alpha methods", "notes": "Old note"})
    page.request.post(url + "/search")
    paper = page.request.get(url + "/papers").json()[0]
    page.request.post(url + "/references/from-paper/" + paper["id"])
    page.reload()
    page.get_by_role("button", name="References", exact=True).click()
    rows = page.locator(".reference-row")
    alpha = rows.filter(has_text="Alpha methods")
    patches = []
    page.on("request", lambda r: patches.append(r.url) if r.method == "PATCH" else None)

    alpha.get_by_role("button", name="Edit notes").click()
    notes = alpha.get_by_label("Notes", exact=True)
    expect(notes).to_have_value("Old note")
    expect(notes).to_have_attribute("maxlength", "5000")
    notes.fill("Draft text")
    expect(alpha.get_by_text("10 / 5000")).to_be_visible()
    expect(alpha.get_by_text("Unsaved changes")).to_be_visible()
    alpha.get_by_role("button", name="Cancel", exact=True).click()
    expect(alpha.get_by_label("Notes", exact=True)).to_have_count(0)
    expect(alpha.locator(".reference-notes")).to_have_text("Old note")
    assert patches == []

    alpha.get_by_role("button", name="Edit notes").click()
    notes.fill("Line one\nLine two")
    page.get_by_label("Search library").fill("no such reference")
    expect(alpha).to_have_count(0)
    page.get_by_label("Search library").fill("")
    expect(notes).to_have_value("Line one\nLine two")
    page.get_by_role("button", name="Overview", exact=True).click()
    page.get_by_role("button", name="References", exact=True).click()
    alpha.get_by_label("Reading status", exact=True).select_option("READING")
    expect(alpha.get_by_label("Reading status", exact=True)).to_be_enabled()
    page.evaluate("window.dispatchEvent(new Event('references-changed'))")
    expect(notes).to_have_value("Line one\nLine two")
    notes.focus()
    page.evaluate("window.dispatchEvent(new Event('references-changed'))")
    expect(notes).to_be_focused()
    assert page.evaluate(
        "(() => { const e = new Event('beforeunload', {cancelable: true});"
        " window.dispatchEvent(e); return e.defaultPrevented; })()"
    )

    def reject(route):
        route.fulfill(status=503, json={"detail": "Notes unavailable"})

    page.route("**/references/*", reject)
    alpha.get_by_role("button", name="Save notes").click()
    expect(alpha.get_by_text("Not saved: Notes unavailable")).to_be_visible()
    expect(notes).to_have_value("Line one\nLine two")
    page.unroute("**/references/*", reject)
    alpha.get_by_role("button", name="Save notes").click()
    expect(page.locator(".reference-toolbar [role=status]")).to_have_text("Notes saved")
    expect(alpha.get_by_label("Notes", exact=True)).to_have_count(0)
    expect(alpha.locator(".reference-notes")).to_have_css("white-space", "pre-wrap")
    assert not page.evaluate(
        "(() => { const e = new Event('beforeunload', {cancelable: true});"
        " window.dispatchEvent(e); return e.defaultPrevented; })()"
    )
    stored = page.request.get(url + "/references").json()
    assert next(r for r in stored if r["title"] == "Alpha methods")["notes"] == (
        "Line one\nLine two"
    )
    assert next(r for r in stored if r["title"] == "Alpha methods")["readingStatus"] == "READING"

    provider_row = rows.filter(has_text=paper["title"])
    expect(provider_row.get_by_role("button", name="Edit", exact=True)).to_have_count(0)
    provider_row.get_by_role("button", name="Add notes").click()
    provider_row.get_by_label("Notes", exact=True).fill("<img src=x onerror=window.pwned=1>")
    provider_row.get_by_role("button", name="Save notes").click()
    expect(provider_row.locator(".reference-notes")).to_have_text(
        "<img src=x onerror=window.pwned=1>"
    )
    assert page.evaluate("window.pwned === undefined")
    page.reload()
    page.get_by_role("button", name="References", exact=True).click()
    expect(provider_row.get_by_role("button", name="Edit notes")).to_be_visible()


def test_reference_metadata_form_and_remove_respect_notes(browser_app):
    page, url, _, _, _ = browser_app
    reference = page.request.post(
        url + "/references", data={"title": "Alpha methods", "notes": "First note"}
    ).json()
    page.reload()
    page.get_by_role("button", name="References", exact=True).click()
    row = page.locator(".reference-row").filter(has_text="Alpha")
    row.get_by_role("button", name="Edit", exact=True).click()
    expect(page.locator(".reference-form").get_by_label("Notes", exact=True)).to_be_hidden()
    page.request.patch(url + "/references/" + reference["id"], data={"notes": "Newer note"})
    page.get_by_label("Title", exact=True).fill("Alpha methods revised")
    page.get_by_role("button", name="Save reference", exact=True).click()
    expect(row.locator("h3")).to_have_text("Alpha methods revised")
    expect(row.locator(".reference-notes")).to_have_text("Newer note")

    page.get_by_role("button", name="Add reference", exact=True).click()
    expect(page.locator(".reference-form").get_by_label("Notes", exact=True)).to_be_visible()
    page.get_by_role("button", name="Cancel", exact=True).click()

    row.get_by_role("button", name="Edit notes").click()
    row.get_by_label("Notes", exact=True).fill("Unsaved thought")
    messages = []

    def answer(dialog):
        messages.append(dialog.message)
        dialog.dismiss() if len(messages) == 1 else dialog.accept()

    page.on("dialog", answer)
    row.get_by_role("button", name="Remove").click()
    expect(row.get_by_label("Notes", exact=True)).to_have_value("Unsaved thought")
    assert "unsaved notes" in messages[0]
    row.get_by_role("button", name="Remove").click()
    expect(page.locator(".reference-row")).to_have_count(0)
    assert not page.evaluate(
        "(() => { const e = new Event('beforeunload', {cancelable: true});"
        " window.dispatchEvent(e); return e.defaultPrevented; })()"
    )


def test_page_stylesheet_loads(browser_app):
    page, _, _, _, _ = browser_app
    expect(page.locator(".brand-mark")).to_have_css("width", "40px")
    expect(page.locator("body")).to_have_css("margin", "0px")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_search_disclosure_preserves_choice_and_exposes_progress(browser_app):
    page, url, gate, embedder, _ = browser_app
    disclosure = page.locator(".search-disclosure")
    expect(page.get_by_placeholder("Add a search query")).to_be_visible()
    page.get_by_role("button", name="Find papers", exact=True).click()
    expect(page.locator(".paper-row")).to_have_count(15)
    page.reload()
    expect(page.locator(".paper-row")).to_have_count(15)
    expect(disclosure).not_to_have_attribute("open", "")
    gate.clear()
    embedder.model = "visual-refresh-test"
    page.get_by_role("button", name="Find papers", exact=True).click()
    expect(page.locator(".search-notice .search-status")).to_have_text(
        "Embedding papers and scoring relevance…"
    )
    expect(disclosure).not_to_have_attribute("open", "")
    disclosure.locator("summary").first.click()
    expect(page.get_by_placeholder("Add a search query")).to_be_visible()
    gate.set()
    expect(page.get_by_role("button", name="Find papers", exact=True)).to_be_enabled()
    expect(disclosure).to_have_attribute("open", "")
    checkbox = page.locator(".query-option input[type=checkbox]").first
    checkbox.uncheck()
    expect(page.get_by_text("Enable at least one search query.")).to_be_visible()
    disclosure.locator("summary").first.click()
    expect(page.get_by_text("Enable at least one search query.")).to_be_visible()


def test_failed_search_notice_visible_with_configuration_closed(browser_app):
    page, url, _, _, _ = browser_app
    page.request.post(url + "/search")
    page.reload()
    expect(page.locator(".paper-row")).to_have_count(15)
    history = page.request.get(url + "/searches").json()
    history.insert(
        0,
        {
            **history[0],
            "id": "failed-visual-run",
            "status": "FAILED",
            "errorMessage": "Search provider unavailable.",
        },
    )
    page.route("**/searches", lambda route: route.fulfill(json=history))
    page.reload()
    expect(page.locator(".search-disclosure")).not_to_have_attribute("open", "")
    expect(page.get_by_text("Search provider unavailable.", exact=True)).to_be_visible()
    expect(
        page.get_by_text("Results from your last successful search are still available.")
    ).to_be_visible()
    expect(page.locator(".paper-row")).to_have_count(15)


def test_manual_edit_confirmation_visible_with_search_closed(browser_app):
    page, url, _, _, _ = browser_app
    page.request.post(url + "/search")
    paper = page.request.get(url + "/papers").json()[0]
    page.request.patch(url + "/papers/" + paper["id"], data={"isRelevant": False})
    page.reload()
    expect(page.locator(".paper-row")).to_have_count(14)
    page.get_by_role("button", name="Find papers", exact=True).click()
    expect(page.get_by_role("button", name="Run anyway")).to_be_visible()
    expect(page.locator(".search-disclosure")).not_to_have_attribute("open", "")
    page.get_by_role("button", name="Run anyway").click()
    expect(page.locator(".paper-row")).to_have_count(15)


def test_settings_marks_every_configured_source_in_use(browser_app):
    page, url, _, _, _ = browser_app
    page.route(
        "**/api/settings/status",
        lambda route: route.fulfill(
            json={
                "scholarlyProvider": "OpenAlex+Scopus",
                "scholarlyProviders": ["OpenAlex", "Scopus"],
                "openAlexApiKeyConfigured": False,
                "openAlexEmailConfigured": False,
                "elsevierApiKeyConfigured": True,
                "llmProvider": "OpenAI",
                "openAiApiKeyConfigured": False,
                "customOpenAiEndpointConfigured": False,
            }
        ),
    )
    page.goto(url.split("/api/projects/")[0] + "/settings")
    expect(page.locator(".settings-active-name")).to_have_text("OpenAlex + Scopus")
    for name in ("OpenAlex", "Scopus"):
        expect(page.locator(".settings-service-row").filter(has_text=name)).to_contain_text(
            "In use"
        )


def test_failed_source_warning(browser_app):
    page, url, _, _, _ = browser_app
    page.request.post(url + "/search")

    def with_failed_source(route):
        response = route.fetch()
        runs = response.json()
        runs[0] |= {"provider": "OpenAlex+Scopus", "failedSources": ["Scopus"]}
        route.fulfill(response=response, json=runs)

    page.route("**/searches", with_failed_source)
    page.reload()
    expect(
        page.get_by_text(
            "Scopus was unavailable for one or more queries; results may be incomplete."
        )
    ).to_be_visible()


def test_failed_source_warning_when_every_source_failed_somewhere(browser_app):
    # Each source failed on a different query, so both appear and no "only" claim is made.
    page, url, _, _, _ = browser_app
    page.request.post(url + "/search")

    def with_failed_sources(route):
        response = route.fetch()
        runs = response.json()
        runs[0] |= {"provider": "OpenAlex+Scopus", "failedSources": ["OpenAlex", "Scopus"]}
        route.fulfill(response=response, json=runs)

    page.route("**/searches", with_failed_sources)
    page.reload()
    expect(
        page.get_by_text(
            "OpenAlex and Scopus were unavailable for one or more queries; "
            "results may be incomplete."
        )
    ).to_be_visible()
    expect(page.get_by_text("only.", exact=False)).to_have_count(0)


def test_no_failed_source_warning_by_default(browser_app):
    page, url, _, _, _ = browser_app
    page.request.post(url + "/search")
    page.reload()
    expect(page.locator(".paper-row").first).to_be_visible()
    expect(page.get_by_text("was unavailable", exact=False)).to_have_count(0)
