from unittest.mock import MagicMock

from datasources.rss import RSSClient

SAMPLE_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test Feed</title>
<item><title>Headline One</title><link>https://example.com/1</link>
<pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_get_headlines_parses_feed_entries(tmp_cache):
    client = RSSClient(cache=tmp_cache, feeds=[{"name": "Test", "url": "https://example.com/rss"}], max_retries=1)
    response = MagicMock()
    response.status_code = 200
    response.content = SAMPLE_RSS
    response.headers = {}
    response.raise_for_status.return_value = None
    client.session = MagicMock()
    client.session.request.return_value = response

    headlines = client.get_headlines()

    assert len(headlines) == 1
    assert headlines[0]["title"] == "Headline One"
    assert headlines[0]["source"] == "Test"


def test_get_headlines_continues_when_one_feed_fails(tmp_cache):
    client = RSSClient(
        cache=tmp_cache,
        feeds=[{"name": "Broken", "url": "https://broken.example.com/rss"}],
        max_retries=1,
    )
    response = MagicMock()
    response.status_code = 500
    response.headers = {}
    client.session = MagicMock()
    client.session.request.return_value = response

    headlines = client.get_headlines()

    assert headlines == []
