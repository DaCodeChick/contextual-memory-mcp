from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import json
import re
from typing import Iterable, Protocol
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True)
class WebPage:
    title: str
    url: str
    text: str


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]: ...


class SearchProviderError(RuntimeError):
    pass


def _read_json(request: Request, *, timeout: float, max_bytes: int = 2_000_000) -> dict:
    with urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise SearchProviderError("Search response exceeded maximum size")
    try:
        value = json.loads(data.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise SearchProviderError("Search provider returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise SearchProviderError("Search provider returned an unexpected payload")
    return value


def _deduplicate(results: Iterable[SearchResult], limit: int) -> list[SearchResult]:
    seen: set[str] = set()
    output: list[SearchResult] = []
    for result in results:
        normalized = result.url.rstrip("/")
        if not normalized or normalized in seen:
            continue
        if not result.url.startswith(("http://", "https://")):
            continue
        seen.add(normalized)
        output.append(result)
        if len(output) >= max(1, limit):
            break
    return output


class ProviderChain:
    """Try providers in priority order, falling back on errors or empty results."""

    name = "chain"

    def __init__(self, providers: Iterable[SearchProvider]) -> None:
        self.providers = tuple(providers)
        if not self.providers:
            raise ValueError("ProviderChain requires at least one provider")
        self.last_errors: tuple[str, ...] = ()
        self.last_provider: str | None = None

    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        errors: list[str] = []
        self.last_provider = None
        for provider in self.providers:
            try:
                results = provider.search(query, limit=limit)
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            if results:
                self.last_errors = tuple(errors)
                self.last_provider = provider.name
                return results
            errors.append(f"{provider.name}: no results")
        self.last_errors = tuple(errors)
        raise SearchProviderError("All search providers failed: " + "; ".join(errors))


class _SearchResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._href: str | None = None
        self._title: list[str] = []
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "a" and ("result__a" in classes or "result-link" in classes):
            self._href = attributes.get("href")
            self._title = []
            self._capture_title = True

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._capture_title:
            return
        self._capture_title = False
        if not self._href:
            return
        title = " ".join("".join(self._title).split())
        url = _decode_duckduckgo_url(self._href)
        if title and url.startswith(("http://", "https://")):
            self.results.append(SearchResult(title=title, url=url))


def _decode_duckduckgo_url(value: str) -> str:
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if "duckduckgo.com" in parsed.netloc:
        redirect = parse_qs(parsed.query).get("uddg")
        if redirect:
            return unquote(redirect[0])
    return value


class DuckDuckGoSearchProvider:
    """Dependency-free fallback using DuckDuckGo's HTML endpoint."""

    name = "duckduckgo"
    endpoint = "https://html.duckduckgo.com/html/"

    def __init__(self, *, timeout: float = 12.0, user_agent: str = "ContextualMemoryMCP/0.1") -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        body = urlencode({"q": query}).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            headers={"User-Agent": self.user_agent, "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(request, timeout=self.timeout) as response:
            html = response.read(2_000_000).decode("utf-8", errors="replace")
        parser = _SearchResultParser()
        parser.feed(html)
        return _deduplicate(parser.results, limit)


class BraveSearchProvider:
    name = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, *, timeout: float = 12.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        url = f"{self.endpoint}?{urlencode({'q': query, 'count': min(max(1, limit), 20)})}"
        payload = _read_json(Request(url, headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"}), timeout=self.timeout)
        items = ((payload.get("web") or {}).get("results") or [])
        return _deduplicate((SearchResult(str(item.get("title") or item.get("url") or ""), str(item.get("url") or ""), str(item.get("description") or "")) for item in items if isinstance(item, dict)), limit)


class TavilySearchProvider:
    name = "tavily"
    endpoint = "https://api.tavily.com/search"

    def __init__(self, api_key: str, *, timeout: float = 15.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        data = json.dumps({"query": query, "max_results": min(max(1, limit), 20), "search_depth": "basic", "include_answer": False, "include_raw_content": False}).encode("utf-8")
        request = Request(self.endpoint, data=data, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "application/json"})
        payload = _read_json(request, timeout=self.timeout)
        items = payload.get("results") or []
        return _deduplicate((SearchResult(str(item.get("title") or item.get("url") or ""), str(item.get("url") or ""), str(item.get("content") or "")) for item in items if isinstance(item, dict)), limit)


class ExaSearchProvider:
    name = "exa"
    endpoint = "https://api.exa.ai/search"

    def __init__(self, api_key: str, *, timeout: float = 15.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        data = json.dumps({"query": query, "numResults": min(max(1, limit), 20), "type": "auto"}).encode("utf-8")
        request = Request(self.endpoint, data=data, headers={"x-api-key": self.api_key, "Content-Type": "application/json", "Accept": "application/json"})
        payload = _read_json(request, timeout=self.timeout)
        items = payload.get("results") or []
        return _deduplicate((SearchResult(str(item.get("title") or item.get("url") or ""), str(item.get("url") or ""), str(item.get("text") or item.get("summary") or "")) for item in items if isinstance(item, dict)), limit)


class SearXNGSearchProvider:
    name = "searxng"

    def __init__(self, base_url: str, *, timeout: float = 12.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        url = f"{self.base_url}/search?{urlencode({'q': query, 'format': 'json'})}"
        payload = _read_json(Request(url, headers={"Accept": "application/json"}), timeout=self.timeout)
        items = payload.get("results") or []
        return _deduplicate((SearchResult(str(item.get("title") or item.get("url") or ""), str(item.get("url") or ""), str(item.get("content") or "")) for item in items if isinstance(item, dict)), limit)


def build_search_provider(settings) -> SearchProvider:
    providers: list[SearchProvider] = []
    for name in settings.web_search_providers:
        normalized = name.strip().lower()
        if normalized == "exa" and settings.exa_api_key:
            providers.append(ExaSearchProvider(settings.exa_api_key, timeout=settings.web_search_timeout))
        elif normalized == "brave" and settings.brave_search_api_key:
            providers.append(BraveSearchProvider(settings.brave_search_api_key, timeout=settings.web_search_timeout))
        elif normalized == "tavily" and settings.tavily_api_key:
            providers.append(TavilySearchProvider(settings.tavily_api_key, timeout=settings.web_search_timeout))
        elif normalized == "searxng" and settings.searxng_url:
            providers.append(SearXNGSearchProvider(settings.searxng_url, timeout=settings.web_search_timeout))
        elif normalized == "duckduckgo":
            providers.append(DuckDuckGoSearchProvider(timeout=settings.web_search_timeout))
    if not providers:
        providers.append(DuckDuckGoSearchProvider(timeout=settings.web_search_timeout))
    return providers[0] if len(providers) == 1 else ProviderChain(providers)


class _ReadableHTMLParser(HTMLParser):
    BLOCKED = {"script", "style", "noscript", "svg", "canvas", "template"}
    BREAKS = {"p", "div", "section", "article", "main", "header", "footer", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._blocked_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCKED:
            self._blocked_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BREAKS and not self._blocked_depth:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCKED and self._blocked_depth:
            self._blocked_depth -= 1
        if tag in self.BREAKS and not self._blocked_depth:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._blocked_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.text_parts.append(data)

    def result(self, fallback_title: str) -> tuple[str, str]:
        title = " ".join("".join(self.title_parts).split()) or fallback_title
        text = "".join(self.text_parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*\n(?:\s*\n)+", "\n\n", text)
        lines = [line.strip() for line in text.splitlines()]
        return title, "\n".join(line for line in lines if line).strip()


class WebFetcher:
    MEDIAWIKI_HOST_HINTS = ("wikipedia.org", "fandom.com", "wiki.org", "wiktionary.org")

    def __init__(self, *, timeout: float = 15.0, max_bytes: int = 3_000_000, user_agent: str = "ContextualMemoryMCP/0.1") -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.user_agent = user_agent

    def _read(self, request: Request) -> tuple[str, str, bytes]:
        with urlopen(request, timeout=self.timeout) as response:
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            data = response.read(self.max_bytes + 1)
        if len(data) > self.max_bytes:
            raise ValueError("Web response exceeds maximum size")
        return content_type, charset, data

    @staticmethod
    def _github_raw_url(url: str) -> str | None:
        parsed = urlparse(url)
        if parsed.netloc.casefold() != "github.com":
            return None
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 5 and parts[2] == "blob":
            owner, repo, _, branch, *path = parts
            return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{'/'.join(path)}"
        return None

    def _fetch_mediawiki(self, url: str) -> WebPage | None:
        parsed = urlparse(url)
        if "/wiki/" not in parsed.path:
            return None
        if not any(hint in parsed.netloc.casefold() for hint in self.MEDIAWIKI_HOST_HINTS):
            return None
        title = unquote(parsed.path.split("/wiki/", 1)[1]).replace("_", " ")
        api_url = f"{parsed.scheme}://{parsed.netloc}/api.php?{urlencode({'action': 'query', 'prop': 'extracts', 'explaintext': 1, 'redirects': 1, 'titles': title, 'format': 'json', 'formatversion': 2})}"
        try:
            _, _, data = self._read(Request(api_url, headers={"User-Agent": self.user_agent, "Accept": "application/json"}))
            payload = json.loads(data.decode("utf-8", errors="replace"))
            pages = ((payload.get("query") or {}).get("pages") or [])
            if not pages or not isinstance(pages[0], dict):
                return None
            page = pages[0]
            text = str(page.get("extract") or "").strip()
            if not text:
                return None
            return WebPage(title=str(page.get("title") or title), url=url, text=text)
        except Exception:
            return None

    def fetch(self, url: str) -> WebPage:
        mediawiki = self._fetch_mediawiki(url)
        if mediawiki is not None:
            return mediawiki

        effective_url = self._github_raw_url(url) or url
        request = Request(effective_url, headers={"User-Agent": self.user_agent})
        content_type, charset, data = self._read(request)
        if content_type not in {"text/html", "text/plain", "application/xhtml+xml", "text/markdown"}:
            raise ValueError(f"Unsupported web content type {content_type!r}: {url}")
        decoded = data.decode(charset, errors="replace")
        fallback = urlparse(url).netloc or url
        if content_type in {"text/plain", "text/markdown"}:
            return WebPage(title=fallback, url=url, text=decoded.strip())
        parser = _ReadableHTMLParser()
        parser.feed(decoded)
        title, text = parser.result(fallback)
        return WebPage(title=title, url=url, text=text)

