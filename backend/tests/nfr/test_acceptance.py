"""ACC-38 (docs/requirements.md §38): the MVP scenario, end to end in a real browser."""

import re

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine

from fakes import WORK, RecordingEmbeddingProvider, RecordingLlmProvider, RecordingProvider
from live import live_browser
from researchpilot.api import create_app
from researchpilot.persistence import Base
from researchpilot.providers.openalex import normalize_work

pytestmark = pytest.mark.nfr
GROUPS = ("alpha", "bravo", "charlie")


def _corpus():
    # 40 on-topic papers split evenly across three groups (14/13/13), one duplicate of
    # the first alpha paper (same DOI, different title/id), and three off-topic papers.
    papers = [
        normalize_work(
            WORK
            | {
                "id": f"https://openalex.org/W{9000 + n}",
                "doi": f"https://doi.org/10.9000/{GROUPS[n % 3]}-{n}",
                "title": f"{GROUPS[n % 3]} study {n} of large language models in software engineering",
            }
        )
        for n in range(40)
    ]
    duplicate = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W9999",
            "doi": "https://doi.org/10.9000/alpha-0",
            "title": "alpha study 0 duplicate record",
        }
    )
    off_topic = [
        normalize_work(
            WORK
            | {
                "id": f"https://openalex.org/W{9900 + n}",
                "doi": f"https://doi.org/10.9900/m-{n}",
                "title": f"marine biology survey {n}",
            }
        )
        for n in range(3)
    ]
    return [*papers, duplicate, *off_topic]


def test_acc_38_mvp_scenario(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'acc.db'}")
    Base.metadata.create_all(engine)
    provider, llm = RecordingProvider(), RecordingLlmProvider()
    provider.papers = _corpus()
    llm.expansion = ["llm code generation", "llm software testing"]
    titles = {p.title for p in provider.papers}
    app = create_app(engine, provider, RecordingEmbeddingProvider(), llm)
    with live_browser(app, viewport={"width": 1400, "height": 1000}) as (page, base):
        # Steps 1-2: the user creates a project and enters a research description.
        page.goto(base + "/projects/new")
        page.get_by_label("Project title").fill("LLMs in SE")
        page.get_by_label("Research description").fill(
            "Large language models in software engineering"
        )
        page.get_by_label(re.compile("^Keywords")).fill("software engineering")
        page.get_by_role("button", name=re.compile("Create project|Save project")).click()
        expect(page).to_have_url(re.compile(r"/projects/[0-9a-f-]{36}$"))

        # Step 3: the backend generates short search queries from the description.
        page.get_by_role("button", name="Find papers", exact=True).click()
        expect(page.locator(".generated-queries li")).to_have_count(2, timeout=15_000)
        expect(page.locator(".generated-queries")).to_contain_text("llm code generation")
        # Steps 5-8: several dozen papers are retrieved, duplicates are removed, papers
        # receive relevance scores, and irrelevant papers are filtered before clustering.
        expect(
            page.get_by_text(re.compile(r"duplicate records? (was|were) merged"))
        ).to_be_visible()
        expect(
            page.get_by_text(re.compile(r"low-relevance papers? (was|were) filtered"))
        ).to_be_visible()
        rows = page.locator(".paper-row")
        expect(rows).to_have_count(40)  # 40 on-topic survivors: >= "several dozen" (>= 36)
        # Step 4: a scholarly API (the fake PaperProvider standing in for the real one) is
        # queried once per generated query. Checked once the row count has settled so it
        # can't race the polling render.
        assert len(provider.calls) == 2
        expect(rows.first).to_contain_text(re.compile(r"Relevance: \d+%"))

        # Steps 9-11: remaining papers are clustered by embeddings, the LLM names each
        # cluster, and the Research Map (cluster tabs) shows the named subtopics.
        tabs = page.locator(".cluster-tab")
        expect(tabs.filter(has_text="Topic alpha")).to_have_count(1)
        # Step 12: papers appear underneath their subtopic.
        tabs.filter(has_text="Topic alpha").click()
        expect(rows.first).to_contain_text("alpha")

        # Step 13: clicking a paper displays its metadata and abstract.
        rows.first.click()
        drawer = page.locator(".drawer-panel")
        expect(drawer).to_be_visible()
        expect(drawer).to_contain_text("DOI")
        # The explanation paragraph also carries class "drawer-abstract"; the real
        # abstract is the last one, after the "Abstract" heading.
        expect(drawer.locator(".drawer-abstract").last).to_contain_text("Large Language Models")
        # Step 14: the UI explains why the paper belongs to that category.
        expect(drawer).to_contain_text(" fits ")  # fake explanation text
        # Step 17: each paper links to its real scholarly source.
        source = drawer.locator("a[href^='https://openalex.org/W']")
        expect(source.first).to_be_visible()

        # Step 15: the user can manually move a paper to another subtopic.
        select = page.locator(".drawer-organize select")
        target = select.locator("option", has_text="Topic bravo").get_attribute("value")
        select.select_option(target)  # also closes the drawer
        expect(tabs.filter(has_text="Topic bravo")).to_contain_text("14")

        # Step 16: the user can rename a generated subtopic.
        tabs.filter(has_text="Topic alpha").click()
        page.locator(".subtopic-menu summary").click()
        page.get_by_role("button", name="Rename subtopic").click()
        page.locator(".rename-form input").fill("Renamed by user")
        page.locator(".rename-form").get_by_role("button", name="Save").click()
        expect(tabs.filter(has_text="Renamed by user")).to_have_count(1)

        # Step 18: no paper shown to the user is invented; every displayed title comes
        # from the provider.
        tabs.first.click()
        shown = page.locator(".paper-row h3").all_inner_texts()
        assert shown and set(shown) <= titles
    engine.dispose()
