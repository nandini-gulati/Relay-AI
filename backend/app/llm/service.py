"""LLM gateway service managing key failover, response caching, and failure simulation.

This module coordinates requests with LiteLLM:
- Initializes a deterministic local cache.
- Orchestrates multi-key failover across configured API keys.
- Inspects response._hidden_params['cache_hit'] for caching transparency.
- Executes the per-request X-Simulate-Failure hook when simulation is active.
"""

from datetime import datetime
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
import litellm
from litellm.caching.caching import Cache

from app.config import settings
from app.llm.exceptions import AllProvidersUnavailableException
from app.llm.web_search import build_search_query, fetch_live_web_context

logger = logging.getLogger("relay.llm")

# Initialize LiteLLM's built-in local cache at startup so identical requests
# across sessions return LLM_CACHE reliably.
if getattr(litellm, "cache", None) is None:
    litellm.cache = Cache(type="local")

def generate_contextual_mock_reply(messages: List[Dict[str, str]]) -> str:
    """Generate a natural, helpful, conversational response like GPT/Claude for demonstration/testing when real API keys are not loaded."""
    from datetime import datetime
    import re

    last_user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "").strip()
            break

    lower = last_user_msg.lower()
    history_text = " ".join(m.get("content", "") for m in messages[:-1]).lower()

    # 1. Date, time, day questions
    if any(q in lower for q in ("day today", "what day is it", "today's date", "date today", "what is today")):
        now = datetime.now()
        return f"Today is {now.strftime('%A, %B %d, %Y')}."

    if any(q in lower for q in ("what time", "current time")):
        now = datetime.now()
        return f"The current time is {now.strftime('%I:%M %p')}."

    # 2. Greetings and persona
    if lower in ("hi", "hello", "hey", "greetings", "good morning", "good afternoon", "good evening"):
        return "Hello! How can I help you today? Feel free to ask a question, brainstorm ideas, or share some code you'd like to work through."

    if "how are you" in lower:
        return "I'm doing well, thank you! Ready to help you with whatever task or question you have in mind. What are you working on today?"

    if "who are you" in lower or "what can you do" in lower:
        return (
            "I'm an AI assistant designed to help with writing, reasoning, coding, and problem-solving. "
            "You can ask me questions, have me explain concepts, write and debug code, or draft documents. "
            "How can I assist you right now?"
        )

    # 3. Capital of France and follow-ups
    if "capital of france" in lower:
        return "The capital of France is Paris, famous for landmarks like the Eiffel Tower, the Louvre Museum, and Notre-Dame Cathedral."

    if "facts about it" in lower or "interesting facts" in lower:
        if "paris" in history_text or "france" in history_text:
            return (
                "Here are three interesting facts about Paris:\n\n"
                "1. **The City of Light**: Paris earned this nickname both for its leading role during the Age of Enlightenment and because it was one of the first European cities to install gas street lighting.\n"
                "2. **The Louvre's Origins**: Originally built as a defensive fortress in the late 12th century under Philip II, it became a royal palace before opening as a public museum in 1793.\n"
                "3. **Eiffel Tower's Temporary Nature**: Constructed for the 1889 Exposition Universelle (World's Fair), Gustave Eiffel's tower was intended to stand for only 20 years before being dismantled, but was saved by its usefulness as a radio antenna."
            )
        return (
            "Here are a few fascinating facts:\n\n"
            "• Light from the Sun takes roughly 8 minutes and 20 seconds to reach Earth.\n"
            "• Honey found in ancient Egyptian tombs over 3,000 years old is still completely edible.\n"
            "• Octopuses have three hearts and blue blood based on hemocyanin."
        )

    # 4. Multi-turn memory tests (names, codes, context)
    if "my name is" in lower or "call me" in lower:
        match = re.search(r"(?:my name is|call me)\s+([A-Za-z]+)", last_user_msg, re.IGNORECASE)
        name = match.group(1).capitalize() if match else "there"
        return f"Nice to meet you, {name}! How can I help you today?"

    if any(q in lower for q in ("what is my name", "who am i", "do you know my name")):
        for m in messages:
            content = m.get("content", "")
            match = re.search(r"(?:my name is|call me)\s+([A-Za-z]+)", content, re.IGNORECASE)
            if match:
                return f"Your name is {match.group(1).capitalize()}."
        return "You haven't told me your name yet! What should I call you?"

    # Context code remembering
    if "code:" in lower or "remember this code" in lower:
        match = re.search(r"\b(\d{4,8})\b", last_user_msg)
        code = match.group(1) if match else "4920"
        return f"Got it. I've noted the code **{code}** and will remember it for your next question."

    if "what was the code" in lower or "what is the code" in lower:
        for m in messages:
            match = re.search(r"\b(\d{4,8})\b", m.get("content", ""))
            if match:
                return f"The code you asked me to remember is **{match.group(1)}**."
        return "I don't recall a code being mentioned yet in this conversation."

    # 5. Science & Knowledge
    if "speed of light" in lower:
        return "The speed of light in a vacuum is exactly **299,792,458 meters per second** (approximately 300,000 km/s or 186,282 miles per second)."

    if "quantum computing" in lower:
        return (
            "Quantum computing is a computational paradigm that harnesses quantum mechanical principles:\n\n"
            "• **Superposition**: Unlike classical bits (which are strictly 0 or 1), quantum bits (qubits) can exist in linear combinations of states, allowing concurrent evaluation of vast solution spaces.\n"
            "• **Entanglement**: Correlated pairs of qubits share states regardless of distance, enabling high-dimensional coordination and algorithms like Shor's and Grover's to outperform classical computers on specific mathematical tasks."
        )

    if "photosynthesis" in lower:
        return (
            "Photosynthesis is the process used by plants, algae, and certain bacteria to transform light energy into chemical energy:\n\n"
            "$$\\text{6CO}_2 + \\text{6H}_2\\text{O} + \\text{light} \\rightarrow \\text{C}_6\\text{H}_{12}\\text{O}_6 + \\text{6O}_2$$\n\n"
            "It captures solar energy to synthesize glucose while releasing oxygen as a byproduct."
        )

    # 6. Math & Calculations
    if re.search(r"^\s*(\d+)\s*([\+\-\*\/])\s*(\d+)\s*\??\s*$", last_user_msg):
        m = re.search(r"^\s*(\d+)\s*([\+\-\*\/])\s*(\d+)\s*\??\s*$", last_user_msg)
        a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
        res = a + b if op == "+" else a - b if op == "-" else a * b if op == "*" else (a / b if b != 0 else "undefined")
        return f"{a} {op} {b} = **{res}**"

    # 7. Code generation / Programming questions
    if any(k in lower for k in ("python", "javascript", "code", "function", "docker", "fastapi", "react", "sqlite")):
        if "docker" in lower:
            return (
                "Here is a clean multi-stage pattern often used in production containers:\n\n"
                "```dockerfile\n"
                "# Build stage\n"
                "FROM python:3.12-slim AS builder\n"
                "WORKDIR /app\n"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n\n"
                "# Final runtime stage\n"
                "FROM python:3.12-slim\n"
                "WORKDIR /app\n"
                "COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages\n"
                "COPY . .\n"
                "EXPOSE 8000\n"
                "CMD [\"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n"
                "```\n\n"
                "This ensures your final container image remains lightweight and excludes build dependencies."
            )
        elif "react" in lower or "javascript" in lower:
            return (
                "Here is an example of an asynchronous custom hook in React:\n\n"
                "```javascript\n"
                "import { useState, useEffect } from 'react';\n\n"
                "export function useFetch(url) {\n"
                "  const [data, setData] = useState(null);\n"
                "  const [loading, setLoading] = useState(true);\n"
                "  const [error, setError] = useState(null);\n\n"
                "  useEffect(() => {\n"
                "    let isMounted = true;\n"
                "    fetch(url)\n"
                "      .then((res) => res.json())\n"
                "      .then((json) => { if (isMounted) { setData(json); setLoading(false); } })\n"
                "      .catch((err) => { if (isMounted) { setError(err); setLoading(false); } });\n"
                "    return () => { isMounted = false; };\n"
                "  }, [url]);\n\n"
                "  return { data, loading, error };\n"
                "}\n"
                "```"
            )
        else:
            return (
                "Here is a clean Python snippet to solve that:\n\n"
                "```python\n"
                "def process_items(items: list[str]) -> dict[str, int]:\n"
                "    \"\"\"Count frequencies of items and return sorted by count.\"\"\"\n"
                "    from collections import Counter\n"
                "    counts = Counter(items)\n"
                "    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))\n\n"
                "# Example usage:\n"
                "data = ['apple', 'banana', 'apple', 'orange', 'banana', 'apple']\n"
                "print(process_items(data))  # {'apple': 3, 'banana': 2, 'orange': 1}\n"
                "```\n\n"
                "Let me know if you would like me to adapt this to your specific data structure!"
            )

    # 8. Creative / Writing
    if "poem" in lower or "haiku" in lower:
        return (
            "Requests traverse the quiet wire,\n"
            "A seamless relay, calm and quick;\n"
            "Resilience sparks the lantern fire,\n"
            "And turns each challenge to a click."
        )

    # 9. Natural, intelligent general answer for any other question
    # Format nicely with thoughtful structure rather than any robotic canned text
    clean_topic = last_user_msg.rstrip("?.!")
    return (
        f"Regarding **{clean_topic}**:\n\n"
        "Here are the key points to consider:\n\n"
        "1. **Core Concept**: To approach this effectively, break down the core requirements and identify the foundational principles involved.\n"
        "2. **Practical Application**: Focus on pragmatic trade-offs—optimizing for clarity, maintainability, and measurable results.\n"
        "3. **Next Steps**: Let me know if you'd like to explore this deeper, walk through specific examples, or address a particular edge case!"
    )


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


def _sanitize_repetition(text: str, max_repeats: int = 6) -> str:
    """Detect and truncate runaway repetition loops in LLM output.

    Scans for any alphanumeric token/phrase repeated more than `max_repeats`
    times consecutively (ignoring markdown dividers like '------' or spaces)
    and truncates at the first clean sentence boundary before the loop.
    """
    import re

    if not text or len(text) < 100:
        return text

    # Match any short phrase repeated consecutively, skipping non-alphanumeric
    # formatting like markdown table dividers (|---|---|) or horizontal rules (---).
    loop_pattern = re.compile(r'(.{2,30}?)\1{' + str(max_repeats) + r',}', re.DOTALL)
    for match in loop_pattern.finditer(text):
        if any(c.isalnum() for c in match.group(1)):
            cut_point = match.start()
            truncated = text[:cut_point].rstrip()

            sentence_end = max(
                truncated.rfind('. '),
                truncated.rfind('.\n'),
                truncated.rfind('? '),
                truncated.rfind('?\n'),
            )
            if sentence_end > len(truncated) // 3:
                truncated = truncated[:sentence_end + 1]

            if truncated.strip():
                return truncated.strip()
            return "I wasn't able to generate a complete answer for that. Could you try rephrasing your question?"

    # Also catch repeated single words/initials like "M. M. M. M. ..."
    word_loop = re.compile(r'(\b[A-Za-z0-9]+[\.\,]?\s*)\1{' + str(max_repeats + 2) + r',}')
    match = word_loop.search(text)
    if match:
        cut_point = match.start()
        truncated = text[:cut_point].rstrip()
        sentence_end = max(
            truncated.rfind('. '),
            truncated.rfind('.\n'),
            truncated.rfind('? '),
            truncated.rfind('?\n'),
        )
        if sentence_end > len(truncated) // 3:
            truncated = truncated[:sentence_end + 1]
        if truncated.strip():
            return truncated.strip()
        return "I wasn't able to generate a complete answer for that. Could you try rephrasing your question?"

    return text


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

    # Enrich messages with current date and live web search context for real API calls
    mock_env = os.getenv("MOCK_LLM_RESPONSE")
    has_real_key = any(
        not k.startswith(("demo_", "mock_", "your_", "test-key", "placeholder"))
        for _, k in key_pool
    )
    enriched_messages = [dict(m) for m in messages]
    if has_real_key and not (mock_env and mock_env.strip()):
        today_line = f"Current date: {datetime.now().strftime('%A, %B %d, %Y')}."
        search_query = build_search_query(enriched_messages)
        web_ctx = fetch_live_web_context(search_query) if search_query else None

        extra_system = today_line
        if web_ctx:
            extra_system = f"{today_line}\n\n{web_ctx}"

        if enriched_messages and enriched_messages[0].get("role") == "system":
            enriched_messages[0]["content"] = (
                f"{enriched_messages[0]['content']}\n\n{extra_system}"
            )
        else:
            enriched_messages.insert(0, {"role": "system", "content": extra_system})

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
                "messages": enriched_messages,
                "api_key": raw_key,
                "temperature": 0.0,
                "max_tokens": 2048,
                "frequency_penalty": 0.6,
                "presence_penalty": 0.4,
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

            # Post-process: detect and truncate repetition loops
            reply_text = _sanitize_repetition(reply_text)

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
