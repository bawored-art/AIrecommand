from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from analyzers.base import AnalysisContext
from common.cache import FileCache


@pytest.fixture
def tmp_cache(tmp_path):
    return FileCache(cache_dir=str(tmp_path / "cache"), default_ttl_seconds=3600)


@pytest.fixture
def base_filters_cfg():
    return {
        "min_daily_volume_usd": 2_000_000,
        "exclude_stablecoins": True,
        "exclude_wrapped_tokens": True,
        "exclude_suspected_scams": True,
        "stablecoin_symbols": ["usdt", "usdc", "dai"],
        "stablecoin_categories": ["stablecoins"],
        "wrapped_categories": ["wrapped-tokens"],
        "wrapped_token_patterns": [r"\bwrapped\b", r"\bstaked\b", r"\bbridged\b"],
        "scam_heuristics": {
            "max_mcap_to_volume_ratio": 5000,
            "require_positive_supply": True,
        },
    }


def _mock_json_response(json_data, status_code=200, headers=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.headers = headers or {}
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def mock_json_response():
    return _mock_json_response


@pytest.fixture
def fixed_now():
    return datetime(2026, 7, 5, tzinfo=timezone.utc)


@pytest.fixture
def base_snapshot():
    return {
        "id": "test-coin", "symbol": "tst", "name": "Test Coin",
        "price_usd": 100.0, "market_cap_usd": 1_000_000.0, "volume_24h_usd": 50_000.0,
        "circulating_supply": 10_000.0, "fdv_usd": 2_000_000.0, "categories": ["Layer 1 (L1)"],
        "tvl_usd": 500_000.0, "fees_24h_usd": 1_000.0,
        "github_owner_repo": "test-org/test-repo", "github_stars": 100,
        "commits_30d": 60, "commits_90d": 150,
        "baseline_30d": {"price_usd": 90.0, "market_cap_usd": 900_000.0,
                          "volume_24h_usd": 40_000.0, "tvl_usd": 400_000.0},
        "baseline_90d": {"price_usd": 80.0, "market_cap_usd": 800_000.0,
                          "volume_24h_usd": 30_000.0, "tvl_usd": 300_000.0},
        "data_flags": {"defillama": "ok", "github": "ok"},
    }


def make_context(snapshot, clients=None, sector_peers=None, headlines=None, config=None, now=None):
    return AnalysisContext(
        coin_id=snapshot["id"], symbol=snapshot["symbol"], name=snapshot["name"],
        snapshot=snapshot, sector_peers=sector_peers or [], headlines=headlines or [],
        clients=clients or {}, config=config or {}, now=now or datetime(2026, 7, 5, tzinfo=timezone.utc),
    )


@pytest.fixture
def context_factory():
    return make_context


def make_analyzer_bundle(onchain=None, user=None, developer=None, technical=None,
                          catalyst=None, valuation=None, risk=None, statuses=None):
    """Stage2 analysis.json의 coin["analyzers"] 형태를 흉내낸 테스트 픽스처."""
    statuses = statuses or {}

    def _entry(metrics, name, evidence=None):
        return {
            "metrics": metrics or {},
            "evidence": evidence or [],
            "data_quality": {"status": statuses.get(name, "ok")},
        }

    return {
        "onchain_growth": _entry(onchain, "onchain_growth"),
        "user_ecosystem": _entry(user, "user_ecosystem"),
        "developer": _entry(developer, "developer"),
        "technical": _entry(technical, "technical"),
        "catalyst": _entry(catalyst, "catalyst"),
        "valuation": _entry(valuation, "valuation"),
        "risk": _entry(risk, "risk"),
        "news": _entry({}, "news"),
    }
