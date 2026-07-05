import asyncio

from analyzers.risk import RiskAnalyzer

SAFE_HEADLINES = [{"title": "Test Coin launches new dashboard", "source": "CoinDesk", "link": "https://example.com/1"}]
RISK_HEADLINES = [{"title": "Test Coin suffers hack, funds stolen", "source": "CoinDesk", "link": "https://example.com/2"}]


class FakeLLM:
    def __init__(self, response):
        self.response = response

    def classify_batch(self, system_prompt, items, schema_hint):
        return self.response


def test_liquidity_ratio_flagged_when_low(context_factory, base_snapshot, fixed_now):
    base_snapshot["volume_24h_usd"] = 1_000.0  # /1,000,000 mc = 0.001 < 0.01 threshold
    context = context_factory(base_snapshot, headlines=[], clients={"llm": None}, now=fixed_now)

    result = asyncio.run(RiskAnalyzer().analyze(context))

    assert result.metrics["liquidity_ratio"] == 0.001
    assert any(f["type"] == "low_liquidity" for f in result.metrics["risk_flags"])


def test_always_null_metrics_for_unlock_and_whale(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, headlines=[], clients={"llm": None}, now=fixed_now)

    result = asyncio.run(RiskAnalyzer().analyze(context))

    assert result.metrics["token_unlock_schedule"] is None
    assert result.metrics["whale_concentration"] is None


def test_no_risk_keyword_headlines_yields_empty_lists_without_llm_call(context_factory, base_snapshot, fixed_now):
    llm = FakeLLM([{"risk_type": "hack", "severity": "high", "summary": "should not be called"}])
    context = context_factory(base_snapshot, headlines=SAFE_HEADLINES, clients={"llm": llm}, now=fixed_now)

    result = asyncio.run(RiskAnalyzer().analyze(context))

    assert result.metrics["hack_history"] == []
    assert result.metrics["regulatory_issues"] == []


def test_hack_extracted_from_matching_headline(context_factory, base_snapshot, fixed_now):
    llm = FakeLLM([{"risk_type": "hack", "severity": "high", "summary": "해킹으로 자금 유출"}])
    context = context_factory(base_snapshot, headlines=RISK_HEADLINES, clients={"llm": llm}, now=fixed_now)

    result = asyncio.run(RiskAnalyzer().analyze(context))

    assert len(result.metrics["hack_history"]) == 1
    assert result.metrics["hack_history"][0]["risk_type"] == "hack"
    assert any(f["type"] == "hack" for f in result.metrics["risk_flags"])


def test_null_hack_history_when_llm_missing_but_keywords_present(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, headlines=RISK_HEADLINES, clients={"llm": None}, now=fixed_now)

    result = asyncio.run(RiskAnalyzer().analyze(context))

    assert result.metrics["hack_history"] is None
    assert result.metrics["regulatory_issues"] is None
