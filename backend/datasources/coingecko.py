import logging
from typing import Optional

from .base import BaseDataSource

logger = logging.getLogger(__name__)

# 과거 시점 스냅샷은 값이 변하지 않으므로(불변 데이터) 오래 캐시해도 안전하다.
HISTORY_TTL_SECONDS = 60 * 60 * 24 * 30


class CoinGeckoClient(BaseDataSource):
    def __init__(
        self,
        cache=None,
        api_key: Optional[str] = None,
        base_url: str = "https://api.coingecko.com/api/v3",
        **kwargs,
    ):
        super().__init__(name="coingecko", base_url=base_url, cache=cache, **kwargs)
        self.api_key = api_key

    def _auth_params(self, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        if self.api_key:
            params["x_cg_demo_api_key"] = self.api_key
        return params

    def get_markets_page(self, vs_currency: str = "usd", per_page: int = 250, page: int = 1) -> list:
        params = self._auth_params({
            "vs_currency": vs_currency,
            "order": "market_cap_desc",
            "per_page": per_page,
            "page": page,
            "sparkline": "false",
            "price_change_percentage": "24h",
        })
        cache_key = f"coingecko:markets:{vs_currency}:{per_page}:{page}"
        return self.fetch_json("/coins/markets", params=params, cache_key=cache_key, ttl_seconds=3600) or []

    def get_top_coins(
        self, vs_currency: str = "usd", per_page: int = 250, max_pages: int = 2, top_n: int = 300
    ) -> list:
        coins = []
        seen_ids = set()
        for page in range(1, max_pages + 1):
            page_data = self.get_markets_page(vs_currency=vs_currency, per_page=per_page, page=page)
            if not page_data:
                break
            for coin in page_data:
                if coin["id"] in seen_ids:
                    continue
                seen_ids.add(coin["id"])
                coins.append(coin)
            if len(page_data) < per_page:
                break
        return coins[:top_n]

    def get_coin_detail(self, coin_id: str) -> dict:
        cache_key = f"coingecko:detail:{coin_id}"
        params = self._auth_params({
            "localization": "false",
            "tickers": "false",
            "market_data": "false",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "false",
        })
        return self.fetch_json(f"/coins/{coin_id}", params=params, cache_key=cache_key, ttl_seconds=86400) or {}

    def get_market_chart(self, coin_id: str, days: int = 200, vs_currency: str = "usd") -> dict:
        """RSI/이동평균/구간 고점 계산용 일별 가격 시계열. {"prices": [[ts_ms, price], ...]}"""
        cache_key = f"coingecko:market_chart:{coin_id}:{days}"
        params = self._auth_params({"vs_currency": vs_currency, "days": days, "interval": "daily"})
        return self.fetch_json(
            f"/coins/{coin_id}/market_chart", params=params, cache_key=cache_key, ttl_seconds=43200
        ) or {}

    def get_global_market_data(self) -> dict:
        """BTC/ETH 도미넌스 등 시장 전체 지표. {"btc_dominance_pct":, "eth_dominance_pct":, ...}"""
        data = self.fetch_json(
            "/global", params=self._auth_params(), cache_key="coingecko:global", ttl_seconds=3600
        ) or {}
        payload = data.get("data") or {}
        dominance = payload.get("market_cap_percentage") or {}
        return {
            "btc_dominance_pct": dominance.get("btc"),
            "eth_dominance_pct": dominance.get("eth"),
            "total_market_cap_usd": (payload.get("total_market_cap") or {}).get("usd"),
            "market_cap_change_24h_pct": payload.get("market_cap_change_percentage_24h_usd"),
        }

    def get_historical_snapshot(self, coin_id: str, date_ddmmyyyy: str) -> dict:
        """30/90일 전 등 특정 과거 날짜의 가격/시총/거래량 스냅샷을 소급 조회한다."""
        cache_key = f"coingecko:history:{coin_id}:{date_ddmmyyyy}"
        params = self._auth_params({"date": date_ddmmyyyy, "localization": "false"})
        data = self.fetch_json(
            f"/coins/{coin_id}/history", params=params, cache_key=cache_key, ttl_seconds=HISTORY_TTL_SECONDS
        )
        market_data = (data or {}).get("market_data") or {}
        return {
            "price_usd": (market_data.get("current_price") or {}).get("usd"),
            "market_cap_usd": (market_data.get("market_cap") or {}).get("usd"),
            "volume_24h_usd": (market_data.get("total_volume") or {}).get("usd"),
        }
