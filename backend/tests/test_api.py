"""Comprehensive backend test suite covering API contract, failover, caching, and persistence."""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from litellm import Choices, Message, ModelResponse, Usage
from litellm.caching.caching import Cache
import litellm

from app.config import settings
from app.db import init_db
from app.main import app


@pytest.fixture(autouse=True)
def clean_state(tmp_path):
    """Ensure clean isolated SQLite database and local cache for each test."""
    db_file = str(tmp_path / "test.db")
    settings.DATABASE_URL = f"sqlite:///{db_file}"
    settings.KEY_POOL = [
        ("key_1", "test-key-1"),
        ("key_2", "test-key-2"),
        ("key_3", "test-key-3"),
    ]
    settings.ENABLE_FAILURE_SIMULATION = True
    init_db()
    # Reset local cache
    litellm.cache = Cache(type="local")
    yield


@pytest.fixture
def client():
    return TestClient(app)


def make_mock_response(content: str, model: str = "gemini/gemini-2.5-flash-lite", prompt_tokens: int = 15, completion_tokens: int = 8):
    """Helper to create a standard ModelResponse object."""
    return ModelResponse(
        id="mock-resp-id",
        choices=[Choices(message=Message(content=content, role="assistant"))],
        model=model,
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


# --- 1. Health Endpoint Tests ---
def test_health_success(client: TestClient):
    """GET /health returns 200 with configured keys and cache enabled."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["keys_configured"] == 3
    assert data["cache_enabled"] is True


# --- 2. 422 Validation Error Tests ---
def test_422_empty_message(client: TestClient):
    """Empty message string must fail with 422."""
    resp = client.post("/chat", json={"session_id": "s-1", "message": ""})
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_422_whitespace_only_message(client: TestClient):
    """Whitespace-only message must fail with 422."""
    resp = client.post("/chat", json={"session_id": "s-1", "message": "   \n\t  "})
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_422_message_over_4000_chars(client: TestClient):
    """Message over 4000 chars after trimming must fail with 422."""
    long_msg = "a" * 4001
    resp = client.post("/chat", json={"session_id": "s-1", "message": long_msg})
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_422_missing_session_id(client: TestClient):
    """Missing session_id must fail with 422."""
    resp = client.post("/chat", json={"message": "hello world"})
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_422_bad_json(client: TestClient):
    """Malformed JSON payload must fail with 422."""
    resp = client.post(
        "/chat",
        content="not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    assert "detail" in resp.json()


# --- 3. 404 Unknown Session Test ---
def test_404_unknown_session(client: TestClient):
    """GET /sessions/{session_id}/messages on unknown session must return 404."""
    resp = client.get("/sessions/unknown-session-123/messages")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "session not found"}


# --- 4. Chat Success and History Tests ---
@patch("litellm.completion")
def test_chat_success_and_history(mock_completion, client: TestClient):
    """Test successful chat flow, response metadata, and session history format."""
    mock_completion.return_value = make_mock_response("Paris is the capital of France.", prompt_tokens=12, completion_tokens=7)

    payload = {
        "session_id": "session-test-1",
        "message": "What is the capital of France?",
    }
    resp = client.post("/chat", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["session_id"] == "session-test-1"
    assert data["reply"] == "Paris is the capital of France."
    meta = data["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "gemini/gemini-2.5-flash-lite"
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0
    assert meta["input_tokens"] == 12
    assert meta["output_tokens"] == 7
    assert isinstance(meta["latency_ms"], int)
    assert meta["latency_ms"] >= 1

    # Check history endpoint
    hist_resp = client.get("/sessions/session-test-1/messages")
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    assert hist["session_id"] == "session-test-1"
    messages = hist["messages"]
    assert len(messages) == 2

    # User message: oldest first, no metadata
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is the capital of France?"
    assert messages[0].get("metadata") is None

    # Assistant message: has required metadata
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Paris is the capital of France."
    assert messages[1]["metadata"] == {
        "resolution_source": "LIVE_INFERENCE",
        "input_tokens": 12,
        "output_tokens": 7,
    }


# --- 5. Response Caching Tests ---
def test_caching_behavior_and_cross_session(client: TestClient):
    """Test LiteLLM caching:
    - Same message hits cache on 2nd turn.
    - Hit reports LLM_CACHE, key_id=null, fallback_attempts=0.
    - Same first message across a new session hits cache.
    - Different message does not hit cache.
    """
    # 1. Turn 1: Live call (using mock_response in litellm for deterministic caching)
    with patch("litellm.completion", wraps=litellm.completion) as spied_completion:
        payload = {"session_id": "sess-cache-1", "message": "Explain quantum computing briefly"}
        # Provide a mock answer via litellm mock_response
        resp1 = client.post(
            "/chat",
            json=payload,
            headers={"X-Test-Mock": "mock"},
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
        assert data1["metadata"]["key_id"] == "key_1"
        reply_text = data1["reply"]

        # 2. Turn 2: Same initial question in a brand NEW session
        # Should hit LiteLLM cache!
        payload_new_session = {"session_id": "sess-cache-2", "message": "Explain quantum computing briefly"}
        resp2 = client.post("/chat", json=payload_new_session)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["metadata"]["resolution_source"] == "LLM_CACHE"
        assert data2["metadata"]["key_id"] is None
        assert data2["metadata"]["fallback_attempts"] == 0
        assert data2["reply"] == reply_text

        # 3. Different message in another session must NOT hit cache
        payload_different = {"session_id": "sess-cache-3", "message": "What is the speed of light?"}
        resp3 = client.post("/chat", json=payload_different)
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["metadata"]["resolution_source"] == "LIVE_INFERENCE"
        assert data3["metadata"]["key_id"] == "key_1"


# --- 6. Failover Hook Tests ---
def test_failover_single_key(client: TestClient):
    """X-Simulate-Failure: key_1=429 should fail over to key_2 with 200 OK."""
    headers = {"X-Simulate-Failure": "key_1=429"}
    payload = {"session_id": "sess-failover-1", "message": "Tell me a joke"}

    resp = client.post("/chat", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1
    assert data["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_all_keys_fail_returns_503_and_no_history(client: TestClient):
    """X-Simulate-Failure: *=429 makes every key fail.
    Must return 503 {"detail": "all providers unavailable"} and write nothing to DB.
    """
    headers = {"X-Simulate-Failure": "*=429"}
    payload = {"session_id": "sess-exhausted", "message": "Hello?"}

    resp = client.post("/chat", json=payload, headers=headers)
    assert resp.status_code == 503
    assert resp.json() == {"detail": "all providers unavailable"}

    # Verify no history written in database for this session
    hist_resp = client.get("/sessions/sess-exhausted/messages")
    # Session was never completed, messages table has zero rows for it
    if hist_resp.status_code == 200:
        assert len(hist_resp.json()["messages"]) == 0
    else:
        assert hist_resp.status_code == 404


def test_simulation_ignored_when_disabled(client: TestClient):
    """When ENABLE_FAILURE_SIMULATION=false, simulation header is ignored."""
    settings.ENABLE_FAILURE_SIMULATION = False
    headers = {"X-Simulate-Failure": "*=429"}
    payload = {"session_id": "sess-disabled-sim", "message": "Test simulation disabled"}

    resp = client.post("/chat", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["metadata"]["key_id"] == "key_1"
    assert resp.json()["metadata"]["fallback_attempts"] == 0


# --- 7. Token Tracking Per-Request ---
def test_per_request_tokens_not_cumulative(client: TestClient):
    """Two equal-length messages in two new sessions should report similar input_tokens."""
    p1 = {"session_id": "sess-tokens-1", "message": "Tell me three colors"}
    p2 = {"session_id": "sess-tokens-2", "message": "Tell me three shapes"}

    resp1 = client.post("/chat", json=p1)
    resp2 = client.post("/chat", json=p2)

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    t1 = resp1.json()["metadata"]["input_tokens"]
    t2 = resp2.json()["metadata"]["input_tokens"]
    assert abs(t1 - t2) <= 5, f"Tokens should be similar: {t1} vs {t2}"


# --- 8. Multi-Turn Memory & Isolation ---
@patch("litellm.completion")
def test_multiturn_memory_and_isolation(mock_completion, client: TestClient):
    """Verify history is accumulated per session and passed to LiteLLM, and sessions stay isolated."""
    mock_completion.side_effect = [
        make_mock_response("Nice to meet you Alice!"),
        make_mock_response("Your name is Alice."),
        make_mock_response("I don't know your name."),
    ]

    # Session A, Turn 1
    client.post("/chat", json={"session_id": "session-A", "message": "My name is Alice"})
    # Session A, Turn 2
    client.post("/chat", json={"session_id": "session-A", "message": "What is my name?"})

    # Check mock_completion call arguments on Turn 2
    # The messages parameter should contain Turn 1 history
    second_call_kwargs = mock_completion.call_args_list[1][1]
    messages_sent = second_call_kwargs["messages"]

    roles = [m["role"] for m in messages_sent]
    contents = [m["content"] for m in messages_sent]

    assert roles == ["system", "user", "assistant", "user"]
    assert contents[1] == "My name is Alice"
    assert contents[2] == "Nice to meet you Alice!"
    assert contents[3] == "What is my name?"

    # Session B, Turn 1: should be isolated and contain NO mention of Alice
    client.post("/chat", json={"session_id": "session-B", "message": "What is my name?"})
    third_call_kwargs = mock_completion.call_args_list[2][1]
    b_messages_sent = third_call_kwargs["messages"]
    b_contents = [m["content"] for m in b_messages_sent]
    assert "Alice" not in " ".join(b_contents)
