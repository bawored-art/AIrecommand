from pipeline.analyze import build_headline_index, build_sector_peers_index


def test_build_headline_index_matches_by_symbol_word_boundary():
    coins = [{"id": "ethereum", "symbol": "eth", "name": "Ethereum"}]
    headlines = [
        {"title": "ETH price surges today"},
        {"title": "New payment method launched"},  # 'method'에 'eth'가 포함되지만 단어 경계 불일치
        {"title": "Ethereum upgrade announced"},
    ]

    index = build_headline_index(coins, headlines)

    titles = {h["title"] for h in index["ethereum"]}
    assert titles == {"ETH price surges today", "Ethereum upgrade announced"}


def test_build_sector_peers_index_groups_by_shared_category():
    coins = [
        {"id": "a", "categories": ["Layer 1 (L1)"], "market_cap_usd": 300},
        {"id": "b", "categories": ["Layer 1 (L1)"], "market_cap_usd": 500},
        {"id": "c", "categories": ["DeFi"], "market_cap_usd": 100},
    ]

    peers = build_sector_peers_index(coins)

    assert {p["id"] for p in peers["a"]} == {"b"}
    assert {p["id"] for p in peers["c"]} == set()


def test_build_sector_peers_index_sorted_by_market_cap_desc():
    coins = [
        {"id": "a", "categories": ["L1"], "market_cap_usd": 100},
        {"id": "b", "categories": ["L1"], "market_cap_usd": 500},
        {"id": "c", "categories": ["L1"], "market_cap_usd": 300},
    ]

    peers = build_sector_peers_index(coins)

    assert [p["id"] for p in peers["a"]] == ["b", "c"]
