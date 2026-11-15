"""Taste ingestion: user-uploaded tasting notes become searchable, unreviewed rows."""

from .pipeline import IngestRejected, IngestResult, IngestStore, TasteIngestor
from .web_search import NullWebSearcher, SearchFindings, WebSearcher, build_web_searcher

__all__ = [
    "IngestRejected",
    "IngestResult",
    "IngestStore",
    "NullWebSearcher",
    "SearchFindings",
    "TasteIngestor",
    "WebSearcher",
    "build_web_searcher",
]
