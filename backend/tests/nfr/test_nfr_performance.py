"""NFR-PERF-1..4 (docs/requirements.md §31): 250-paper projects stay responsive."""

import re
import time

import numpy as np
import pytest
from playwright.sync_api import expect

from fakes import WORK
from nfr_support import budget, check_budget
from researchpilot.analysis import deduplicate, filter_relevant, rank_papers, rank_semantically
from researchpilot.clustering import cluster_papers
from researchpilot.providers.openalex import normalize_work

pytestmark = pytest.mark.nfr


def test_nfr_perf_1_map_renders_250_papers(large_browser, record_property):
    page, base, project_id = large_browser
    with budget(record_property, "NFR-PERF-1", 1.5):
        page.goto(f"{base}/projects/{project_id}")
        expect(page.locator(".paper-row")).to_have_count(252, timeout=10_000)


def test_nfr_perf_2_tab_and_filter_rerender(large_browser, record_property):
    page, base, project_id = large_browser
    page.goto(f"{base}/projects/{project_id}")
    expect(page.locator(".paper-row")).to_have_count(252, timeout=10_000)
    tab = page.locator(".cluster-tab").nth(1)
    expected = int(tab.locator(".count").inner_text())
    with budget(record_property, "NFR-PERF-2 tab", 0.3):
        tab.click()
        expect(tab).to_have_class(re.compile(r"\bactive\b"))
        expect(page.locator(".paper-row")).to_have_count(expected)

    papers = page.request.get(f"{base}/api/projects/{project_id}/papers").json()
    selected_cluster = sorted({p["clusterId"] for p in papers if p["clusterId"] is not None})[0]
    expected_oa = sum(
        1
        for p in papers
        if p["clusterId"] == selected_cluster
        and p["isRelevant"] is not False
        and p["accessStatus"] == "OPEN_ACCESS"
    )
    toggle = page.get_by_role("button", name="Open access only", exact=True)
    paper_list = page.locator(".paper-list").element_handle()
    with budget(record_property, "NFR-PERF-2 filter", 0.3):
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "true")
        if expected_oa == expected:
            # A row-count assertion would prove nothing if the open-access filter
            # happens to leave this cluster's count unchanged; wait for the
            # re-render itself (the old .paper-list node gets replaced) instead.
            page.wait_for_function("list => !list.isConnected", arg=paper_list)
        else:
            expect(page.locator(".paper-row")).to_have_count(expected_oa)


def test_nfr_perf_3_backend_analysis_of_250_papers(record_property):
    papers = [
        normalize_work(
            WORK
            | {
                "id": f"https://openalex.org/W{5000 + n}",
                "doi": f"https://doi.org/10.6000/perf-{n % 245}",  # 5 DOI duplicates
                "title": f"study {n} of large language models in software engineering",
            }
        )
        for n in range(250)
    ]
    rng = np.random.default_rng(0)
    centres = rng.normal(size=(6, 512))
    with budget(record_property, "NFR-PERF-3", 1.0):
        unique, _ = deduplicate(papers)
        lexical = rank_papers(unique, "large language models software engineering", [])
        vectors = {
            item.paper.id: (centres[i % 6] + rng.normal(scale=0.3, size=512)).tolist()
            for i, item in enumerate(lexical)
        }
        question = centres.mean(axis=0).tolist()
        ranked = filter_relevant(rank_semantically(lexical, question, vectors))
        cluster_papers([vectors[item.paper.id] for item in ranked])


@pytest.mark.parametrize("endpoint", ["/papers", "/subtopics", "/searches", "/queries"])
def test_nfr_perf_4_read_endpoints_p95(large_api, record_property, endpoint):
    client, url = large_api
    timings = []
    for _ in range(20):
        started = time.perf_counter()
        assert client.get(url + endpoint).status_code == 200
        timings.append(time.perf_counter() - started)
    p95 = sorted(timings)[18]  # 19th of 20 samples
    check_budget(record_property, f"NFR-PERF-4 {endpoint}", 0.2, p95)
