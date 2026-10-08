from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_rejects_unsupported_extension():
    response = client.post(
        "/api/files/",
        files={"file": ("notes.txt", b"not geospatial", "text/plain")},
    )
    assert response.status_code == 400
    assert "Only .kml or .zip" in response.json()["detail"]


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
