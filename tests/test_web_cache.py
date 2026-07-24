from pathlib import Path

from core.web_cache import WebAcquisitionCache
from providers.web import SearchResult


def test_search_cache_round_trip(tmp_path: Path) -> None:
    cache = WebAcquisitionCache(tmp_path / "web.sqlite3")
    cache.put_search("test query", "fake", [SearchResult("Title", "https://example.com", "Snippet")], ttl_days=7)
    provider, results = cache.get_search("  TEST   query ")
    assert provider == "fake"
    assert results[0].url == "https://example.com"


def test_acquisition_history_suppresses_retry(tmp_path: Path) -> None:
    cache = WebAcquisitionCache(tmp_path / "web.sqlite3")
    cache.record_attempt("missing character", status="NO_RESULTS", pages_indexed=0, retry_after_days=7)
    history = cache.should_skip("Missing Character")
    assert history is not None
    assert history.status == "NO_RESULTS"
