import asyncio

from datasources.base import DataSourceError

from analyzers.technical import TechnicalAnalyzer, _compute_rsi

KNOWN_PRICES = [100, 102, 101, 105, 107, 106, 110, 111, 109, 108, 112, 115, 114, 116, 118]


def test_compute_rsi_matches_hand_calculation():
    # 직접 계산한 기대값: avg_gain=24/14, avg_loss=6/14, RS=4.0 -> RSI=100-100/5=80.0
    assert _compute_rsi(KNOWN_PRICES, period=14) == 80.0


def test_compute_rsi_none_when_insufficient_data():
    assert _compute_rsi([100, 101, 102], period=14) is None


class FakeCoinGecko:
    def __init__(self, prices):
        self.prices = prices

    def get_market_chart(self, coin_id, days=200):
        return {"prices": [[i, p] for i, p in enumerate(self.prices)]}


class FailingCoinGecko:
    def get_market_chart(self, coin_id, days=200):
        raise DataSourceError("boom")


def test_returns_use_snapshot_baseline_not_chart(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, clients={"coingecko": FakeCoinGecko(KNOWN_PRICES)}, now=fixed_now)

    result = asyncio.run(TechnicalAnalyzer().analyze(context))

    assert result.metrics["return_30d_pct"] is not None
    assert result.metrics["rsi_14"] == 80.0


def test_partial_when_insufficient_chart_history(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, clients={"coingecko": FakeCoinGecko(KNOWN_PRICES)}, now=fixed_now)

    result = asyncio.run(TechnicalAnalyzer().analyze(context))

    assert result.metrics["ma_200d_deviation_pct"] is None
    assert result.data_quality["status"] == "partial"


def test_unavailable_when_coingecko_disabled(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, clients={"coingecko": None}, now=fixed_now)

    result = asyncio.run(TechnicalAnalyzer().analyze(context))

    assert result.metrics["rsi_14"] is None
    assert result.data_quality["status"] == "partial"


def test_partial_when_market_chart_fetch_fails(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, clients={"coingecko": FailingCoinGecko()}, now=fixed_now)

    result = asyncio.run(TechnicalAnalyzer().analyze(context))

    assert result.metrics["rsi_14"] is None
    assert result.data_quality["status"] == "partial"
