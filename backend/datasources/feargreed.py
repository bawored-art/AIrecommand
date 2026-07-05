import logging

from .base import BaseDataSource

logger = logging.getLogger(__name__)


class FearGreedClient(BaseDataSource):
    """alternative.me의 무료 Fear & Greed Index API. API 키 불필요."""

    def __init__(self, cache=None, base_url: str = "https://api.alternative.me", **kwargs):
        super().__init__(name="feargreed", base_url=base_url, cache=cache, **kwargs)

    def get_latest(self) -> dict:
        data = self.fetch_json(
            "/fng/", params={"limit": 1}, cache_key="feargreed:latest", ttl_seconds=3600
        ) or {}
        entries = data.get("data") or []
        if not entries:
            return {}
        entry = entries[0]
        value = entry.get("value")
        return {
            "value": int(value) if value is not None else None,
            "classification": entry.get("value_classification"),
            "timestamp": entry.get("timestamp"),
        }
