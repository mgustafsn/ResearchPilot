"""Saved-query validation through the API, without real provider/LLM calls."""

import pytest


def add(client, url, text):
    response = client.post(url + "/queries/custom", json={"query": text})
    assert response.status_code == 201
    return response.json()


def test_ten_saved_query_cap_counts_disabled_queries_and_recovers_after_delete(search_client):
    client, provider, url = search_client
    saved = [add(client, url, f"query {i}") for i in range(10)]
    path = f"{url}/queries/{saved[0]['id']}"
    assert client.patch(path, json={"enabled": False}).status_code == 200
    before = client.get(url + "/queries").json()
    response = client.post(url + "/queries/custom", json={"query": "eleventh query"})
    assert response.status_code == 422
    assert client.get(url + "/queries").json() == before
    assert client.patch(path, json={"query": "edited at capacity"}).status_code == 200
    assert client.delete(path).status_code == 204
    add(client, url, "replacement query")
    assert len(client.get(url + "/queries").json()) == 10
    assert provider.calls == []


@pytest.mark.parametrize(
    "original, duplicate",
    [
        ("Language Models", "language MODELS"),
        ("Straße", "STRASSE"),
        ("cloud provisioning", "  CLOUD\t provisioning\n"),
    ],
)
def test_duplicate_create_and_patch_are_case_insensitive_and_atomic(
    search_client, original, duplicate
):
    client, provider, url = search_client
    first = add(client, url, original)
    second = add(client, url, "different query")
    before = client.get(url + "/queries").json()
    assert client.post(url + "/queries/custom", json={"query": duplicate}).status_code == 409
    assert (
        client.patch(
            f"{url}/queries/{second['id']}",
            json={
                "query": duplicate,
                "enabled": False,
            },
        ).status_code
        == 409
    )
    assert client.get(url + "/queries").json() == before
    # Updating a query's own spelling is not a duplicate of another row.
    response = client.patch(f"{url}/queries/{first['id']}", json={"query": duplicate})
    assert response.status_code == 200
    assert response.json()["query"] == " ".join(duplicate.split())
    assert response.json()["enabled"] is True
    assert provider.calls == []


def test_create_and_patch_collapse_all_whitespace_and_reject_empty_text(search_client):
    client, _, url = search_client
    query = add(client, url, " \tcloud\n\n provisioning\u00a0tools  ")
    assert query["query"] == "cloud provisioning tools"
    path = f"{url}/queries/{query['id']}"
    response = client.patch(path, json={"query": "\nterraform\t\t modules  "})
    assert response.status_code == 200
    assert response.json()["query"] == "terraform modules"
    before = client.get(url + "/queries").json()
    assert client.post(url + "/queries/custom", json={"query": " \t\n "}).status_code == 422
    assert client.patch(path, json={"query": "\t\n"}).status_code == 422
    assert client.get(url + "/queries").json() == before


def test_disabling_every_query_blocks_search_without_changing_previous_results(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    assert client.post(url + "/search").status_code == 200
    queries = client.get(url + "/queries").json()
    assert queries
    before = {
        key: client.get(url + "/" + key).json() for key in ["papers", "subtopics", "searches"]
    }
    calls_before = (
        len(provider.calls),
        len(embedder.batches),
        len(llm.calls),
        len(llm.explain_calls),
    )
    for query in queries:
        response = client.patch(f"{url}/queries/{query['id']}", json={"enabled": False})
        assert response.status_code == 200
        assert response.json()["enabled"] is False
    assert all(not query["enabled"] for query in client.get(url + "/queries").json())
    response = client.post(url + "/search")
    assert response.status_code == 422
    assert response.json()["code"] == "NO_ENABLED_QUERIES"
    assert {key: client.get(url + "/" + key).json() for key in before} == before
    assert (
        len(provider.calls),
        len(embedder.batches),
        len(llm.calls),
        len(llm.explain_calls),
    ) == calls_before
    assert (
        client.patch(f"{url}/queries/{queries[0]['id']}", json={"enabled": True}).status_code == 200
    )
    assert client.post(url + "/search").status_code == 200
    assert len(provider.calls) == calls_before[0] + 1


def test_regeneration_respects_cap_and_preserves_custom_queries(search_client_named):
    client, provider, _, llm, url = search_client_named
    custom = [add(client, url, f"custom query {i}") for i in range(9)]
    llm.expansion = ["suggested first", "suggested second", "suggested third"]
    response = client.post(url + "/queries")
    assert response.status_code == 200
    saved = client.get(url + "/queries").json()
    assert len(saved) == 10
    assert {item["id"] for item in custom} <= {item["id"] for item in saved}
    assert [item["query"] for item in saved if not item["userAdded"]] == ["suggested first"]
    assert client.post(url + "/queries").status_code == 200
    assert len(client.get(url + "/queries").json()) == 10
    assert provider.calls == []
