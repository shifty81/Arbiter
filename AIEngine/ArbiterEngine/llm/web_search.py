"""Web search provider — stdlib-only, no API key required.

Supports two backends:
- **DuckDuckGo Lite** (default) — parses ``https://lite.duckduckgo.com/lite/``
  using only ``urllib`` and ``html.parser``.  No JS, no API key, no cookies.
- **SearXNG** — uses a self-hosted SearXNG instance's JSON API.  Set
  ``searxng_url`` to the base URL of your instance (e.g.
  ``http://localhost:8080``).

Public API
----------
search(query, max_results, provider, timeout_s, searxng_url) -> list[SearchResult]
    Fetch web search results for a query.

build_rag_context(results, query, max_chars) -> str
    Format search results into a prompt context block for the LLM.
"""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_PROVIDER_DDG      = "duckduckgo"
_PROVIDER_SEARXNG  = "searxng"
PROVIDERS          = (_PROVIDER_DDG, _PROVIDER_SEARXNG)


@dataclass
class SearchResult:
    """One web search result."""
    title:   str
    url:     str
    snippet: str = ""

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


# ── DuckDuckGo Lite HTML parser ───────────────────────────────────────────────

class _DDGLiteParser(HTMLParser):
    """Extracts results from the DuckDuckGo Lite HTML page.

    DDG Lite result structure (simplified):
      <table>
        ...
        <td class="result-link"><a href="...">TITLE</a></td>
        <td class="result-snippet">SNIPPET</td>
        ...
      </table>
    """

    def __init__(self) -> None:
        super().__init__()
        self._results: list[SearchResult] = []
        self._in_link    = False
        self._in_snippet = False
        self._cur_url    = ""
        self._cur_title  = ""
        self._cur_snippet_parts: list[str] = []

    # ── SAX-style callbacks ───────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        classes  = (attr_map.get("class") or "").lower()

        if tag == "td" and "result-link" in classes:
            self._in_link   = True
            self._cur_title = ""
            self._cur_url   = ""
        elif tag == "td" and "result-snippet" in classes:
            self._in_snippet       = True
            self._cur_snippet_parts = []
        elif tag == "a" and self._in_link:
            href = attr_map.get("href") or ""
            if href.startswith("http"):
                self._cur_url = href
            elif href.startswith("//"):
                self._cur_url = "https:" + href

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            if self._in_link:
                self._in_link = False
            elif self._in_snippet:
                self._in_snippet = False
                snippet = " ".join(self._cur_snippet_parts).strip()
                if self._cur_url:
                    self._results.append(
                        SearchResult(
                            title=self._cur_title.strip(),
                            url=self._cur_url,
                            snippet=snippet,
                        )
                    )

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._cur_title += data
        elif self._in_snippet:
            self._cur_snippet_parts.append(data)


def _ddg_lite_search(
    query: str,
    max_results: int = 5,
    timeout_s: float = 8.0,
    user_agent: str = _DEFAULT_UA,
) -> list[SearchResult]:
    """Fetch results from DuckDuckGo Lite (no JS, no API key)."""
    encoded = urllib.parse.urlencode({"q": query, "kl": "us-en"})
    url     = f"https://lite.duckduckgo.com/lite/?{encoded}"

    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("DuckDuckGo Lite request failed: %s", exc)
        return []

    parser = _DDGLiteParser()
    try:
        parser.feed(html.unescape(body))
    except Exception as exc:
        logger.warning("DDG HTML parse error: %s", exc)

    # Fallback: parse via regex if the structured parser found nothing
    results = parser._results
    if not results:
        results = _ddg_regex_fallback(body, max_results)

    return [r for r in results if r.url][:max_results]


def _ddg_regex_fallback(body: str, max_results: int) -> list[SearchResult]:
    """Regex-based fallback extraction from DuckDuckGo Lite HTML."""
    results: list[SearchResult] = []
    # Matches: <a href="https://...">TITLE</a>
    link_re = re.compile(r'<a[^>]+href=["\']?(https?://[^"\'> ]+)["\']?[^>]*>(.*?)</a>',
                         re.IGNORECASE | re.DOTALL)
    for m in link_re.finditer(body):
        url   = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if title and url and "duckduckgo.com" not in url:
            results.append(SearchResult(title=title, url=url))
        if len(results) >= max_results:
            break
    return results


# ── SearXNG backend ───────────────────────────────────────────────────────────

def _searxng_search(
    query: str,
    base_url: str,
    max_results: int = 5,
    timeout_s: float = 8.0,
    user_agent: str = _DEFAULT_UA,
) -> list[SearchResult]:
    """Fetch results from a SearXNG instance via its JSON API."""
    params  = urllib.parse.urlencode({"q": query, "format": "json", "engines": "general"})
    url     = f"{base_url.rstrip('/')}/search?{params}"
    req     = urllib.request.Request(url, headers={
        "User-Agent": user_agent,
        "Accept":     "application/json",
    })
    try:
        import json as _json
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = _json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.warning("SearXNG request failed (%s): %s", url, exc)
        return []

    results: list[SearchResult] = []
    for item in data.get("results", [])[:max_results]:
        results.append(SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("content", ""),
        ))
    return results


# ── Public API ────────────────────────────────────────────────────────────────

def search(
    query: str,
    max_results: int = 5,
    provider: str = _PROVIDER_DDG,
    timeout_s: float = 8.0,
    searxng_url: str = "",
    user_agent: str = _DEFAULT_UA,
) -> list[SearchResult]:
    """Search the web and return a list of :class:`SearchResult` objects.

    Parameters
    ----------
    query
        The search query.
    max_results
        Maximum number of results to return (default 5, max 20).
    provider
        Backend to use: ``"duckduckgo"`` (default) or ``"searxng"``.
    timeout_s
        HTTP request timeout in seconds.
    searxng_url
        Base URL of a SearXNG instance — required when ``provider="searxng"``.
    user_agent
        HTTP ``User-Agent`` header value.
    """
    max_results = max(1, min(max_results, 20))

    if provider == _PROVIDER_SEARXNG:
        if not searxng_url:
            logger.warning("SearXNG provider selected but searxng_url is empty; falling back to DDG")
            provider = _PROVIDER_DDG
        else:
            return _searxng_search(query, searxng_url, max_results, timeout_s, user_agent)

    # Default: DuckDuckGo Lite
    return _ddg_lite_search(query, max_results, timeout_s, user_agent)


def build_rag_context(
    results: list[SearchResult],
    query: str,
    max_chars: int = 6000,
) -> str:
    """Format search results into a context block for LLM prompt injection.

    The block is structured as:

    .. code-block:: text

        === Web search results for: "your query" ===
        [1] Title of first result
            URL: https://...
            Snippet: ...

        [2] Title of second result
            ...

        === End of web search results ===

    Parameters
    ----------
    results
        List of :class:`SearchResult` objects.
    query
        The original search query (used in the header line).
    max_chars
        Maximum total characters for the context block.
    """
    if not results:
        return (
            f'=== Web search results for: "{query}" ===\n'
            "No results found.\n"
            "=== End of web search results ===\n"
        )

    lines: list[str] = [f'=== Web search results for: "{query}" ===']
    total = len(lines[0])

    for i, r in enumerate(results, start=1):
        snippet = r.snippet.strip() or "(no snippet available)"
        block = (
            f"\n[{i}] {r.title}\n"
            f"    URL: {r.url}\n"
            f"    Snippet: {snippet}\n"
        )
        if total + len(block) > max_chars:
            break
        lines.append(block)
        total += len(block)

    footer = "\n=== End of web search results ==="
    lines.append(footer)
    return "".join(lines)
