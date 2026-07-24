from __future__ import annotations

from dataclasses import dataclass

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
    def __init__(self, ingestion, *, settings=None, search: SearchProvider | None = None, fetcher: WebFetcher | None = None, cache: WebAcquisitionCache | None = None) -> None:
        self.ingestion = ingestion
        self.settings = settings or ingestion.settings
        self.search_provider = search or build_search_provider(self.settings)
        self.fetcher = fetcher or WebFetcher(timeout=self.settings.web_search_timeout)
        self.cache = cache or WebAcquisitionCache(self.settings.web_cache_path)

    def _search(self, query: str, *, limit: int) -> tuple[list, str | None, bool]:
        cached = self.cache.get_search(query)
        if cached is not None:
            provider, results = cached
            return results[:limit], provider, True
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
        except Exception as exc:
            self.cache.record_attempt(
                query, status="FAILED", pages_indexed=0,
                retry_after_days=self.settings.web_acquisition_retry_days,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        fetched = indexed = unchanged = failed = 0
        sources: list[str] = []
        for candidate in candidates[:max_pages]:
            try:
                result = self.ingest_url(candidate.url)
                fetched += 1
                indexed += int(result["indexed"])
                unchanged += int(result["unchanged"])
                sources.append(candidate.url)
            except Exception:
                failed += 1

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
