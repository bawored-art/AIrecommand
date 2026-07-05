import asyncio

from common.llm_client import LLMUnavailableError

from analyzers.catalyst import CatalystAnalyzer

HEADLINES = [
    {"title": "Test Coin announces mainnet upgrade", "source": "CoinDesk",
     "link": "https://example.com/1", "published": "2026-06-01"},
    {"title": "Test Coin price chart looks nice", "source": "CoinDesk",
     "link": "https://example.com/2", "published": "2026-06-02"},
]


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def classify_batch(self, system_prompt, items, schema_hint):
        self.calls.append(items)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_no_headlines_returns_zero_catalysts(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, headlines=[], clients={"llm": FakeLLM([])}, now=fixed_now)

    result = asyncio.run(CatalystAnalyzer().analyze(context))

    assert result.metrics["catalyst_count"] == 0
    assert result.data_quality["status"] == "ok"


def test_unavailable_when_llm_client_missing(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, headlines=HEADLINES, clients={"llm": None}, now=fixed_now)

    result = asyncio.run(CatalystAnalyzer().analyze(context))

    assert result.metrics["catalysts"] is None
    assert result.data_quality["status"] == "unavailable"
    # 헤드라인 원문은 evidence로 항상 남는다 (LLM 가용성과 무관)
    assert len(result.evidence) == 2


def test_unavailable_when_llm_raises(context_factory, base_snapshot, fixed_now):
    llm = FakeLLM(LLMUnavailableError("no api key"))
    context = context_factory(base_snapshot, headlines=HEADLINES, clients={"llm": llm}, now=fixed_now)

    result = asyncio.run(CatalystAnalyzer().analyze(context))

    assert result.data_quality["status"] == "unavailable"


def test_filters_out_none_type_catalysts(context_factory, base_snapshot, fixed_now):
    llm = FakeLLM([
        {"catalyst_type": "mainnet_upgrade", "event_date": "2026-08-01", "confidence": 0.9, "summary": "메인넷 업그레이드"},
        {"catalyst_type": "none", "event_date": None, "confidence": 0.1, "summary": "관련 없음"},
    ])
    context = context_factory(base_snapshot, headlines=HEADLINES, clients={"llm": llm}, now=fixed_now)

    result = asyncio.run(CatalystAnalyzer().analyze(context))

    assert result.metrics["catalyst_count"] == 1
    assert result.metrics["catalysts"][0]["catalyst_type"] == "mainnet_upgrade"
    assert result.metrics["catalysts"][0]["url"] == "https://example.com/1"
    assert result.data_quality["status"] == "ok"
