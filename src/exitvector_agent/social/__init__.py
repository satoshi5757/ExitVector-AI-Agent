"""Social signal ingestion and trend analysis."""

from .models import SocialObservation
from .sources import MockSourceAdapter, SourceAdapter, SourceFailure

__all__ = [
    "MockSourceAdapter",
    "SocialObservation",
    "SourceAdapter",
    "SourceFailure",
]
