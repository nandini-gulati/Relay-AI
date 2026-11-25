"""Lightweight live web search helper for accurate, up-to-date answers.

Uses DuckDuckGo Lite and Google News RSS over httpx with no extra API keys.
Fails gracefully (returns None) on timeout or network error so chat never breaks.
"""

from datetime import datetime
import html
import logging
import re
import time
from typing import Dict, List, Optional, Tuple
import urllib.parse
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger("relay.search")

# Short in-memory cache so repeated identical queries produce the exact same
# enriched prompt and reliably hit LiteLLM's response cache (LLM_CACHE).
_SEARCH_CACHE: Dict[str, Tuple[float, Optional[str]]] = {}
_SEARCH_CACHE_TTL = 300.0  # 5 minutes

_SKIP_GREETINGS = re.compile(
    r"^(hi|hello|hey|good morning|good afternoon|good evening|thanks|thank you|ok|okay|bye|cool|nice|how are you|who are you)\b[!.?]*$",
    re.IGNORECASE,
)

_SKIP_CODING_OR_CREATIVE = re.compile(
    r"\b("
    r"python|javascript|typescript|react|html|css|sql|sqlite|docker|fastapi|bash|regex|"
    r"function|class|variable|compile|debug|syntax|algorithm|"
    r"write a poem|write a story|haiku|translate|rewrite|proofread|summarize this"
    r")\b",
    re.IGNORECASE,
)

_FOLLOWUP_PATTERNS = re.compile(
    r"^(what about|how about|and what|tell me more|what did|how did|who else|more on|more about|why didn|why did|u are wrong|you are wrong)\b",
    re.IGNORECASE,
)


def needs_web_search(query: str) -> bool:
    """Return True for factual/real-world queries; skip greetings, pure code, math, and creative prompts."""
    q = (query or "").strip()
    if len(q) < 4:
        return False
    if _SKIP_GREETINGS.match(q):
        return False
    if re.fullmatch(r"[\d\s\+\-\*\/\(\)\.\=\?]+", q):
        return False
    if _SKIP_CODING_OR_CREATIVE.search(q):
        return False
    return True


def build_search_query(messages: List[Dict[str, str]]) -> Optional[str]:
    """Return a clean, context-aware web search query when live data helps.

    - Self-contained factual questions search directly.
    - Short follow-ups (e.g. 'what about vaibhav suryavanshi') merge with the
      immediately preceding user topic so the search stays on-subject.
    """
    user_msgs = [
        m.get("content", "").strip()
        for m in messages
        if m.get("role") == "user" and m.get("content", "").strip()
    ]
    if not user_msgs:
        return None

    latest = user_msgs[-1]
    if not needs_web_search(latest):
        return None

    # Only merge with the immediately preceding user message when the latest
    # message is a short follow-up fragment (not a self-contained new question).
    is_short_followup = (
        _FOLLOWUP_PATTERNS.search(latest) is not None and len(latest.split()) <= 6
    ) or len(latest.split()) <= 4

    if is_short_followup and len(user_msgs) >= 2:
        prev = user_msgs[-2]
        if needs_web_search(prev):
            clean_latest = re.sub(
                r"^(what about|how about|tell me more about|more about|and|why didn't u mention|why didnt u mention)\s+",
                "",
                latest,
                flags=re.IGNORECASE,
            ).strip(" ?.")
            clean_prev = re.sub(
                r"^(what happened in|tell me about|what is|who won|which)\s+",
                "",
                prev,
                flags=re.IGNORECASE,
            ).strip(" ?.")
            if clean_latest and clean_latest.lower() not in ("it", "that", "this", "u are wrong", "you are wrong"):
                return f"{clean_latest} {clean_prev}".strip()
            return clean_prev

    return latest


def _strip_tags(raw: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", raw)
    cleaned = html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _search_duckduckgo(query: str, limit: int = 6, timeout: float = 4.5) -> List[str]:
    results: List[str] = []
    try:
        resp = httpx.post(
            "https://lite.duckduckgo.com/lite/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return results

        titles = re.findall(r'class=["\']result-link["\'][^>]*>(.*?)</a>', resp.text, re.S)
        snippets = re.findall(r'class=["\']result-snippet["\'][^>]*>(.*?)</td>', resp.text, re.S)
        for title, snippet in zip(titles[:limit], snippets[:limit]):
            t = _strip_tags(title)
            s = _strip_tags(snippet)
            if t and s:
                results.append(f"- {t}: {s}")
    except Exception as exc:
        logger.debug("DuckDuckGo search skipped: %s", exc)
    return results


def _search_google_news(query: str, limit: int = 5, timeout: float = 4.5) -> List[str]:
    results: List[str] = []
    try:
        encoded = urllib.parse.quote(query)
        resp = httpx.get(
            f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return results

        root = ET.fromstring(resp.text)
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            if title:
                results.append(f"- {title} ({pub_date})" if pub_date else f"- {title}")
    except Exception as exc:
        logger.debug("Google News RSS search skipped: %s", exc)
    return results


def fetch_live_web_context(query: str, timeout: float = 4.5) -> Optional[str]:
    """Fetch recent web snippets and news headlines for a query (cached 5m for deterministic LLM_CACHE)."""
    cache_key = re.sub(r"\s+", " ", (query or "").strip().lower())
    now = time.monotonic()
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _SEARCH_CACHE_TTL:
        return cached[1]

    news_items = _search_google_news(query, limit=5, timeout=timeout)
    web_items = _search_duckduckgo(query, limit=6, timeout=timeout)

    if not news_items and not web_items:
        return None

    today_str = datetime.now().strftime("%B %d, %Y")
    sections: List[str] = [f"[Live Web Results as of {today_str}]"]
    if news_items:
        sections.append("Recent News:\n" + "\n".join(news_items))
    if web_items:
        sections.append("Web Snippets:\n" + "\n".join(web_items))
    sections.append(
        "STRICT GROUNDING RULES: Only state facts, names, dates, scores, and numbers "
        "that are explicitly present in these live search results. Prioritize the most "
        "recent dated news items over older ones. Never invent or guess missing details. "
        "If a detail is not in the results, say it was not reported in the available snippets. "
        "Do not mention internal search tags or use emojis."
    )
    result = "\n\n".join(sections)
    _SEARCH_CACHE[cache_key] = (now, result)
    return result
