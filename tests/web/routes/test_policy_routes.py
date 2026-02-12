import re

from fastapi.testclient import TestClient

VALID_YAML = """\
base_currency: EUR
buckets:
  core:
    targets:
      IWDA.AS: 0.60
      EIMI.AS: 0.25
      IUSN.AS: 0.15
"""


def test_policy_page_renders_empty_state(client: TestClient) -> None:
    response = client.get("/policy")
    assert response.status_code == 200
    assert "Policy Editor" in response.text
    assert "No policies saved yet" in response.text


def test_policy_page_has_editor_form(client: TestClient) -> None:
    response = client.get("/policy")
    assert response.status_code == 200
    assert 'name="name"' in response.text
    assert 'name="yaml_text"' in response.text
    assert "Save Policy" in response.text


def test_save_valid_policy_shows_success(client: TestClient) -> None:
    response = client.post(
        "/policy",
        data={"name": "test-policy", "yaml_text": VALID_YAML},
    )
    assert response.status_code == 200
    assert "Policy saved" in response.text
    assert "test-policy" in response.text


def test_save_invalid_yaml_shows_error(client: TestClient) -> None:
    response = client.post(
        "/policy",
        data={"name": "bad-policy", "yaml_text": "not: valid: yaml: {"},
    )
    assert response.status_code == 200
    assert "Policy Editor" in response.text
    # YAML preserved in textarea
    assert "not: valid: yaml: {" in response.text


def test_save_empty_name_shows_error(client: TestClient) -> None:
    response = client.post(
        "/policy",
        data={"name": "  ", "yaml_text": VALID_YAML},
    )
    assert response.status_code == 200
    assert "required" in response.text.lower()


def test_save_duplicate_policy_shows_already_exists(client: TestClient) -> None:
    yaml_for_dup = """\
base_currency: USD
buckets:
  core:
    targets:
      SPY: 0.70
      AGG: 0.30
"""
    client.post(
        "/policy",
        data={"name": "first", "yaml_text": yaml_for_dup},
    )
    response = client.post(
        "/policy",
        data={"name": "second", "yaml_text": yaml_for_dup},
    )
    assert response.status_code == 200
    assert "already exists" in response.text


def test_version_list_shows_after_save(client: TestClient) -> None:
    response = client.get("/policy")
    assert response.status_code == 200
    assert "test-policy" in response.text
    assert "No policies saved yet" not in response.text


def test_load_policy_by_id(client: TestClient) -> None:
    response = client.get("/policy")
    match = re.search(r'href="/policy\?id=(\d+)"', response.text)
    assert match is not None
    policy_id = match.group(1)

    response = client.get(f"/policy?id={policy_id}")
    assert response.status_code == 200
    # YAML loaded into editor textarea
    assert "IWDA.AS" in response.text or "SPY" in response.text


def test_load_nonexistent_policy_shows_empty_editor(client: TestClient) -> None:
    response = client.get("/policy?id=99999")
    assert response.status_code == 200
    assert "Policy Editor" in response.text


def test_policy_page_has_navigation(client: TestClient) -> None:
    response = client.get("/policy")
    assert response.status_code == 200
    assert 'href="/"' in response.text
