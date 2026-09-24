"""Reading progress belongs to the project reference, not scholarly metadata."""

import pytest
from fakes import DATA


@pytest.mark.parametrize("manual", [True, False])
def test_reading_transitions_and_preservation(search_client, manual):
    client, provider, project = search_client
    assert client.post(project + "/search").status_code == 200
    paper = client.get(project + "/papers").json()[0]
    refs = project + "/references"
    save = refs + "/from-paper/" + paper["id"]
    if manual:
        reference = client.post(refs, json={"title": "My citation", "doi": paper["doi"]}).json()
    else:
        reference = client.post(save).json()
    assert reference["readingStatus"] == "TO_READ"
    target = refs + "/" + reference["id"]
    for status in ["READING", "READ", "TO_READ", "READ"]:
        response = client.patch(target, json={"readingStatus": status})
        assert response.status_code == 200
        assert response.json()["readingStatus"] == status
    assert (
        client.patch(target, json={"notes": "Keep these notes"}).json()["readingStatus"] == "READ"
    )
    assert client.patch(target, json={}).json()["readingStatus"] == "READ"
    linked = client.post(save).json()
    assert linked["id"] == reference["id"]
    assert linked["readingStatus"] == "READ"
    assert linked["paperId"] == paper["id"]
    provider.papers[0] = provider.papers[0].model_copy(
        update={"title": "Updated large language models"}
    )
    assert client.post(project + "/search").status_code == 200
    result = client.get(refs).json()[0]
    assert result["readingStatus"] == "READ"
    assert result["notes"] == "Keep these notes"
    assert result["status"] == ("Draft" if manual else "Published")
    if not manual:
        assert result["title"] == "Updated large language models"
        assert (
            client.patch(target, json={"title": "Invented", "readingStatus": "READING"}).status_code
            == 409
        )
        assert client.get(refs).json()[0]["readingStatus"] == "READ"


@pytest.mark.parametrize("invalid", [None, "read", "FINISHED", "", 1, True])
def test_invalid_reading_status(client, invalid):
    project = client.post("/api/projects", json=DATA).json()
    refs = f"/api/projects/{project['id']}/references"
    assert client.post(refs, json={"title": "Paper", "readingStatus": invalid}).status_code == 422
    reference = client.post(refs, json={"title": "Paper", "readingStatus": "READING"}).json()
    assert (
        client.patch(refs + "/" + reference["id"], json={"readingStatus": invalid}).status_code
        == 422
    )
    assert client.get(refs).json()[0]["readingStatus"] == "READING"


def test_reading_status_is_project_owned(search_client):
    client, _, first = search_client
    second = "/api/projects/" + client.post("/api/projects", json=DATA).json()["id"]
    saved = []
    for project in [first, second]:
        assert client.post(project + "/search").status_code == 200
        paper = client.get(project + "/papers").json()[0]
        saved.append(client.post(project + "/references/from-paper/" + paper["id"]).json())
    assert saved[0]["paperId"] == saved[1]["paperId"]
    assert (
        client.patch(
            first + "/references/" + saved[0]["id"], json={"readingStatus": "READ"}
        ).status_code
        == 200
    )
    assert client.get(second + "/references").json()[0]["readingStatus"] == "TO_READ"
    assert (
        client.patch(
            second + "/references/" + saved[0]["id"], json={"readingStatus": "READ"}
        ).status_code
        == 404
    )


def test_postgres_reading_status_upgrade(client, engine):
    """Simulate a pre-016 library, then apply the real upgrade and check backfill."""
    from pathlib import Path
    import runpy

    from sqlalchemy import inspect
    from sqlalchemy.exc import IntegrityError

    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL migration verification")
    root = Path(__file__).parents[2]
    applied = runpy.run_path(str(root / "scripts/migrate.py"))["_already_applied"]
    project = client.post("/api/projects", json=DATA).json()
    refs = f"/api/projects/{project['id']}/references"
    client.post(refs, json={"title": "Existing citation", "notes": "Existing notes"})
    with engine.begin() as connection:
        connection.exec_driver_sql('ALTER TABLE project_references DROP COLUMN "readingStatus"')
    assert not applied(inspect(engine), 16)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            (root / "migrations/016_reference_reading_status.sql").read_text()
        )
    assert applied(inspect(engine), 16)
    reference = client.get(refs).json()[0]
    assert reference["readingStatus"] == "TO_READ"
    assert reference["notes"] == "Existing notes"
    for value in ["NULL", "'INVALID'"]:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.exec_driver_sql(f'UPDATE project_references SET "readingStatus" = {value}')
