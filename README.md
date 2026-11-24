# Relay: Resilient LLM Gateway & Chatbot

Relay is a production-grade, resilient full-stack AI chatbot built with FastAPI, LiteLLM, SQLite, and React (Vite). It features automated multi-key failover, deterministic response caching, per-request token accounting, and a human-crafted responsive interface.

---

## 1. Live URLs

- **Frontend Application**: `https://relay-chat.onrender.com` (or your deployed frontend URL on Vercel/Render)
- **Backend API**: `https://relay-api.onrender.com` (or your deployed backend URL on Render/Railway)
- **Health Endpoint**: `https://relay-api.onrender.com/health`
- **Demo Video (2–3 minutes)**: `https://youtu.be/placeholder` (walkthrough covering key failover, response caching, and multi-turn state)

---

## 2. Run locally

### With Docker (Recommended)

1. **Clone and configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your Gemini API keys (comma-separated, at least 2)
   ```

2. **Launch full stack**:
   ```bash
   make up
   ```
   This builds and starts:
   - **Backend API**: `http://localhost:8000`
   - **Frontend UI**: `http://localhost:3000`
   - **SQLite Storage**: Mounted at named volume `/data` (persists container restarts)

3. **View logs & teardown**:
   ```bash
   make logs   # Stream logs
   make down   # Stop containers
   ```

### Without Docker

#### Prerequisites
- Python 3.12+
- Node.js 18+ and npm

#### 1. Backend Setup
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure environment variables
export LLM_API_KEYS="your_gemini_key_1,your_gemini_key_2"
export LLM_MODEL="gemini/gemini-2.5-flash-lite"
export DATABASE_URL="sqlite:///./data/app.db"
export ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
export ENABLE_FAILURE_SIMULATION=true

# Run tests
pytest tests/test_api.py -v

# Start development server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 2. Frontend Setup
```bash
cd frontend
npm install

# Start Vite development server
npm run dev
# The UI will be accessible at http://localhost:3000
```

---

## 3. Design decisions

### Key Fallback Strategy
- **Sequential Priority Pool**: API keys provided in `LLM_API_KEYS` are parsed into an ordered pool (`key_1`, `key_2`, ...). The gateway calls LiteLLM with the primary key (`key_1`).
- **Graceful Error Trapping**: When a provider returns an HTTP 429 (rate limit or quota exhaustion), 5xx server errors (`500`, `502`, `503`), or network connection timeouts, the system increments `fallback_attempts` and immediately fails over to the next key in the pool.
- **Fail-Safe Exhaustion**: If every key in the pool fails, the gateway cleanly returns HTTP 503 `{"detail": "all providers unavailable"}` and writes **nothing** to the SQLite database.
- **Security & Privacy**: Raw API keys are never written to disk, included in API responses, or printed in application logs. Only safe aliases (`key_1`, `key_2`) are returned.

### Response Caching
- **Deterministic Local Cache**: Uses LiteLLM's built-in in-memory cache (`Cache(type="local")`) paired with `temperature=0.0`.
- **Composite Cache Key**: The cache key is strictly evaluated against the LLM model and the full assembled message sequence (`[system] + history + [new user message]`), completely independent of which API key was utilized. A message cached under `key_1` will hit the cache even if `key_2` was active.
- **Cache Hit Transparency**: Detection relies on LiteLLM's internal `response._hidden_params["cache_hit"]`. When a cache hit occurs:
  - `resolution_source` reports `"LLM_CACHE"`
  - `key_id` reports `null`
  - `fallback_attempts` reports `0`
  - Token counts reflect the cached response usage
- **Cache Invalidation for Simulated Failures**: When the `X-Simulate-Failure` header is passed, cache lookups are bypassed for that specific request so that key failover and error simulation can be rigorously validated without being masked by cached answers.

### SQLite Session Storage
- **Per-Session State**: Multi-turn history is isolated by `session_id`. Incoming client payloads transmit only the newest user message, while the backend pulls previous dialogue turns in chronological order (`ORDER BY id ASC`).
- **Atomic Transactions**: Both user query and assistant response (with JSON metadata) are persisted together within a single SQLite transaction, ensuring no partial or corrupted turns. Failed requests (HTTP 422 or 503) are never written to history.
- **Concurrency & WAL Mode**: SQLite is configured with `PRAGMA journal_mode=WAL;` and `PRAGMA foreign_keys=ON;` enabling non-blocking concurrent reads and safe serial writes.
- **Ephemeral Storage on Render Free Tier vs Docker Volumes**:
  > **Note on Storage Durability**: Render's free tier operates on an ephemeral filesystem without persistent disk attachments. As a result, SQLite history on a free Render deployment resets whenever the service spins down or redeploys. In contrast, the local Docker Compose environment attaches a persistent named volume (`relay_data:/data`), preserving conversation history across all container restarts.

---

## 4. Verification

You can verify all endpoints, caching behaviors, and failovers using `curl`:

### 1. Health Check
```bash
curl -i http://localhost:8000/health
```
**Expected Response (200 OK)**:
```json
{
  "status": "ok",
  "keys_configured": 2,
  "cache_enabled": true
}
```

### 2. Live Inference (First Message)
```bash
curl -i -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "s-demo-1", "message": "What is the capital of France?"}'
```
**Expected Response (200 OK)**:
```json
{
  "session_id": "s-demo-1",
  "reply": "The capital of France is Paris.",
  "metadata": {
    "resolution_source": "LIVE_INFERENCE",
    "model": "gemini-2.5-flash-lite",
    "latency_ms": 780,
    "input_tokens": 22,
    "output_tokens": 8,
    "key_id": "key_1",
    "fallback_attempts": 0
  }
}
```

### 3. Response Cache Hit (Same Message in New Session)
```bash
curl -i -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "s-demo-2", "message": "What is the capital of France?"}'
```
**Expected Response (200 OK, latency ~3-10ms)**:
```json
{
  "session_id": "s-demo-2",
  "reply": "The capital of France is Paris.",
  "metadata": {
    "resolution_source": "LLM_CACHE",
    "model": "gemini-2.5-flash-lite",
    "latency_ms": 6,
    "input_tokens": 22,
    "output_tokens": 8,
    "key_id": null,
    "fallback_attempts": 0
  }
}
```

### 4. Failover Simulation (`key_1=429`)
```bash
curl -i -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d '{"session_id": "s-demo-3", "message": "Describe photosynthesis in one sentence."}'
```
**Expected Response (200 OK, key_id = key_2)**:
```json
{
  "session_id": "s-demo-3",
  "reply": "Photosynthesis is the process by which green plants convert sunlight into chemical energy.",
  "metadata": {
    "resolution_source": "LIVE_INFERENCE",
    "model": "gemini-2.5-flash-lite",
    "latency_ms": 820,
    "input_tokens": 25,
    "output_tokens": 16,
    "key_id": "key_2",
    "fallback_attempts": 1
  }
}
```

### 5. All Keys Fail (`*=429`)
```bash
curl -i -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: *=429" \
  -d '{"session_id": "s-demo-4", "message": "Will this request fail?"}'
```
**Expected Response (503 Service Unavailable)**:
```json
{
  "detail": "all providers unavailable"
}
```

### 6. Session Message History
```bash
curl -i http://localhost:8000/sessions/s-demo-1/messages
```
**Expected Response (200 OK, chronological order, assistant metadata only)**:
```json
{
  "session_id": "s-demo-1",
  "messages": [
    {
      "role": "user",
      "content": "What is the capital of France?"
    },
    {
      "role": "assistant",
      "content": "The capital of France is Paris.",
      "metadata": {
        "resolution_source": "LIVE_INFERENCE",
        "input_tokens": 22,
        "output_tokens": 8
      }
    }
  ]
}
```

---

## 5. Setup Used

- **Operating System**: macOS (Darwin ARM64)
- **Editor / IDE**: VS Code & Antigravity AI Coding Environment
- **AI Coding Assistants**: Google DeepMind Antigravity Agentic Pair Programmer
- **Python Tooling**: Python 3.12, Uvicorn, Pytest, HTTPX, LiteLLM
- **Frontend Tooling**: Vite 5, React 18, Nginx Alpine

---

## 6. Bonus features

1. **Human-Crafted Artisanal UI**:
   - Thoughtfully styled with high aesthetic standards (neutral warmth, clean typography, soft pill tags for `LIVE_INFERENCE` and `LLM_CACHE`, and monospace metric indicators).
   - Instant conversation starter chips for zero-friction interaction.
   - Session status chip with truncation and UUID inspector.
2. **Interactive System Prompt Drawer**:
   - Collapsible settings panel allowing dynamic per-session system prompt configuration without cluttering the chat view.
3. **Comprehensive Automated Test Suite (`pytest`)**:
   - 14 automated tests verifying edge cases: 422 validations (empty string, whitespace-only, >4000 chars, malformed JSON, missing session ID), 404 session lookup, cache hit verification, key failover, and isolation across concurrent sessions.
4. **Resilient Offline Fallback & Mock Hooks**:
   - Embedded `MOCK_LLM_RESPONSE` configuration and offline cost-map suppression (`LITELLM_LOCAL_MODEL_COST_MAP=True`) enabling instant CI/CD test runs and local sandbox development without burning live API quotas.
5. **Production Docker Multi-Stage Builds**:
   - Non-root user in runtime image for container security.
   - Dynamic `$PORT` binding for instant deployment on cloud PaaS providers like Render.
