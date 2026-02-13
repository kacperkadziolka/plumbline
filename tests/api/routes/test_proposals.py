from fastapi.testclient import TestClient

from tests.api.routes.conftest import _seed_proposal


def test_list_proposals_returns_empty_initially(client: TestClient) -> None:
    response = client.get("/api/v1/proposals/")

    assert response.status_code == 200
    data = response.json()
    assert data["proposals"] == []
    assert data["count"] == 0


def test_export_csv_returns_error_for_nonexistent_proposal(client: TestClient) -> None:
    response = client.get("/api/v1/proposals/99999/csv")

    assert response.status_code == 400


def test_list_proposals_returns_seeded_data(client: TestClient) -> None:
    proposal_id = _seed_proposal()

    response = client.get("/api/v1/proposals/")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1
    ids = [p["proposal_id"] for p in data["proposals"]]
    assert proposal_id in ids

    match = next(p for p in data["proposals"] if p["proposal_id"] == proposal_id)
    assert match["currency"] == "EUR"
    assert float(match["amount"]) == 1000.00


def test_csv_export_returns_valid_csv_with_correct_headers(client: TestClient) -> None:
    proposal_id = _seed_proposal()

    response = client.get(f"/api/v1/proposals/{proposal_id}/csv")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert f"proposal_{proposal_id}.csv" in response.headers["content-disposition"]

    body = response.text
    lines = body.strip().split("\n")

    # Metadata comments present
    comment_lines = [line for line in lines if line.startswith("#")]
    assert len(comment_lines) == 8
    assert any("proposal_id" in line for line in comment_lines)
    assert any("policy_hash" in line for line in comment_lines)

    # CSV header and data rows
    data_lines = [line for line in lines if not line.startswith("#")]
    assert data_lines[0] == "ticker,buy_amount,current_weight,target_weight,gap"
    assert len(data_lines) == 3  # header + 2 trades

    # Verify trade data is present
    assert any("IWDA.AS" in line for line in data_lines)
    assert any("EIMI.AS" in line for line in data_lines)
