from io import BytesIO

from fastapi.testclient import TestClient


def test_import_page_renders_form(client: TestClient) -> None:
    response = client.get("/import")
    assert response.status_code == 200
    assert "Import Data" in response.text
    assert 'enctype="multipart/form-data"' in response.text
    assert 'type="file"' in response.text
    assert "Required columns" in response.text


def test_import_page_shows_all_tabs(client: TestClient) -> None:
    response = client.get("/import")
    assert response.status_code == 200
    assert "Holdings" in response.text
    assert "Prices" in response.text
    assert "FX Rates" in response.text
    assert "Manual CSV" in response.text
    assert "IBKR Statement" in response.text


def test_holdings_page_renders_empty_state(client: TestClient) -> None:
    """Holdings page renders with empty state when no data."""
    response = client.get("/holdings")
    assert response.status_code == 200
    assert "Holdings" in response.text
    assert "No holdings imported" in response.text
    assert "Import Holdings" in response.text


def test_holdings_page_displays_imported_data(client: TestClient) -> None:
    """Holdings page displays data after import."""
    csv_content = """ticker,qty,currency,asset_type,name
AAPL,10,USD,equity,Apple Inc.
MSFT,5,USD,equity,Microsoft Corporation
"""
    client.post(
        "/import/holdings/manual",
        files={"file": ("holdings.csv", BytesIO(csv_content.encode()), "text/csv")},
    )

    response = client.get("/holdings")
    assert response.status_code == 200
    assert "AAPL" in response.text
    assert "Apple Inc." in response.text
    assert "MSFT" in response.text
    assert "Microsoft Corporation" in response.text


def test_holdings_page_shows_snapshot_metadata(client: TestClient) -> None:
    """Holdings page shows snapshot date and ID."""
    csv_content = """ticker,qty,currency,asset_type
AAPL,10,USD,equity
"""
    client.post(
        "/import/holdings/manual",
        files={"file": ("holdings.csv", BytesIO(csv_content.encode()), "text/csv")},
    )

    response = client.get("/holdings")
    assert response.status_code == 200
    assert "Snapshot Date:" in response.text
    assert "Snapshot ID:" in response.text
    assert "Positions:" in response.text


def test_holdings_page_has_refresh_button(client: TestClient) -> None:
    """Holdings page includes HTMX refresh button."""
    response = client.get("/holdings")
    assert response.status_code == 200
    assert 'hx-get="/holdings"' in response.text
    assert "Refresh" in response.text


def test_upload_valid_csv_shows_success(client: TestClient) -> None:
    csv_content = """ticker,qty,currency,asset_type,name
AAPL,10,USD,equity,Apple Inc.
MSFT,5,USD,equity,Microsoft Corporation
"""
    response = client.post(
        "/import/holdings/manual",
        files={"file": ("holdings.csv", BytesIO(csv_content.encode()), "text/csv")},
    )

    assert response.status_code == 200
    assert "Import Successful" in response.text
    assert "2 positions imported" in response.text
    assert "View Holdings" in response.text


def test_upload_empty_csv_shows_error(client: TestClient) -> None:
    response = client.post(
        "/import/holdings/manual",
        files={"file": ("empty.csv", BytesIO(b""), "text/csv")},
    )

    assert response.status_code == 400
    assert "Validation Error" in response.text
    assert "CSV is empty" in response.text


def test_upload_csv_missing_columns_shows_error(client: TestClient) -> None:
    csv_content = """ticker,qty,currency
AAPL,10,USD
"""
    response = client.post(
        "/import/holdings/manual",
        files={"file": ("missing_cols.csv", BytesIO(csv_content.encode()), "text/csv")},
    )

    assert response.status_code == 400
    assert "Validation Error" in response.text
    assert "Missing required columns" in response.text
    assert "asset_type" in response.text


def test_upload_csv_invalid_qty_shows_error(client: TestClient) -> None:
    csv_content = """ticker,qty,currency,asset_type
AAPL,-5,USD,equity
"""
    response = client.post(
        "/import/holdings/manual",
        files={"file": ("invalid_qty.csv", BytesIO(csv_content.encode()), "text/csv")},
    )

    assert response.status_code == 400
    assert "Validation Error" in response.text
    assert "must be greater than 0" in response.text


# IBKR Import Tests


def test_upload_valid_ibkr_shows_success(client: TestClient) -> None:
    ibkr_csv = (
        "Statement,Data,Period,January 2026\n"
        "Financial Instrument Information,Header,Cat,Symbol,Desc,,,,,,Type,\n"
        "Financial Instrument Information,Data,Stocks,AMZN,AMAZON,,,,,,COMMON,\n"
        "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity\n"
        "Open Positions,Data,Summary,Stocks,USD,AMZN,10\n"
    )
    response = client.post(
        "/import/holdings/ibkr",
        files={"file": ("activity.csv", BytesIO(ibkr_csv.encode()), "text/csv")},
    )

    assert response.status_code == 200
    assert "Import Successful" in response.text
    assert "1 position imported" in response.text


def test_upload_empty_ibkr_shows_error(client: TestClient) -> None:
    response = client.post(
        "/import/holdings/ibkr",
        files={"file": ("empty.csv", BytesIO(b""), "text/csv")},
    )

    assert response.status_code == 400
    assert "Validation Error" in response.text
    assert "empty" in response.text.lower()


def test_upload_ibkr_missing_positions_shows_error(client: TestClient) -> None:
    ibkr_csv = "Statement,Data,Period,January 2026\nFinancial Instrument Information,Header,Asset Category,Symbol\n"
    response = client.post(
        "/import/holdings/ibkr",
        files={"file": ("no_positions.csv", BytesIO(ibkr_csv.encode()), "text/csv")},
    )

    assert response.status_code == 400
    assert "Validation Error" in response.text
    assert "Open Positions" in response.text


# Prices Import Tests


def test_upload_valid_prices_csv_shows_success(client: TestClient) -> None:
    # First create assets via holdings import
    holdings_csv = """ticker,qty,currency,asset_type
AAPL,10,USD,equity
"""
    client.post(
        "/import/holdings/manual",
        files={"file": ("holdings.csv", BytesIO(holdings_csv.encode()), "text/csv")},
    )

    prices_csv = """date,ticker,close,currency
2024-01-15,AAPL,185.92,USD
2024-01-16,AAPL,186.50,USD
"""
    response = client.post(
        "/import/prices",
        files={"file": ("prices.csv", BytesIO(prices_csv.encode()), "text/csv")},
    )

    assert response.status_code == 200
    assert "Import Successful" in response.text
    assert "2 price rows imported" in response.text


def test_upload_empty_prices_csv_shows_error(client: TestClient) -> None:
    response = client.post(
        "/import/prices",
        files={"file": ("empty.csv", BytesIO(b""), "text/csv")},
    )

    assert response.status_code == 400
    assert "Validation Error" in response.text
    assert "CSV is empty" in response.text


def test_upload_prices_unknown_ticker_shows_error(client: TestClient) -> None:
    prices_csv = """date,ticker,close,currency
2024-01-15,ZZZZ,100.00,USD
"""
    response = client.post(
        "/import/prices",
        files={"file": ("prices.csv", BytesIO(prices_csv.encode()), "text/csv")},
    )

    assert response.status_code == 400
    assert "ZZZZ" in response.text


# FX Import Tests


def test_upload_valid_fx_csv_shows_success(client: TestClient) -> None:
    fx_csv = """date,pair,rate
2024-01-15,USD/EUR,0.92
2024-01-15,GBP/EUR,1.17
"""
    response = client.post(
        "/import/fx",
        files={"file": ("fx.csv", BytesIO(fx_csv.encode()), "text/csv")},
    )

    assert response.status_code == 200
    assert "Import Successful" in response.text
    assert "2 FX rate rows imported" in response.text


def test_upload_empty_fx_csv_shows_error(client: TestClient) -> None:
    response = client.post(
        "/import/fx",
        files={"file": ("empty.csv", BytesIO(b""), "text/csv")},
    )

    assert response.status_code == 400
    assert "Validation Error" in response.text
    assert "CSV is empty" in response.text


def test_upload_fx_invalid_pair_shows_error(client: TestClient) -> None:
    fx_csv = """date,pair,rate
2024-01-15,INVALID,0.92
"""
    response = client.post(
        "/import/fx",
        files={"file": ("fx.csv", BytesIO(fx_csv.encode()), "text/csv")},
    )

    assert response.status_code == 400
    assert "Validation Error" in response.text
