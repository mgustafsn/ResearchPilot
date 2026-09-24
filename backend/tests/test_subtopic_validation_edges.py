"""Subtopic boundary failures must leave existing organization intact."""

import pytest

from fakes import grouped_papers


@pytest.fixture
def populated_project(search_client_named):
    client, provider, _, _, url = search_client_named
    provider.papers = grouped_papers()
    assert client.post(url + "/search").status_code == 200
    assert len(client.get(url + "/subtopics").json()) >= 2
    return client, url


def snapshot(client, url):
    return (client.get(url + "/subtopics").json(), client.get(url + "/papers").json())


@pytest.mark.parametrize(
    "operation, expected_status",
    [
        ("self", 422),
        ("unknown_target", 404),
        ("unknown_source", 404),
        ("delete_unknown", 404),
    ],
)
def test_invalid_merge_and_delete_preserve_topics_and_papers(
    populated_project, operation, expected_status
):
    client, url = populated_project
    before = snapshot(client, url)
    source = before[0][0]["clusterId"]
    unknown = max(topic["clusterId"] for topic in before[0]) + 100
    if operation == "delete_unknown":
        response = client.delete(f"{url}/subtopics/{unknown}")
    else:
        target = source if operation != "unknown_target" else unknown
        source = unknown if operation == "unknown_source" else source
        response = client.post(f"{url}/subtopics/{source}/merge", json={"targetClusterId": target})
    assert response.status_code == expected_status
    assert snapshot(client, url) == before


@pytest.mark.parametrize("name, description", [("n", ""), ("n" * 80, "d" * 500)])
def test_rename_accepts_exact_limits_and_persists(populated_project, name, description):
    client, url = populated_project
    topics, papers = snapshot(client, url)
    cluster = topics[0]["clusterId"]
    response = client.patch(
        f"{url}/subtopics/{cluster}", json={"name": name, "description": description}
    )
    assert response.status_code == 200
    assert response.json()["name"] == name
    assert response.json()["description"] == description
    assert response.json()["userModified"] is True
    fetched = client.get(url + "/subtopics").json()
    assert next(topic for topic in fetched if topic["clusterId"] == cluster) == response.json()
    assert {p["id"]: p["clusterId"] for p in client.get(url + "/papers").json()} == {
        p["id"]: p["clusterId"] for p in papers
    }


@pytest.mark.parametrize(
    "patch",
    [
        {"name": ""},
        {"name": " \t\n "},
        {"name": "n" * 81},
        {"name": "Valid", "description": "d" * 501},
    ],
)
def test_invalid_rename_is_rejected_without_changes(populated_project, patch):
    client, url = populated_project
    before = snapshot(client, url)
    cluster = before[0][0]["clusterId"]
    response = client.patch(f"{url}/subtopics/{cluster}", json=patch)
    assert response.status_code == 422
    assert snapshot(client, url) == before


def test_rename_trims_whitespace_before_length_validation(populated_project):
    client, url = populated_project
    cluster = client.get(url + "/subtopics").json()[0]["clusterId"]
    response = client.patch(
        f"{url}/subtopics/{cluster}",
        json={
            "name": "  " + "n" * 80 + "\n",
            "description": "\t" + "d" * 500 + "  ",
        },
    )
    assert response.status_code == 200
    assert response.json()["name"] == "n" * 80
    assert response.json()["description"] == "d" * 500
