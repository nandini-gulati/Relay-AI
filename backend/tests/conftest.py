"""Pytest fixtures for Relay backend testing."""

import os
import pytest
from fastapi.testclient import TestClient

# Ensure offline mock mode for litellm
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["LLM_API_KEYS"] = "test-key-1,test-key-2,test-key-3"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"
os.environ["MOCK_LLM_RESPONSE"] = "Mocked LLM reply for testing"

from app.config import settings
from app.db import init_db
from app.main import app


@pytest.fixture(autouse=True)
def setup_test_db():
    """Reset database and settings for each test."""
    settings.DATABASE_URL = "sqlite:///:memory:"
    settings.KEY_POOL = [
        ("key_1", "test-key-1"),
        ("key_2", "test-key-2"),
        ("key_3", "test-key-3"),
    ]
    settings.ENABLE_FAILURE_SIMULATION = True
    init_db()
    yield


@pytest.fixture
def client():
    """Provide a TestClient for FastAPI routes."""
    return TestClient(app)
