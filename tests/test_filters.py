from pipeline.filters import (
    apply_filters,
    is_stablecoin,
    is_suspected_scam,
    is_wrapped_token,
    passes_min_volume,
)


def test_is_stablecoin_by_symbol(base_filters_cfg):
    assert is_stablecoin({"symbol": "USDT"}, base_filters_cfg)


def test_is_stablecoin_by_category(base_filters_cfg):
    assert is_stablecoin({"symbol": "xyz", "categories": ["Stablecoins"]}, base_filters_cfg)


def test_is_stablecoin_false_for_normal_coin(base_filters_cfg):
    assert not is_stablecoin({"symbol": "eth", "categories": ["Smart Contract Platform"]}, base_filters_cfg)


def test_is_wrapped_token_by_name_pattern(base_filters_cfg):
    assert is_wrapped_token({"name": "Wrapped Bitcoin", "symbol": "wbtc"}, base_filters_cfg)


def test_is_wrapped_token_false_for_normal_coin(base_filters_cfg):
    assert not is_wrapped_token({"name": "Waves", "symbol": "waves"}, base_filters_cfg)


def test_is_suspected_scam_zero_supply(base_filters_cfg):
    coin = {"circulating_supply": 0, "market_cap": 100, "total_volume": 10}
    assert is_suspected_scam(coin, base_filters_cfg)


def test_is_suspected_scam_extreme_mcap_volume_ratio(base_filters_cfg):
    coin = {"circulating_supply": 1000, "market_cap": 10_000_000, "total_volume": 100}
    assert is_suspected_scam(coin, base_filters_cfg)


def test_is_suspected_scam_false_for_healthy_coin(base_filters_cfg):
    coin = {"circulating_supply": 19_000_000, "market_cap": 1e12, "total_volume": 1e10}
    assert not is_suspected_scam(coin, base_filters_cfg)


def test_passes_min_volume(base_filters_cfg):
    assert passes_min_volume({"total_volume": 3_000_000}, base_filters_cfg)
    assert not passes_min_volume({"total_volume": 1_000_000}, base_filters_cfg)


def test_apply_filters_end_to_end(base_filters_cfg):
    coins = [
        {"id": "btc", "symbol": "btc", "name": "Bitcoin",
         "market_cap": 1e12, "total_volume": 1e10, "circulating_supply": 19_000_000},
        {"id": "usdt", "symbol": "usdt", "name": "Tether",
         "market_cap": 1e11, "total_volume": 1e10, "circulating_supply": 1e11},
        {"id": "wbtc", "symbol": "wbtc", "name": "Wrapped Bitcoin",
         "market_cap": 1e9, "total_volume": 1e7, "circulating_supply": 100000},
        {"id": "lowvol", "symbol": "lv", "name": "LowVol Coin",
         "market_cap": 1e7, "total_volume": 100, "circulating_supply": 1000},
    ]

    kept, rejected = apply_filters(coins, base_filters_cfg)

    assert {c["id"] for c in kept} == {"btc"}
    assert {r["id"] for r in rejected} == {"usdt", "wbtc", "lowvol"}
