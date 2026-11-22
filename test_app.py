import pytest
from app import app, tasks, counter


@pytest.fixture
def client():
    tasks.clear()
    counter["next_id"] = 1
    return app.test_client()


def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


def test_create_and_get_task(client):
    r = client.post("/tasks", json={"title": "Test"})
    assert r.status_code == 201
    assert client.get("/tasks/1").json["title"] == "Test"


def test_create_task_without_title(client):
    assert client.post("/tasks", json={}).status_code == 400


def test_get_unknown_task(client):
    assert client.get("/tasks/999").status_code == 404


def test_delete_task(client):
    client.post("/tasks", json={"title": "x"})
    assert client.delete("/tasks/1").status_code == 204


def test_metrics(client):
    client.get("/health")
    assert b"http_requests_total" in client.get("/metrics").data