from datetime import datetime, timezone

from analyzers.base import epoch_seconds, growth_from_snapshot_baseline, pct_change, percentile_rank_cheapness


def test_pct_change_normal():
    assert pct_change(110, 100) == 10.0
    assert pct_change(90, 100) == -10.0


def test_pct_change_none_when_inputs_missing():
    assert pct_change(None, 100) is None
    assert pct_change(100, None) is None
    assert pct_change(100, 0) is None


def test_growth_from_snapshot_baseline():
    snapshot = {
        "tvl_usd": 120,
        "baseline_30d": {"tvl_usd": 100},
        "baseline_90d": {"tvl_usd": 80},
    }
    result = growth_from_snapshot_baseline(snapshot, "tvl_usd")
    assert result["current"] == 120
    assert result["change_30d_pct"] == 20.0
    assert result["change_90d_pct"] == 50.0


def test_growth_from_snapshot_baseline_missing_baseline():
    snapshot = {"tvl_usd": 120, "baseline_30d": {}, "baseline_90d": {}}
    result = growth_from_snapshot_baseline(snapshot, "tvl_usd")
    assert result["change_30d_pct"] is None
    assert result["change_90d_pct"] is None


def test_percentile_rank_cheapness_higher_for_cheaper_coin():
    peers = [10, 20, 30, 40]
    assert percentile_rank_cheapness(5, peers) == 100.0
    assert percentile_rank_cheapness(50, peers) == 0.0
    assert percentile_rank_cheapness(25, peers) == 50.0


def test_percentile_rank_cheapness_none_with_too_few_peers():
    assert percentile_rank_cheapness(5, [10]) is None
    assert percentile_rank_cheapness(None, [10, 20]) is None


def test_epoch_seconds_days_ago():
    now = datetime(2026, 7, 5, tzinfo=timezone.utc)
    assert epoch_seconds(now, 0) == int(now.timestamp())
    assert epoch_seconds(now, 30) < epoch_seconds(now, 0)
