from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re
from typing import Protocol
from urllib.parse import parse_qs, unquote, urlparse
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
    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]: ...


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
    """Dependency-free web discovery using DuckDuckGo's HTML endpoint."""

    endpoint = "https://html.duckduckgo.com/html/"

    def __init__(self, *, timeout: float = 12.0, user_agent: str = "ContextualMemoryMCP/0.1") -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        from urllib.parse import urlencode

        body = urlencode({"q": query}).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            headers={
                "User-Agent": self.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            html = response.read(2_000_000).decode("utf-8", errors="replace")
        parser = _SearchResultParser()
        parser.feed(html)
        seen: set[str] = set()
        results: list[SearchResult] = []
        for result in parser.results:
            normalized = result.url.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            results.append(result)
            if len(results) >= max(1, limit):
                break
        return results


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
        text = "\n".join(line for line in lines if line).strip()
        return title, text


class WebFetcher:
    def __init__(self, *, timeout: float = 15.0, max_bytes: int = 3_000_000, user_agent: str = "ContextualMemoryMCP/0.1") -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.user_agent = user_agent

    def fetch(self, url: str) -> WebPage:
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout) as response:
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            data = response.read(self.max_bytes + 1)
        if len(data) > self.max_bytes:
            raise ValueError(f"Web page exceeds maximum size: {url}")
        if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
            raise ValueError(f"Unsupported web content type {content_type!r}: {url}")
        decoded = data.decode(charset, errors="replace")
        fallback = urlparse(url).netloc or url
        if content_type == "text/plain":
            return WebPage(title=fallback, url=url, text=decoded.strip())
        parser = _ReadableHTMLParser()
        parser.feed(decoded)
        title, text = parser.result(fallback)
        return WebPage(title=title, url=url, text=text)
