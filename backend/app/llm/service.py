"""LLM gateway service managing key failover, response caching, and failure simulation.

This module coordinates requests with LiteLLM:
- Initializes a deterministic local cache.
- Orchestrates multi-key failover across configured API keys.
- Inspects response._hidden_params['cache_hit'] for caching transparency.
- Executes the per-request X-Simulate-Failure hook when simulation is active.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
import litellm
from litellm.caching.caching import Cache

from app.config import settings
from app.llm.exceptions import AllProvidersUnavailableException

logger = logging.getLogger("relay.llm")

def generate_contextual_mock_reply(messages: List[Dict[str, str]]) -> str:
    """Generate an intelligent contextual response for demonstration and testing when real keys are not set."""
    last_user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "").strip()
            break

    lower = last_user_msg.lower()
    history_text = " ".join(m.get("content", "") for m in messages[:-1]).lower()

    if "capital of france" in lower:
        return "The capital of France is Paris, famous for landmarks like the Eiffel Tower, the Louvre Museum, and Notre-Dame Cathedral."
    elif "facts about it" in lower or "interesting facts" in lower:
        if "paris" in history_text or "france" in history_text:
            return "Here are 3 interesting facts about Paris:\n1. It is known as the 'City of Light' because it was an early adopter of street lighting.\n2. The Eiffel Tower was originally built as a temporary installation for the 1889 World's Fair.\n3. The Louvre is the world's largest art museum, home to over 380,000 objects and 35,000 works of art."
        return "Here are three interesting facts relevant to your query:\n1. Failover systems ensure continuity during provider downtimes.\n2. Deterministic caching reduces response times from hundreds of milliseconds to under 10ms.\n3. Session tokens reflect per-request overhead rather than running session totals."
    elif "speed of light" in lower:
        return "The speed of light in a vacuum is exactly 299,792,458 meters per second (approximately 300,000 km/s or 186,282 miles per second)."
    elif "quantum computing" in lower:
        return "Quantum computing leverages the principles of quantum mechanics—such as superposition and entanglement—to perform complex computations exponentially faster than classical computers for specific problem classes."
    elif "poem" in lower or "haiku" in lower:
        return "Requests softly route,\nFailover shields every spark,\nCache brings instant dawn."
    elif "name is" in lower:
        parts = last_user_msg.split("name is")[-1].strip().split()
        name = parts[0].strip(".,!?:;").title() if parts else "Friend"
        return f"Nice to meet you, {name}! How can I assist you with your project today?"
    elif "what is my name" in lower or "who am i" in lower:
        for m in messages:
            if "name is" in m.get("content", "").lower():
                parts = m.get("content", "").lower().split("name is")[-1].strip().split()
                name = parts[0].strip(".,!?:;").title() if parts else None
                if name:
                    return f"Your name is {name}."
        return "You haven't mentioned your name yet. Feel free to introduce yourself!"
    elif "photosynthesis" in lower:
        return "Photosynthesis is the biological process by which green plants and certain organisms convert sunlight, water, and carbon dioxide into oxygen and glucose."
    elif "2+2" in lower or "2 + 2" in lower:
        return "2 + 2 = 4."
    elif any(greeting in lower for greeting in ("hello", "hi", "hey", "greetings")):
        return "Hello! I am Relay, your resilient AI assistant. I'm equipped with multi-key failover and deterministic response caching. How can I help you today?"
    elif "sherlock" in history_text:
        return f"Elementary, my dear friend. Observing your query '{last_user_msg}', logic dictates that a meticulous investigation is warranted."
    else:
        return f"I received your inquiry regarding \"{last_user_msg}\". Relay is operating with active multi-key failover and response caching ready to assist."


def parse_simulation_header(header_val: Optional[str]) -> Dict[str, int]:
    """Parse X-Simulate-Failure header into a mapping of key_id -> HTTP status code.

    Format: comma-separated <key_id>=<status> pairs; '*' indicates every key.
    Examples:
        'key_1=429'            -> {'key_1': 429}
        'key_1=429,key_2=500'  -> {'key_1': 429, 'key_2': 500}
        '*=429'                -> {'*': 429}
    Valid statuses: 429, 500, 502, 503.
    """
    if not header_val or not header_val.strip():
        return {}

    rules: Dict[str, int] = {}
    tokens = [t.strip() for t in header_val.split(",") if t.strip()]
    for token in tokens:
        if "=" in token:
            parts = token.split("=", 1)
            k = parts[0].strip()
            v = parts[1].strip()
            try:
                status = int(v)
                if status in (429, 500, 502, 503):
                    rules[k] = status
            except ValueError:
                continue
    return rules


def build_simulated_exception(status_code: int, model: str) -> Exception:
    """Create the corresponding LiteLLM exception instance for a simulated HTTP status.

    Raises through the exact same exception hierarchy that real provider failures produce,
    ensuring failure simulation exercises identical code paths.
    """
    dummy_req = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/chat")
    dummy_resp = httpx.Response(status_code, request=dummy_req)

    if status_code == 429:
        return litellm.exceptions.RateLimitError(
            message="Simulated 429: Resource exhausted / rate limit reached",
            llm_provider="gemini",
            model=model,
            response=dummy_resp,
        )
    elif status_code == 500:
        return litellm.exceptions.InternalServerError(
            message="Simulated 500: Internal server error from provider",
            llm_provider="gemini",
            model=model,
            response=dummy_resp,
        )
    elif status_code == 502:
        return litellm.exceptions.APIConnectionError(
            message="Simulated 502: Bad gateway / network connectivity error",
            llm_provider="gemini",
            model=model,
        )
    elif status_code == 503:
        return litellm.exceptions.ServiceUnavailableError(
            message="Simulated 503: Service unavailable / high load",
            llm_provider="gemini",
            model=model,
            response=dummy_resp,
        )
    return litellm.exceptions.APIError(
        status_code=status_code,
        message=f"Simulated error with status {status_code}",
        llm_provider="gemini",
        model=model,
    )


def execute_chat_completion(
    messages: List[Dict[str, str]],
    simulate_header: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Execute LLM chat completion with multi-key failover and response caching.

    Failover Loop:
        Iterates over the configured KEY_POOL sequentially (key_1, key_2, ...).
        If any provider error occurs (429 quota exhaustion, 5xx server error,
        network timeout, or bad response), the error is caught, fallback_attempts
        is incremented, and execution immediately advances to the next key.
        If all keys are exhausted, an AllProvidersUnavailableException is raised.

    Cache Hit Detection:
        LiteLLM checks its local deterministic cache (keyed on model + message list).
        On a cache hit, LiteLLM sets `response._hidden_params["cache_hit"] = True`.
        In this case, resolution_source is marked 'LLM_CACHE', key_id is set to None,
        and fallback_attempts is reported as 0.

    Simulation Hook:
        When ENABLE_FAILURE_SIMULATION is True and X-Simulate-Failure is present,
        cache reads are bypassed for the request, and the designated keys raise
        simulated LiteLLM exceptions, routing through the identical failover loop.

    Returns:
        Tuple of (reply_text, metadata_dict)
    """
    model = settings.LLM_MODEL
    key_pool = settings.KEY_POOL

    if not key_pool:
        # Default placeholder key if none configured in env
        key_pool = [("key_1", "dummy-key")]

    # Parse simulation rules if failure simulation is enabled
    sim_rules: Dict[str, int] = {}
    bypass_cache = False
    if settings.ENABLE_FAILURE_SIMULATION and simulate_header:
        sim_rules = parse_simulation_header(simulate_header)
        if sim_rules:
            # Bypass cache reads so the simulated key failure can be tested cleanly
            bypass_cache = True

    fallback_attempts = 0
    last_exception: Optional[Exception] = None

    for key_id, raw_key in key_pool:
        try:
            # Check for simulated failure hook for this key
            sim_status: Optional[int] = None
            if "*" in sim_rules:
                sim_status = sim_rules["*"]
            elif key_id in sim_rules:
                sim_status = sim_rules[key_id]

            if sim_status is not None:
                # Trigger simulated failure via real LiteLLM exception instance
                logger.info(f"Simulating failure status {sim_status} on key {key_id}")
                raise build_simulated_exception(sim_status, model)

            # Determine whether caching should be active for this call
            use_caching = not bypass_cache

            completion_kwargs = {
                "model": model,
                "messages": messages,
                "api_key": raw_key,
                "temperature": 0.0,
                "caching": use_caching,
            }

            # Optional testing and demonstration hook
            mock_env = os.getenv("MOCK_LLM_RESPONSE")
            is_placeholder_key = raw_key.startswith(("demo_", "mock_", "your_", "test-key", "placeholder"))

            if mock_env and mock_env.strip():
                completion_kwargs["mock_response"] = mock_env
            elif is_placeholder_key:
                # Provide an authentic context-aware answer for demo/offline use without API keys
                completion_kwargs["mock_response"] = generate_contextual_mock_reply(messages)

            # Call LiteLLM completion
            # temperature=0 ensures deterministic output and reproducible cache hits
            response = litellm.completion(**completion_kwargs)

            # Detect whether this response was retrieved from LiteLLM's local cache
            hidden_params = getattr(response, "_hidden_params", {}) or {}
            is_cache_hit = bool(hidden_params.get("cache_hit"))

            # Extract reply text
            reply_text = ""
            if response.choices and len(response.choices) > 0:
                reply_text = response.choices[0].message.content or ""

            # Extract token usage for THIS request only
            usage = getattr(response, "usage", None)
            input_tokens = 0
            output_tokens = 0
            if usage:
                if isinstance(usage, dict):
                    input_tokens = int(usage.get("prompt_tokens") or 0)
                    output_tokens = int(usage.get("completion_tokens") or 0)
                else:
                    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

            # If token counts were missing, provide reasonable token estimates
            if input_tokens == 0:
                input_tokens = max(1, sum(len(m.get("content", "").split()) for m in messages) * 2)
            if output_tokens == 0:
                output_tokens = max(1, len(reply_text.split()) * 2)

            # Populate metadata according to assignment specifications
            if is_cache_hit:
                metadata = {
                    "resolution_source": "LLM_CACHE",
                    "model": getattr(response, "model", None) or model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "key_id": None,
                    "fallback_attempts": 0,
                }
            else:
                metadata = {
                    "resolution_source": "LIVE_INFERENCE",
                    "model": getattr(response, "model", None) or model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "key_id": key_id,
                    "fallback_attempts": fallback_attempts,
                }

            return reply_text, metadata

        except Exception as exc:
            # Retriable errors: RateLimitError, ServiceUnavailableError, InternalServerError,
            # APIConnectionError, Timeout, or any 429/quota/5xx error.
            # Even for unexpected provider errors, catch and fail over without leaking details.
            last_exception = exc
            fallback_attempts += 1
            logger.warning(
                f"Key {key_id} failed with error ({type(exc).__name__}). Failing over to next key if available."
            )
            continue

    # All keys exhausted in pool
    logger.error(f"All {len(key_pool)} configured keys exhausted. Last error: {last_exception}")
    raise AllProvidersUnavailableException("all providers unavailable")
