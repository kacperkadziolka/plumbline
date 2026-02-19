import re
from datetime import date
from io import BytesIO

from fastapi.testclient import TestClient

VALID_YAML = """\
base_currency: EUR
buckets:
  core:
    targets:
      IWDA.AS: 0.60
      EIMI.AS: 0.40
"""

BACKTEST_YAML = """\
start_date: 2024-01-15
end_date: 2024-03-15
contribution_schedule:
  type: monthly
  amount: 1000
  currency: EUR
  day_of_month: 15
"""


def _seed_policy(client: TestClient) -> str:
    """Seed a policy and return its ID."""
    client.post("/policy", data={"name": "bt-policy", "yaml_text": VALID_YAML})
    page = client.get("/backtests")
    match = re.search(r'value="(\d+)"[^>]*>\s*bt-policy', page.text)
    assert match is not None, "Could not find policy option"
    return match.group(1)


def _seed_prices(client: TestClient) -> None:
    """Seed assets and daily price data for the backtest period."""
    # Holdings import creates assets
    holdings_csv = "ticker,qty,currency,asset_type\nIWDA.AS,10,EUR,equity\nEIMI.AS,5,EUR,equity\n"
    client.post(
        "/import/holdings/manual",
        files={"file": ("holdings.csv", BytesIO(holdings_csv.encode()), "text/csv")},
    )

    # Generate price CSV covering 2024-01-15 to 2024-03-15
    lines = ["ticker,date,close,currency"]
    d = date(2024, 1, 15)
    while d <= date(2024, 3, 15):
        lines.append(f"IWDA.AS,{d.isoformat()},80.00,EUR")
        lines.append(f"EIMI.AS,{d.isoformat()},30.00,EUR")
        d = date.fromordinal(d.toordinal() + 1)

    prices_csv = "\n".join(lines) + "\n"
    client.post(
        "/import/prices",
        files={"file": ("prices.csv", BytesIO(prices_csv.encode()), "text/csv")},
    )


def test_backtests_page_renders_form(client: TestClient) -> None:
    response = client.get("/backtests")
    assert response.status_code == 200
    assert "Backtests" in response.text
    assert "Run Backtest" in response.text
    assert 'name="policy_id"' in response.text
    assert 'name="backtest_yaml"' in response.text


def test_backtests_page_has_navigation(client: TestClient) -> None:
    response = client.get("/backtests")
    assert response.status_code == 200
    assert 'href="/"' in response.text
    assert 'href="/policy"' in response.text


def test_backtests_page_empty_state(client: TestClient) -> None:
    response = client.get("/backtests")
    assert response.status_code == 200
    assert "No backtest runs yet" in response.text


def test_post_backtest_invalid_policy_id(client: TestClient) -> None:
    response = client.post(
        "/backtests",
        data={"policy_id": "abc", "backtest_yaml": BACKTEST_YAML},
    )
    assert response.status_code == 200
    assert "select a policy" in response.text.lower() or "Select" in response.text


def test_post_backtest_whitespace_yaml(client: TestClient) -> None:
    policy_id = _seed_policy(client)
    response = client.post(
        "/backtests",
        data={"policy_id": policy_id, "backtest_yaml": "   "},
    )
    assert response.status_code == 200
    assert "empty" in response.text.lower() or "YAML" in response.text


def test_post_backtest_invalid_yaml(client: TestClient) -> None:
    policy_id = _seed_policy(client)
    response = client.post(
        "/backtests",
        data={"policy_id": policy_id, "backtest_yaml": "not valid yaml: ["},
    )
    assert response.status_code == 200
    assert "Run Backtest" in response.text  # Form is re-rendered


def test_backtest_detail_not_found(client: TestClient) -> None:
    response = client.get("/backtests/99999")
    assert response.status_code == 400
    assert "not found" in response.text.lower() or "Not Found" in response.text


def test_run_backtest_full_integration(client: TestClient) -> None:
    policy_id = _seed_policy(client)
    _seed_prices(client)

    response = client.post(
        "/backtests",
        data={"policy_id": policy_id, "backtest_yaml": BACKTEST_YAML},
        follow_redirects=False,
    )
    # Should redirect to detail page (303)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/backtests/")

    # Follow redirect to detail page
    detail_response = client.get(response.headers["location"])
    assert detail_response.status_code == 200
    assert "Backtest Run #" in detail_response.text
    assert "Metrics" in detail_response.text
    assert "Equity Curve" in detail_response.text
    assert "Total Return" in detail_response.text
    assert "2024-01-15" in detail_response.text

    # Charts are included
    assert "chart.js" in detail_response.text.lower()
    assert 'id="equityChart"' in detail_response.text
    assert 'id="drawdownChart"' in detail_response.text
    assert 'id="contributionsChart"' in detail_response.text


def test_backtests_list_shows_run_after_creation(client: TestClient) -> None:
    # After the full integration test, there should be at least one run
    response = client.get("/backtests")
    assert response.status_code == 200
    assert "No backtest runs yet" not in response.text
    assert "2024-01-15" in response.text
    assert "2024-03-15" in response.text


def test_post_backtest_preserves_form_values(client: TestClient) -> None:
    response = client.post(
        "/backtests",
        data={"policy_id": "99999", "backtest_yaml": BACKTEST_YAML},
    )
    assert response.status_code == 200
    # The YAML should be preserved in the textarea
    assert "start_date: 2024-01-15" in response.text
