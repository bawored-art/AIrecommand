import json
from datetime import date
from unittest.mock import MagicMock

from datasources.base import DataSourceError
from pipeline.backfill import get_baseline


def test_get_baseline_uses_local_history_when_available(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    today = date(2026, 7, 5)
    target_date = date(2026, 6, 5)  # 30일 전
    snapshot_payload = {
        "date": target_date.isoformat(),
        "coins": [{"id": "bitcoin", "price_usd": 50000, "market_cap_usd": 1e12,
                    "volume_24h_usd": 2e10, "tvl_usd": None}],
    }
    (raw_dir / f"{target_date.isoformat()}.json").write_text(json.dumps(snapshot_payload), encoding="utf-8")

    baseline = get_baseline("bitcoin", today, 30, str(raw_dir))

    assert baseline["source"] == "local_history"
    assert baseline["price_usd"] == 50000


def test_get_baseline_falls_back_to_api_when_local_missing(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    today = date(2026, 7, 5)

    mock_cg = MagicMock()
    mock_cg.get_historical_snapshot.return_value = {
        "price_usd": 42.0, "market_cap_usd": 1e9, "volume_24h_usd": 1e8,
    }

    baseline = get_baseline("ethereum", today, 90, str(raw_dir), coingecko_client=mock_cg)

    assert baseline["source"] == "api_backfill"
    assert baseline["price_usd"] == 42.0
    mock_cg.get_historical_snapshot.assert_called_once()


def test_get_baseline_missing_when_no_sources_available(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    today = date(2026, 7, 5)

    baseline = get_baseline("unknown-coin", today, 30, str(raw_dir))

    assert baseline["source"] == "missing"
    assert baseline["price_usd"] is None


def test_get_baseline_handles_api_error_gracefully(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    today = date(2026, 7, 5)
    mock_cg = MagicMock()
    mock_cg.get_historical_snapshot.side_effect = DataSourceError("boom")

    baseline = get_baseline("ethereum", today, 30, str(raw_dir), coingecko_client=mock_cg)

    assert baseline["source"] == "missing"


def test_get_baseline_uses_defillama_tvl_when_price_history_missing(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    today = date(2026, 7, 5)

    mock_defillama = MagicMock()
    mock_defillama.get_tvl_at_or_before.return_value = 12345.0

    baseline = get_baseline(
        "ethereum", today, 30, str(raw_dir),
        coingecko_client=None, defillama_client=mock_defillama, defillama_slug="aave",
    )

    assert baseline["tvl_usd"] == 12345.0
    assert baseline["source"] == "api_backfill"
