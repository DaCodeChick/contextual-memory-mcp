from providers.web import _ReadableHTMLParser, _SearchResultParser


def test_duckduckgo_result_parser_decodes_redirect() -> None:
    parser = _SearchResultParser()
    parser.feed(
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fcharacter">Character</a>'
    )
    assert len(parser.results) == 1
    assert parser.results[0].title == "Character"
    assert parser.results[0].url == "https://example.com/character"


def test_readable_html_parser_removes_scripts() -> None:
    parser = _ReadableHTMLParser()
    parser.feed(
        "<html><head><title>Example</title><script>bad()</script></head>"
        "<body><h1>Character</h1><p>Useful profile text.</p></body></html>"
    )
    title, text = parser.result("fallback")
    assert title == "Example"
    assert "Useful profile text." in text
    assert "bad()" not in text

from types import SimpleNamespace

from providers.web import (
    DuckDuckGoSearchProvider,
    ProviderChain,
    SearchProviderError,
    SearchResult,
    build_search_provider,
)


class _FakeProvider:
    def __init__(self, name: str, *, results=None, error: Exception | None = None) -> None:
        self.name = name
        self.results = results or []
        self.error = error
        self.calls = 0

    def search(self, query: str, *, limit: int = 8):
        self.calls += 1
        if self.error:
            raise self.error
        return self.results[:limit]


def test_provider_chain_falls_back_after_error() -> None:
    first = _FakeProvider("first", error=RuntimeError("offline"))
    second = _FakeProvider("second", results=[SearchResult("Hit", "https://example.com")])
    chain = ProviderChain([first, second])
    assert chain.search("character")[0].url == "https://example.com"
    assert chain.last_provider == "second"
    assert first.calls == second.calls == 1


def test_provider_chain_falls_back_after_empty_results() -> None:
    first = _FakeProvider("first")
    second = _FakeProvider("second", results=[SearchResult("Hit", "https://example.com")])
    chain = ProviderChain([first, second])
    assert chain.search("character")[0].title == "Hit"
    assert "no results" in chain.last_errors[0]


def test_provider_chain_reports_total_failure() -> None:
    chain = ProviderChain([_FakeProvider("empty"), _FakeProvider("broken", error=RuntimeError("down"))])
    try:
        chain.search("character")
    except SearchProviderError as exc:
        assert "empty" in str(exc)
        assert "broken" in str(exc)
    else:
        raise AssertionError("Expected SearchProviderError")


def test_provider_factory_skips_unconfigured_providers() -> None:
    settings = SimpleNamespace(
        web_search_providers=["exa", "brave", "duckduckgo"],
        web_search_timeout=5.0,
        exa_api_key=None,
        brave_search_api_key=None,
        tavily_api_key=None,
        searxng_url=None,
    )
    provider = build_search_provider(settings)
    assert isinstance(provider, DuckDuckGoSearchProvider)
