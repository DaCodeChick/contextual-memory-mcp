from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable

from core.web_cache import WebAcquisitionCache
from providers.web import SearchProvider, WebFetcher, build_search_provider


@dataclass(frozen=True)
class AcquisitionResult:
    query: str
    discovered: int
    fetched: int
    indexed: int
    unchanged: int
    failed: int
    sources: tuple[str, ...]
    provider: str | None = None
    cached: bool = False
    skipped: bool = False
    status: str = "SUCCESS"

    def as_dict(self) -> dict:
        return {
            "query": self.query,
            "discovered": self.discovered,
            "fetched": self.fetched,
            "indexed": self.indexed,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "sources": list(self.sources),
            "provider": self.provider,
            "cached": self.cached,
            "skipped": self.skipped,
            "status": self.status,
        }


class WebAcquisitionService:
    def __init__(self, ingestion, *, settings=None, search: SearchProvider | None = None, fetcher: WebFetcher | None = None, cache: WebAcquisitionCache | None = None, progress: Callable[[str], None] | None = None) -> None:
        self.ingestion = ingestion
        self.settings = settings or ingestion.settings
        self.search_provider = search or build_search_provider(self.settings)
        self.fetcher = fetcher or WebFetcher(timeout=self.settings.web_fetch_timeout)
        self.cache = cache or WebAcquisitionCache(self.settings.web_cache_path)
        self.progress = progress
        if hasattr(self.search_provider, "progress"):
            self.search_provider.progress = progress

    def _report(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)

    def _search(self, query: str, *, limit: int) -> tuple[list, str | None, bool]:
        cached = self.cache.get_search(query)
        if cached is not None:
            provider, results = cached
            self._report(f"Using cached search results from {provider}.")
            return results[:limit], provider, True
        if not hasattr(self.search_provider, "progress"):
            self._report(f"Searching with {getattr(self.search_provider, 'name', 'provider')}...")
        results = self.search_provider.search(query, limit=limit)
        provider = getattr(self.search_provider, "last_provider", None) or getattr(self.search_provider, "name", None)
        self.cache.put_search(
            query, provider or "unknown", results,
            ttl_days=self.settings.web_search_cache_days,
        )
        return results, provider, False

    def ingest_url(self, url: str, *, force: bool = False) -> dict:
        page = self.fetcher.fetch(url)
        if len(page.text) < 200:
            raise ValueError(f"Fetched page did not contain enough readable text: {url}")
        result = self.ingestion.ingest_text(
            source_path=page.url,
            title=page.title,
            text=page.text,
            source_kind="web",
            force=force,
        )
        return {"url": page.url, "title": page.title, **result}

    def acquire(self, query: str, *, max_results: int = 8, max_pages: int = 4, force: bool = False) -> AcquisitionResult:
        started = time.monotonic()
        deadline = started + self.settings.web_acquisition_total_timeout
        if not force:
            prior = self.cache.should_skip(query)
            if prior is not None:
                return AcquisitionResult(
                    query=query, discovered=0, fetched=0, indexed=0,
                    unchanged=0, failed=0, sources=(), skipped=True,
                    status=prior.status,
                )
        try:
            candidates, provider, cached = self._search(query, limit=max_results)
            self._report(f"Found {len(candidates)} candidate result(s) via {provider or 'unknown'}.")
        except Exception as exc:
            self.cache.record_attempt(
                query, status="FAILED", pages_indexed=0,
                retry_after_days=self.settings.web_acquisition_retry_days,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        fetched = indexed = unchanged = failed = 0
        sources: list[str] = []
        for index, candidate in enumerate(candidates[:max_pages], start=1):
            if time.monotonic() >= deadline:
                self._report("Stopping because the acquisition time limit was reached.")
                failed += len(candidates[:max_pages]) - index + 1
                break
            self._report(f"Fetching page {index}/{min(len(candidates), max_pages)}: {candidate.url}")
            try:
                result = self.ingest_url(candidate.url)
                fetched += 1
                indexed += int(result["indexed"])
                unchanged += int(result["unchanged"])
                sources.append(candidate.url)
                self._report(f"Indexed: {candidate.url}")
            except Exception as exc:
                failed += 1
                self._report(f"Skipped {candidate.url}: {type(exc).__name__}: {exc}")

        if indexed > 0:
            status = "SUCCESS" if failed == 0 else "PARTIAL"
            retry_days = self.settings.web_acquisition_refresh_days
        elif unchanged > 0:
            status = "SUCCESS"
            retry_days = self.settings.web_acquisition_refresh_days
        elif candidates:
            status = "PARTIAL" if fetched else "FAILED"
            retry_days = self.settings.web_acquisition_retry_days
        else:
            status = "NO_RESULTS"
            retry_days = self.settings.web_acquisition_retry_days

        self.cache.record_attempt(
            query, status=status, pages_indexed=indexed,
            retry_after_days=retry_days,
        )
        return AcquisitionResult(
            query=query, discovered=len(candidates), fetched=fetched,
            indexed=indexed, unchanged=unchanged, failed=failed,
            sources=tuple(sources), provider=provider, cached=cached,
            status=status,
        )
