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


def _seed_policy(client: TestClient) -> None:
    client.post("/policy", data={"name": "test-policy", "yaml_text": VALID_YAML})


def _seed_holdings_and_prices(client: TestClient) -> None:
    today = date.today().isoformat()
    holdings_csv = "ticker,qty,currency,asset_type\nIWDA.AS,10,EUR,equity\nEIMI.AS,5,EUR,equity\n"
    client.post(
        "/import/holdings/manual",
        files={"file": ("holdings.csv", BytesIO(holdings_csv.encode()), "text/csv")},
    )

    prices_csv = f"ticker,date,close,currency\nIWDA.AS,{today},80.00,EUR\nEIMI.AS,{today},30.00,EUR\n"
    client.post(
        "/import/prices",
        files={"file": ("prices.csv", BytesIO(prices_csv.encode()), "text/csv")},
    )


def test_propose_page_renders_form(client: TestClient) -> None:
    response = client.get("/propose")
    assert response.status_code == 200
    assert "Contribution Proposal" in response.text
    assert 'name="amount"' in response.text
    assert 'name="currency"' in response.text
    assert 'name="policy_id"' in response.text
    assert "Generate Proposal" in response.text


def test_propose_page_lists_policies(client: TestClient) -> None:
    _seed_policy(client)
    response = client.get("/propose")
    assert response.status_code == 200
    assert "test-policy" in response.text


def test_propose_page_has_navigation(client: TestClient) -> None:
    response = client.get("/propose")
    assert response.status_code == 200
    assert 'href="/"' in response.text
    assert 'href="/policy"' in response.text


def test_generate_proposal_invalid_amount(client: TestClient) -> None:
    response = client.post(
        "/propose",
        data={"amount": "not-a-number", "currency": "EUR", "policy_id": "1"},
    )
    assert response.status_code == 200
    assert "Invalid amount" in response.text


def test_generate_proposal_no_policy_selected(client: TestClient) -> None:
    # Empty policy_id is caught by our handler as a parse error
    response = client.post(
        "/propose",
        data={"amount": "1000", "currency": "EUR", "policy_id": "abc"},
    )
    assert response.status_code == 200
    assert "select a policy" in response.text.lower() or "Select" in response.text


def test_generate_proposal_success(client: TestClient) -> None:
    _seed_policy(client)
    _seed_holdings_and_prices(client)

    # Find the policy_id from the propose page
    page = client.get("/propose")
    assert "test-policy" in page.text

    # Extract policy_id from the select option
    import re

    match = re.search(r'value="(\d+)"[^>]*>\s*test-policy', page.text)
    assert match is not None, "Could not find policy option in form"
    policy_id = match.group(1)

    response = client.post(
        "/propose",
        data={"amount": "1000", "currency": "EUR", "policy_id": policy_id},
    )
    assert response.status_code == 200
    assert "Allocation Plan" in response.text
    assert "IWDA.AS" in response.text
    assert "EIMI.AS" in response.text
    assert "Buy Amount" in response.text
    assert "Save Proposal" in response.text


def test_generate_proposal_preserves_form_values(client: TestClient) -> None:
    response = client.post(
        "/propose",
        data={"amount": "500", "currency": "USD", "policy_id": "99999"},
    )
    assert response.status_code == 200
    # Form values should be preserved
    assert 'value="500"' in response.text
    assert 'value="USD"' in response.text


def test_save_proposal_success(client: TestClient) -> None:
    _seed_policy(client)
    _seed_holdings_and_prices(client)

    page = client.get("/propose")
    import re

    match = re.search(r'value="(\d+)"[^>]*>\s*test-policy', page.text)
    assert match is not None
    policy_id = match.group(1)

    # Generate proposal first
    gen_response = client.post(
        "/propose",
        data={"amount": "1000", "currency": "EUR", "policy_id": policy_id},
    )
    assert gen_response.status_code == 200
    assert "Save Proposal" in gen_response.text

    # Extract the allocation_json from hidden field
    json_match = re.search(r'name="allocation_json"\s+value="([^"]*)"', gen_response.text)
    assert json_match is not None, "Could not find allocation_json hidden field"
    import html

    allocation_json = html.unescape(json_match.group(1))

    # Save the proposal
    save_response = client.post(
        "/propose/save",
        data={
            "policy_id": policy_id,
            "amount": "1000",
            "currency": "EUR",
            "allocation_json": allocation_json,
        },
    )
    assert save_response.status_code == 200
    assert "Proposal saved" in save_response.text
    assert "Download CSV" in save_response.text
