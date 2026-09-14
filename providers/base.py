from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class NormalizedArticle:
    """Common article shape every provider must produce.

    canonical_url / content_hash / semantic_hash / story_id / quality_score
    are filled in later by the pipeline (dedup/clustering/scoring), not by
    providers themselves — providers only know how to talk to one source.
    """

    article_id: str
    title: str
    url: str
    provider: str
    source_name: str
    description: Optional[str] = None
    content: Optional[str] = None
    image_url: Optional[str] = None
    source_url: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    fetched_at: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    keywords: list = field(default_factory=list)

    canonical_url: Optional[str] = None
    content_hash: Optional[str] = None
    story_id: Optional[str] = None
    quality_score: Optional[float] = None
    is_duplicate: bool = False
    is_primary: bool = True

    # Phase 2 NLP enrichment -- filled in by pipeline.sentiment /
    # pipeline.entities after dedup, before clustering/scoring.
    sentiment: Optional[str] = None  # "positive" | "neutral" | "negative"
    sentiment_score: Optional[float] = None  # model confidence, 0-1
    entities: list = field(default_factory=list)  # [{"text": ..., "label": ...}]

    def to_dict(self):
        return asdict(self)


class NewsProvider(ABC):
    """Common interface every news source implements.

    The rest of the application only ever talks to this interface — it
    never needs to know whether an article came from a REST API or an RSS
    feed.
    """

    name = "base"

    @property
    def enabled(self):
        """Whether this provider is configured and ready to be called."""
        return True

    @abstractmethod
    def fetch_news(self, query=None, category=None, country=None, language=None, page=None, page_size=10):
        """Return a list of NormalizedArticle for the given filters."""
        raise NotImplementedError
