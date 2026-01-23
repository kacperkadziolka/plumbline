from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, Any]:
    with TestClient(app) as c:
        yield c
