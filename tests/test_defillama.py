from unittest.mock import MagicMock

from datasources.defillama import DefiLlamaClient


def test_build_gecko_id_index_only_keeps_matched_protocols(tmp_cache, mock_json_response):
    client = DefiLlamaClient(cache=tmp_cache, max_retries=1)
    client.session = MagicMock()
    client.session.request.return_value = mock_json_response([
        {"slug": "uniswap", "gecko_id": "uniswap", "tvl": 100},
        {"slug": "no-gecko-id", "tvl": 5},
    ])

    index = client.build_gecko_id_index()

    assert "uniswap" in index
    assert "no-gecko-id" not in index


def test_get_tvl_at_or_before_picks_closest_past_point(tmp_cache, mock_json_response):
    client = DefiLlamaClient(cache=tmp_cache, max_retries=1)
    client.session = MagicMock()
    client.session.request.return_value = mock_json_response({
        "tvl": [
            {"date": 1000, "totalLiquidityUSD": 10},
            {"date": 2000, "totalLiquidityUSD": 20},
            {"date": 3000, "totalLiquidityUSD": 30},
        ]
    })

    value = client.get_tvl_at_or_before("uniswap", target_epoch_seconds=2500)

    assert value == 20


def test_get_tvl_at_or_before_returns_none_when_no_history_before_target(tmp_cache, mock_json_response):
    client = DefiLlamaClient(cache=tmp_cache, max_retries=1)
    client.session = MagicMock()
    client.session.request.return_value = mock_json_response({"tvl": [{"date": 5000, "totalLiquidityUSD": 50}]})

    value = client.get_tvl_at_or_before("uniswap", target_epoch_seconds=1000)

    assert value is None
