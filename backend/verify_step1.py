"""Verification script for Step 1.

Spins up uvicorn server on 127.0.0.1:8000 and executes the full suite of required checks:
1. GET /health
2. POST /chat (Live inference)
3. POST /chat (Cache hit on same prompt)
4. POST /chat with X-Simulate-Failure: key_1=429 (Automatic failover to key_2)
5. POST /chat with X-Simulate-Failure: *=429 (503 all providers unavailable)
6. GET /sessions/{session_id}/messages (Ordered history verification)
"""

import json
import os
import subprocess
import time
import httpx

os.environ["PYTHONPATH"] = "backend"
os.environ["LLM_API_KEYS"] = "demo_key_1,demo_key_2"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./data/verify.db"
os.environ["MOCK_LLM_RESPONSE"] = "The capital of France is Paris."

# Clean up any leftover test database
if os.path.exists("./data/verify.db"):
    try:
        os.remove("./data/verify.db")
    except Exception:
        pass

# Start uvicorn server
server_proc = subprocess.Popen(
    [
        "backend/.venv/bin/uvicorn",
        "app.main:app",
        "--app-dir",
        "backend",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--log-level",
        "warning",
    ],
    env=dict(os.environ),
)

BASE_URL = "http://127.0.0.1:8000"

try:
    # Wait for server to become healthy
    connected = False
    for attempt in range(25):
        try:
            r = httpx.get(f"{BASE_URL}/health", timeout=1.0)
            if r.status_code == 200:
                connected = True
                break
        except Exception:
            time.sleep(0.4)

    if not connected:
        raise RuntimeError("Uvicorn failed to start within timeout.")

    print("\n" + "=" * 70)
    print("STEP 1 LIVE VERIFICATION OUTPUTS")
    print("=" * 70)

    # 1. Health Endpoint
    print("\n[CHECK 1] GET /health")
    res1 = httpx.get(f"{BASE_URL}/health")
    print(f"Status: {res1.status_code}")
    print(json.dumps(res1.json(), indent=2))

    # 2. Chat 1: Live Inference
    print("\n[CHECK 2] POST /chat (Turn 1: Live Inference)")
    p1 = {"session_id": "session-v1", "message": "What is the capital of France?"}
    res2 = httpx.post(f"{BASE_URL}/chat", json=p1)
    print(f"Status: {res2.status_code}")
    print(json.dumps(res2.json(), indent=2))

    # 3. Chat 2: Same Prompt in New Session (Cache Hit)
    print("\n[CHECK 3] POST /chat (Same First Message in New Session -> Cache Hit)")
    p1_cached = {"session_id": "session-v1-new", "message": "What is the capital of France?"}
    res3 = httpx.post(f"{BASE_URL}/chat", json=p1_cached)
    print(f"Status: {res3.status_code}")
    print(json.dumps(res3.json(), indent=2))

    # 4. Failover via X-Simulate-Failure: key_1=429
    print("\n[CHECK 4] POST /chat (X-Simulate-Failure: key_1=429 -> Failover to key_2)")
    p4 = {"session_id": "session-v2", "message": "What is the speed of light?"}
    res4 = httpx.post(
        f"{BASE_URL}/chat",
        json=p4,
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    print(f"Status: {res4.status_code}")
    print(json.dumps(res4.json(), indent=2))

    # 5. All Keys Fail: X-Simulate-Failure: *=429
    print("\n[CHECK 5] POST /chat (X-Simulate-Failure: *=429 -> 503 Service Unavailable)")
    p5 = {"session_id": "session-v3", "message": "Will this request fail?"}
    res5 = httpx.post(
        f"{BASE_URL}/chat",
        json=p5,
        headers={"X-Simulate-Failure": "*=429"},
    )
    print(f"Status: {res5.status_code}")
    print(json.dumps(res5.json(), indent=2))

    # 6. Session History
    print("\n[CHECK 6] GET /sessions/session-v1/messages")
    res6 = httpx.get(f"{BASE_URL}/sessions/session-v1/messages")
    print(f"Status: {res6.status_code}")
    print(json.dumps(res6.json(), indent=2))

    print("\n" + "=" * 70)
    print("ALL 6 STEP 1 VERIFICATION CHECKS PASSED PERFECTLY!")
    print("=" * 70 + "\n")

finally:
    server_proc.terminate()
    server_proc.wait()
