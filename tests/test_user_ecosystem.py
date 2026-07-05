import asyncio

import pytest

from analyzers.base import epoch_seconds
from analyzers.user_ecosystem import UserEcosystemAnalyzer


def test_dau_trend_always_null(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, clients={}, now=fixed_now)

    result = asyncio.run(UserEcosystemAnalyzer().analyze(context))

    assert result.metrics["dau_trend"] is None


def test_fees_growth_unavailable_without_defillama(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, clients={"defillama": None}, now=fixed_now)

    result = asyncio.run(UserEcosystemAnalyzer().analyze(context))

    assert result.metrics["fees_growth"]["status"] == "unavailable"


def test_fees_growth_not_applicable_when_no_protocol_match(context_factory, base_snapshot, fixed_now):
    class FakeDefiLlama:
        def build_gecko_id_index(self):
            return {}

    context = context_factory(base_snapshot, clients={"defillama": FakeDefiLlama()}, now=fixed_now)

    result = asyncio.run(UserEcosystemAnalyzer().analyze(context))

    assert result.metrics["fees_growth"]["status"] == "not_applicable"


def test_fees_growth_computed_when_protocol_matches(context_factory, base_snapshot, fixed_now):
    epoch_now = epoch_seconds(fixed_now, 0)
    epoch_30 = epoch_seconds(fixed_now, 30)
    epoch_90 = epoch_seconds(fixed_now, 90)

    class FakeDefiLlama:
        def build_gecko_id_index(self):
            return {"test-coin": {"slug": "test-protocol"}}

        def get_fees_at_or_before(self, slug, epoch):
            assert slug == "test-protocol"
            return {epoch_now: 200.0, epoch_30: 150.0, epoch_90: 100.0}.get(epoch)

    context = context_factory(base_snapshot, clients={"defillama": FakeDefiLlama()}, now=fixed_now)

    result = asyncio.run(UserEcosystemAnalyzer().analyze(context))

    growth = result.metrics["fees_growth"]
    assert growth["current"] == 200.0
    assert growth["change_30d_pct"] == pytest.approx(33.33, abs=0.1)
    assert growth["change_90d_pct"] == 100.0
