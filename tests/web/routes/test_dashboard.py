from datetime import date
from io import BytesIO

from fastapi.testclient import TestClient

TODAY = date.today().isoformat()


def test_dashboard_no_data_state(client: TestClient) -> None:
    """Dashboard shows welcome/onboarding when no data is imported."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Welcome to Plumbline" in response.text
    assert "Import Holdings" in response.text


def test_dashboard_partial_state(client: TestClient) -> None:
    """Dashboard shows partial state when holdings exist but prices are missing."""
    csv_content = """ticker,qty,currency,asset_type,name
AAPL,10,USD,equity,Apple Inc.
MSFT,5,USD,equity,Microsoft Corporation
"""
    client.post(
        "/import/holdings/manual",
        files={"file": ("holdings.csv", BytesIO(csv_content.encode()), "text/csv")},
    )

    response = client.get("/")
    assert response.status_code == 200
    assert "Market data missing" in response.text
    assert "2 positions" in response.text
    assert 'href="/import"' in response.text
    assert 'href="/holdings"' in response.text


def test_dashboard_full_state(client: TestClient) -> None:
    """Dashboard shows full valuation after importing holdings, prices, and FX."""
    prices_csv = f"""date,ticker,close,currency
{TODAY},AAPL,185.00,USD
{TODAY},MSFT,420.00,USD
"""
    client.post(
        "/import/prices",
        files={"file": ("prices.csv", BytesIO(prices_csv.encode()), "text/csv")},
    )

    fx_csv = f"""date,pair,rate
{TODAY},USD/EUR,0.92
"""
    client.post(
        "/import/fx",
        files={"file": ("fx.csv", BytesIO(fx_csv.encode()), "text/csv")},
    )

    response = client.get("/")
    assert response.status_code == 200
    assert "Total Portfolio Value" in response.text
    assert "Top Holdings" in response.text
    assert "Currency Exposure" in response.text
    assert "AAPL" in response.text
    assert "MSFT" in response.text
    assert "USD" in response.text


def test_dashboard_navigation_links(client: TestClient) -> None:
    """Dashboard always shows navigation links."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/holdings"' in response.text
    assert 'href="/valuation"' in response.text
    assert 'href="/import"' in response.text
