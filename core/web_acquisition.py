from __future__ import annotations

from dataclasses import dataclass

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

    def as_dict(self) -> dict:
        return {
            "query": self.query,
            "discovered": self.discovered,
            "fetched": self.fetched,
            "indexed": self.indexed,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "sources": list(self.sources),
        }


class WebAcquisitionService:
    def __init__(self, ingestion, *, settings=None, search: SearchProvider | None = None, fetcher: WebFetcher | None = None) -> None:
        self.ingestion = ingestion
        effective_settings = settings or ingestion.settings
        self.search_provider = search or build_search_provider(effective_settings)
        self.fetcher = fetcher or WebFetcher(timeout=effective_settings.web_search_timeout)

    def acquire(self, query: str, *, max_results: int = 8, max_pages: int = 4) -> AcquisitionResult:
        candidates = self.search_provider.search(query, limit=max_results)
        fetched = indexed = unchanged = failed = 0
        sources: list[str] = []
        for candidate in candidates[:max_pages]:
            try:
                page = self.fetcher.fetch(candidate.url)
                fetched += 1
                if len(page.text) < 200:
                    failed += 1
                    continue
                result = self.ingestion.ingest_text(
                    source_path=page.url,
                    title=page.title,
                    text=page.text,
                    source_kind="web",
                )
                indexed += int(result["indexed"])
                unchanged += int(result["unchanged"])
                sources.append(page.url)
            except Exception:
                failed += 1
        return AcquisitionResult(
            query=query,
            discovered=len(candidates),
            fetched=fetched,
            indexed=indexed,
            unchanged=unchanged,
            failed=failed,
            sources=tuple(sources),
        )
