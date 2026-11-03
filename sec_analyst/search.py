"""Optional web research through the Brave Search API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import math
from numbers import Real
from urllib.parse import urlencode, urlsplit

import requests


class WebSearchError(RuntimeError):
    """Raised when a configured web search request cannot be used."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = "Brave Search"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class BraveSearchClient:
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None, timeout: float = 12.0) -> None:
        self.api_key = (
            api_key if api_key is not None else os.environ.get("BRAVE_SEARCH_API_KEY")
        )
        self.api_key = self.api_key.strip() if self.api_key else None
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, Real)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Search timeout must be a positive finite number.")
        self.timeout = timeout
        self.session = requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, company_name: str, max_results: int = 5) -> list[SearchResult]:
        if not isinstance(company_name, str) or not company_name.strip():
            raise ValueError("A company name is required for web research.")
        if (
            isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or not 1 <= max_results <= 10
        ):
            raise ValueError("Search result count must be between 1 and 10.")
        if not self.api_key:
            raise WebSearchError(
                "BRAVE_SEARCH_API_KEY is not configured; web research was not run."
            )
        query = f'"{company_name.strip()}" financial results funding outlook'
        try:
            response = self.session.get(
                self.ENDPOINT,
                params={"q": query, "count": max_results},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.api_key,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise WebSearchError(f"Web search request failed: {exc}") from exc
        except ValueError as exc:
            raise WebSearchError("Web search API returned invalid JSON.") from exc
        try:
            web_results = payload["web"]["results"]
            if not isinstance(web_results, list):
                raise TypeError("web results are not a list")
            safe_results: list[SearchResult] = []
            for item in web_results[:max_results]:
                if not isinstance(item, dict):
                    continue
                result_url = str(item.get("url", ""))[:2000]
                parsed_url = urlsplit(result_url)
                if parsed_url.scheme not in {"https", "http"} or not parsed_url.netloc:
                    continue
                safe_results.append(
                    SearchResult(
                        title=str(item.get("title", ""))[:300],
                        url=result_url,
                        snippet=str(item.get("description", ""))[:1500],
                    )
                )
            return safe_results
        except (KeyError, TypeError) as exc:
            raise WebSearchError("Web search API returned an unusable response.") from exc


def build_search_url(query: str, max_results: int = 5) -> str:
    """Expose the exact request URL for diagnostics without including credentials."""
    return f"{BraveSearchClient.ENDPOINT}?{urlencode({'q': query, 'count': max_results})}"
