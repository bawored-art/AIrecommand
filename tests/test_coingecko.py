from unittest.mock import MagicMock

from datasources.coingecko import CoinGeckoClient


def test_get_top_coins_merges_pages_and_dedups(tmp_cache, mock_json_response):
    client = CoinGeckoClient(cache=tmp_cache, max_retries=1)
    page1 = [{"id": f"coin{i}", "symbol": f"c{i}", "name": f"Coin{i}"} for i in range(250)]
    page2 = [{"id": f"coin{i}", "symbol": f"c{i}", "name": f"Coin{i}"} for i in range(200, 260)]
    client.session = MagicMock()
    client.session.request.side_effect = [
        mock_json_response(page1),
        mock_json_response(page2),
    ]

    coins = client.get_top_coins(per_page=250, max_pages=2, top_n=300)

    ids = [c["id"] for c in coins]
    assert len(ids) == len(set(ids))
    assert len(coins) <= 300
    assert client.session.request.call_count == 2


def test_get_historical_snapshot_parses_market_data(tmp_cache, mock_json_response):
    client = CoinGeckoClient(cache=tmp_cache, max_retries=1)
    client.session = MagicMock()
    client.session.request.return_value = mock_json_response({
        "market_data": {
            "current_price": {"usd": 1.23},
            "market_cap": {"usd": 456.0},
            "total_volume": {"usd": 78.0},
        }
    })

    result = client.get_historical_snapshot("bitcoin", "01-01-2026")

    assert result["price_usd"] == 1.23
    assert result["market_cap_usd"] == 456.0
    assert result["volume_24h_usd"] == 78.0


def test_get_global_market_data_parses_dominance(tmp_cache, mock_json_response):
    client = CoinGeckoClient(cache=tmp_cache, max_retries=1)
    client.session = MagicMock()
    client.session.request.return_value = mock_json_response({
        "data": {
            "market_cap_percentage": {"btc": 55.5, "eth": 12.3},
            "total_market_cap": {"usd": 2_000_000_000_000},
            "market_cap_change_percentage_24h_usd": -1.5,
        }
    })

    result = client.get_global_market_data()

    assert result["btc_dominance_pct"] == 55.5
    assert result["eth_dominance_pct"] == 12.3
    assert result["total_market_cap_usd"] == 2_000_000_000_000
    assert result["market_cap_change_24h_pct"] == -1.5
