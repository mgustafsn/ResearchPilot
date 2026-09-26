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


def test_citation_lifecycle_and_field_preservation(client):
    project = client.post("/api/projects", json=DATA).json()
    refs = f"/api/projects/{project['id']}/references"
    created = client.post(
        refs,
        json={
            "title": "Zeta paper",
            "notes": "Keep me",
            "readingStatus": "READING",
        },
    ).json()
    assert (created["isCited"], created["citationNumber"], created["previousCitationNumber"]) == (
        False,
        None,
        None,
    )
    target = f"{refs}/{created['id']}"
    cited = client.patch(target, json={"isCited": True}).json()
    assert cited["isCited"] is True and cited["citationNumber"] is None
    numbered = client.patch(target, json={"citationNumber": 4}).json()
    assert numbered["citationNumber"] == 4
    uncited = client.patch(target, json={"isCited": False}).json()
    assert (uncited["isCited"], uncited["citationNumber"], uncited["previousCitationNumber"]) == (
        False,
        None,
        4,
    )
    repeated = client.patch(target, json={"isCited": False}).json()
    assert repeated["previousCitationNumber"] == 4
    recited = client.patch(target, json={"isCited": True}).json()
    assert recited["citationNumber"] is None
    restored = client.patch(target, json={"citationNumber": 4}).json()
    assert restored["citationNumber"] == 4
    assert restored["previousCitationNumber"] == 4
    assert restored["notes"] == "Keep me"
    assert restored["readingStatus"] == "READING"


def test_citation_validation_uniqueness_and_rollback(client):
    project = client.post("/api/projects", json=DATA).json()
    refs = f"/api/projects/{project['id']}/references"
    invalid_payloads = [
        {"title": "Bad", "citationNumber": 2},
        {"title": "Bad", "isCited": False, "citationNumber": 2},
        {"title": "Bad", "isCited": "yes"},
        {"title": "Bad", "citationNumber": 0},
        {"title": "Bad", "previousCitationNumber": 2},
    ]
    for payload in invalid_payloads:
        assert client.post(refs, json=payload).status_code == 422
    first = client.post(
        refs, json={"title": "First", "isCited": True, "citationNumber": 7, "notes": "one"}
    ).json()
    second = client.post(refs, json={"title": "Second", "notes": "two"}).json()
    second_path = f"{refs}/{second['id']}"
    assert client.patch(second_path, json={"citationNumber": 7}).status_code == 422
    assert client.patch(second_path, json={"isCited": True}).status_code == 200
    conflict = client.patch(
        second_path, json={"citationNumber": 7, "notes": "must roll back", "readingStatus": "READ"}
    )
    assert conflict.status_code == 409
    unchanged = next(item for item in client.get(refs).json() if item["id"] == second["id"])
    assert unchanged["isCited"] is True
    assert unchanged["citationNumber"] is None
    assert unchanged["notes"] == "two"
    assert unchanged["readingStatus"] == "TO_READ"
    assert (
        next(item for item in client.get(refs).json() if item["id"] == first["id"])[
            "citationNumber"
        ]
        == 7
    )


def test_reference_library_orders_by_title_and_allows_many_unnumbered(client):
    project = client.post("/api/projects", json=DATA).json()
    refs = f"/api/projects/{project['id']}/references"
    for title in ["zebra", "Alpha", "middle"]:
        response = client.post(refs, json={"title": title})
        assert response.status_code == 201
        assert response.json()["citationNumber"] is None
    assert [item["title"] for item in client.get(refs).json()] == ["Alpha", "middle", "zebra"]


@pytest.mark.parametrize("manual", [True, False])
def test_notes_only_patch_preserves_other_fields(search_client, manual):
    client, _provider, project = search_client
    assert client.post(project + "/search").status_code == 200
    paper = client.get(project + "/papers").json()[0]
    refs = project + "/references"
    if manual:
        reference = client.post(
            refs, json={"title": "My citation", "authors": ["A. Author"], "doi": "10.1/notes"}
        ).json()
    else:
        reference = client.post(refs + "/from-paper/" + paper["id"]).json()
    target = refs + "/" + reference["id"]
    client.patch(target, json={"isCited": True, "readingStatus": "READING"})
    client.patch(target, json={"citationNumber": 7})
    before = client.get(refs).json()[0]
    for notes in ["First line\nSecond line", "", "x" * 5000, "<script>alert(1)</script>"]:
        response = client.patch(target, json={"notes": notes})
        assert response.status_code == 200
        assert response.json() == {**before, "notes": notes}
    assert client.patch(target, json={"notes": "x" * 5001}).status_code == 422
    assert client.get(refs).json()[0]["notes"] == "<script>alert(1)</script>"


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


def test_postgres_citation_tracking_upgrade_keeps_old_numbers_as_previous(client, engine):
    """The 018 upgrade starts every item uncited but keeps its old number restorable."""
    from pathlib import Path

    from sqlalchemy import text

    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL migration verification")
    root = Path(__file__).parents[2]
    project = client.post("/api/projects", json=DATA).json()
    refs = f"/api/projects/{project['id']}/references"
    first = client.post(refs, json={"title": "Existing one"}).json()
    second = client.post(refs, json={"title": "Existing two"}).json()
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            ALTER TABLE project_references
            DROP CONSTRAINT uq_reference_project_citation_number,
            DROP CONSTRAINT ck_reference_previous_citation_number_positive,
            DROP CONSTRAINT ck_reference_uncited_has_no_number,
            DROP COLUMN "isCited",
            DROP COLUMN "previousCitationNumber";
            ALTER TABLE project_references RENAME COLUMN "citationNumber" TO number;
            """
        )
        connection.execute(
            text("UPDATE project_references SET number = CASE WHEN id = :id THEN 2 ELSE 9 END"),
            {"id": first["id"]},
        )
        connection.exec_driver_sql(
            """
            ALTER TABLE project_references ALTER COLUMN number SET NOT NULL;
            ALTER TABLE project_references ADD CONSTRAINT
                "project_references_projectId_number_key" UNIQUE ("projectId", number);
            """
        )
        connection.exec_driver_sql(
            (root / "migrations/018_reference_citation_tracking.sql").read_text()
        )
        rows = connection.execute(
            text(
                'SELECT id, "citationNumber", "isCited", "previousCitationNumber" '
                "FROM project_references"
            )
        ).all()
    assert {str(row[0]): row[1:] for row in rows} == {
        first["id"]: (None, False, 2),
        second["id"]: (None, False, 9),
    }
    listed = {item["id"]: item for item in client.get(refs).json()}
    assert listed.keys() == {first["id"], second["id"]}
    assert listed[first["id"]]["previousCitationNumber"] == 2
    assert listed[first["id"]]["isCited"] is False
