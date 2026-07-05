import logging

import feedparser

from .base import BaseDataSource, DataSourceError

logger = logging.getLogger(__name__)


class RSSClient(BaseDataSource):
    def __init__(self, cache=None, feeds=None, **kwargs):
        super().__init__(name="rss", base_url="", cache=cache, **kwargs)
        self.feeds = feeds or []

    def get_headlines(self, limit_per_feed: int = 30) -> list:
        headlines = []
        for feed in self.feeds:
            try:
                headlines.extend(self._fetch_feed(feed["name"], feed["url"], limit_per_feed))
            except DataSourceError as exc:
                logger.warning("rss: failed to fetch feed %s: %s", feed["name"], exc)
        return headlines

    def _fetch_feed(self, name: str, url: str, limit: int) -> list:
        cache_key = f"rss:{name}"

        def _do_fetch():
            response = self._request("GET", url)
            parsed = feedparser.parse(response.content)
            entries = []
            for entry in parsed.entries[:limit]:
                entries.append({
                    "source": name,
                    "title": entry.get("title"),
                    "link": entry.get("link"),
                    "published": entry.get("published") or entry.get("updated"),
                })
            return entries

        if self.cache is None:
            return _do_fetch()
        return self.cache.get_or_set(cache_key, _do_fetch, ttl_seconds=3600)
