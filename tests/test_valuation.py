import asyncio

from analyzers.valuation import ValuationAnalyzer


def _peer(mc, tvl, fees):
    return {"market_cap_usd": mc, "tvl_usd": tvl, "fees_24h_usd": fees}


def test_raw_ratios_computed(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, clients={}, config={"analysis": {"min_sector_peers": 5}}, now=fixed_now)

    result = asyncio.run(ValuationAnalyzer().analyze(context))

    assert result.metrics["mc_to_tvl"] == 1_000_000 / 500_000
    assert result.metrics["fdv_to_mc"] == 2_000_000 / 1_000_000
    assert result.metrics["mc_to_fees_annualized"] == 1_000_000 / (1_000 * 365)


def test_percentile_none_when_insufficient_peers(context_factory, base_snapshot, fixed_now):
    peers = [_peer(2_000_000, 500_000, 1_000)]  # 표본 1개 < min_sector_peers
    context = context_factory(base_snapshot, sector_peers=peers,
                               config={"analysis": {"min_sector_peers": 5}}, now=fixed_now)

    result = asyncio.run(ValuationAnalyzer().analyze(context))

    assert result.metrics["mc_to_tvl_percentile"] is None
    assert result.data_quality["status"] == "partial"


def test_percentile_computed_with_enough_peers(context_factory, base_snapshot, fixed_now):
    # base_snapshot mc_to_tvl = 1,000,000/500,000 = 2.0 (동료보다 저렴해야 높은 백분위)
    peers = [_peer(3_000_000, 500_000, 1_000), _peer(4_000_000, 500_000, 1_000),
              _peer(5_000_000, 500_000, 1_000), _peer(6_000_000, 500_000, 1_000),
              _peer(7_000_000, 500_000, 1_000)]
    context = context_factory(base_snapshot, sector_peers=peers,
                               config={"analysis": {"min_sector_peers": 5}}, now=fixed_now)

    result = asyncio.run(ValuationAnalyzer().analyze(context))

    assert result.metrics["mc_to_tvl_percentile"] == 100.0
    assert result.data_quality["status"] == "ok"
