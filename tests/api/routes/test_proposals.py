from fastapi.testclient import TestClient

from app.main import app


def test_list_proposals_returns_empty_initially() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/proposals/")

        assert response.status_code == 200
        data = response.json()
        assert data["proposals"] == []
        assert data["count"] == 0


def test_export_csv_returns_error_for_nonexistent_proposal() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/proposals/99999/csv")

        assert response.status_code == 400
