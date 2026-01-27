import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.errors import DataMissingError, PolicyError, ValidationError
from app.main import app


@pytest.fixture(scope="module")
def error_client() -> TestClient:
    """TestClient with test-only error routes added."""
    test_router = APIRouter(tags=["test"])

    @test_router.get("/test-error/validation")
    async def trigger_validation_error() -> None:
        raise ValidationError(
            message="Invalid portfolio weight specified",
            details="Weight must be between 0 and 1, got 1.5",
        )

    @test_router.get("/test-error/missing")
    async def trigger_missing_error() -> None:
        raise DataMissingError(
            message="Price data not found",
            details="No price data available for ticker XYZ",
        )

    @test_router.get("/test-error/policy")
    async def trigger_policy_error() -> None:
        raise PolicyError(
            message="Policy constraints are infeasible",
            details="Cannot satisfy both minimum and maximum constraints",
        )

    app.include_router(test_router)
    with TestClient(app) as client:
        yield client


def test_validation_error_renders_friendly_page(error_client: TestClient) -> None:
    response = error_client.get("/test-error/validation")
    assert response.status_code == 400
    assert "Validation Error" in response.text
    assert "Invalid portfolio weight specified" in response.text
    assert "Weight must be between 0 and 1" in response.text
    assert "Return Home" in response.text
    assert "Traceback" not in response.text


def test_data_missing_error_renders_friendly_page(error_client: TestClient) -> None:
    response = error_client.get("/test-error/missing")
    assert response.status_code == 400
    assert "Data Not Found" in response.text
    assert "Price data not found" in response.text
    assert "XYZ" in response.text


def test_policy_error_renders_friendly_page(error_client: TestClient) -> None:
    response = error_client.get("/test-error/policy")
    assert response.status_code == 400
    assert "Policy Error" in response.text
    assert "Policy constraints are infeasible" in response.text
