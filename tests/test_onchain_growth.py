import asyncio

from analyzers.base import epoch_seconds
from analyzers.onchain_growth import OnChainGrowthAnalyzer


def test_tvl_growth_from_snapshot_baseline(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, clients={}, now=fixed_now)

    result = asyncio.run(OnChainGrowthAnalyzer().analyze(context))

    growth = result.metrics["tvl_growth"]
    assert growth["change_30d_pct"] == 25.0
    assert round(growth["change_90d_pct"], 2) == round((500_000 - 300_000) / 300_000 * 100, 2)


def test_always_null_metrics_not_covered_by_free_sources(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, clients={}, now=fixed_now)

    result = asyncio.run(OnChainGrowthAnalyzer().analyze(context))

    assert result.metrics["active_address_growth"] is None
    assert result.metrics["transaction_count_growth"] is None
    assert result.metrics["new_holder_growth"] is None
    assert result.metrics["exchange_net_flow"] is None
    assert result.data_quality["status"] == "partial"


def test_stablecoin_inflow_not_applicable_for_non_chain_coin(context_factory, base_snapshot, fixed_now):
    class FakeDefiLlama:
        def build_chain_gecko_index(self):
            return {}

    context = context_factory(base_snapshot, clients={"defillama": FakeDefiLlama()}, now=fixed_now)

    result = asyncio.run(OnChainGrowthAnalyzer().analyze(context))

    assert result.metrics["stablecoin_inflow"]["status"] == "not_applicable"


def test_stablecoin_inflow_computed_for_matching_l1_chain(context_factory, base_snapshot, fixed_now):
    epoch_now = epoch_seconds(fixed_now, 0)
    epoch_30 = epoch_seconds(fixed_now, 30)
    epoch_90 = epoch_seconds(fixed_now, 90)

    class FakeDefiLlama:
        def build_chain_gecko_index(self):
            return {"test-coin": {"name": "Test Chain"}}

        def get_chain_stablecoin_mcap_at_or_before(self, chain_name, epoch):
            assert chain_name == "Test Chain"
            return {epoch_now: 1000.0, epoch_30: 800.0, epoch_90: 500.0}.get(epoch)

    context = context_factory(base_snapshot, clients={"defillama": FakeDefiLlama()}, now=fixed_now)

    result = asyncio.run(OnChainGrowthAnalyzer().analyze(context))

    inflow = result.metrics["stablecoin_inflow"]
    assert inflow["current"] == 1000.0
    assert inflow["change_30d_pct"] == 25.0
    assert inflow["change_90d_pct"] == 100.0
