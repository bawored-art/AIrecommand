import asyncio

from analyzers.news import NewsAnalyzer

HEADLINES = [
    {"title": "Test Coin partners with major exchange", "source": "CoinDesk", "link": "https://example.com/1"},
    {"title": "Test Coin faces network outage", "source": "CoinDesk", "link": "https://example.com/2"},
]


class FakeLLM:
    def __init__(self, response):
        self.response = response

    def classify_batch(self, system_prompt, items, schema_hint):
        return self.response


def test_no_headlines_returns_zero_counts(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, headlines=[], clients={"llm": FakeLLM([])}, now=fixed_now)

    result = asyncio.run(NewsAnalyzer().analyze(context))

    assert result.metrics["headlines_evaluated"] == 0
    assert result.data_quality["status"] == "ok"


def test_unavailable_when_llm_missing(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, headlines=HEADLINES, clients={"llm": None}, now=fixed_now)

    result = asyncio.run(NewsAnalyzer().analyze(context))

    assert result.data_quality["status"] == "unavailable"


def test_sentiment_aggregation(context_factory, base_snapshot, fixed_now):
    llm = FakeLLM([
        {"sentiment": "positive", "impact": 0.8},
        {"sentiment": "negative", "impact": 0.4},
    ])
    context = context_factory(base_snapshot, headlines=HEADLINES, clients={"llm": llm}, now=fixed_now)

    result = asyncio.run(NewsAnalyzer().analyze(context))

    assert result.metrics["positive_count"] == 1
    assert result.metrics["negative_count"] == 1
    assert result.metrics["neutral_count"] == 0
    assert result.metrics["net_sentiment_score"] == round((0.8 - 0.4) / 2, 3)
    assert result.data_quality["status"] == "ok"
