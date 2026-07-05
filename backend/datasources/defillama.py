import logging
from typing import Optional

from .base import BaseDataSource

logger = logging.getLogger(__name__)

# 스테이블코인 관련 엔드포인트는 api.llama.fi가 아닌 별도 서브도메인에서 서비스된다.
STABLECOINS_BASE_URL = "https://stablecoins.llama.fi"


class DefiLlamaClient(BaseDataSource):
    def __init__(self, cache=None, base_url: str = "https://api.llama.fi", **kwargs):
        super().__init__(name="defillama", base_url=base_url, cache=cache, **kwargs)

    def get_protocols(self) -> list:
        return self.fetch_json("/protocols", cache_key="defillama:protocols", ttl_seconds=3600) or []

    def build_gecko_id_index(self) -> dict:
        """CoinGecko coin id -> DefiLlama protocol 매핑. gecko_id 필드로 정확히 매칭한다."""
        index = {}
        for protocol in self.get_protocols():
            gecko_id = protocol.get("gecko_id")
            if gecko_id:
                index[gecko_id] = protocol
        return index

    def get_protocol_tvl_history(self, slug: str) -> list:
        cache_key = f"defillama:protocol:{slug}"
        data = self.fetch_json(f"/protocol/{slug}", cache_key=cache_key, ttl_seconds=3600)
        return (data or {}).get("tvl", [])

    def get_tvl_at_or_before(self, slug: str, target_epoch_seconds: int) -> Optional[float]:
        history = self.get_protocol_tvl_history(slug)
        candidates = [point for point in history if point.get("date", 0) <= target_epoch_seconds]
        if not candidates:
            return None
        closest = max(candidates, key=lambda point: point["date"])
        return closest.get("totalLiquidityUSD")

    def get_protocol_fees_summary(self, slug: str) -> dict:
        cache_key = f"defillama:fees:{slug}"
        return self.fetch_json(f"/summary/fees/{slug}", cache_key=cache_key, ttl_seconds=3600) or {}

    def get_fees_series(self, slug: str) -> list:
        """일별 fees 시계열. summary/fees 응답에 포함된 totalDataChart([timestamp, value])를 사용."""
        summary = self.get_protocol_fees_summary(slug)
        chart = summary.get("totalDataChart") or []
        return [{"date": int(point[0]), "value": point[1]} for point in chart if len(point) == 2]

    def get_fees_at_or_before(self, slug: str, target_epoch_seconds: int) -> Optional[float]:
        series = self.get_fees_series(slug)
        candidates = [point for point in series if point["date"] <= target_epoch_seconds]
        if not candidates:
            return None
        return max(candidates, key=lambda point: point["date"])["value"]

    def get_chains(self) -> list:
        return self.fetch_json("/v2/chains", cache_key="defillama:chains", ttl_seconds=3600) or []

    def build_chain_gecko_index(self) -> dict:
        """CoinGecko coin id -> DefiLlama 체인 매핑. L1 네이티브 코인의 체인 지표 조회에 사용."""
        index = {}
        for chain in self.get_chains():
            gecko_id = chain.get("gecko_id")
            if gecko_id:
                index[gecko_id] = chain
        return index

    def get_stablecoins_market_caps(self) -> list:
        """스테이블코인 발행량(체인별 유입 프록시). Stage 2 스코어링에서 활용 예정."""
        return self.fetch_json(
            f"{STABLECOINS_BASE_URL}/stablecoins", params={"includePrices": "false"},
            cache_key="defillama:stablecoins", ttl_seconds=3600,
        ) or []

    def get_chain_stablecoin_chart(self, chain_name: str) -> list:
        """체인별 스테이블코인 총 유통량 시계열 (거래소 순유입 프록시 아닌, 체인 유입 프록시)."""
        cache_key = f"defillama:stablecoinchart:{chain_name}"
        data = self.fetch_json(
            f"{STABLECOINS_BASE_URL}/stablecoincharts/{chain_name}", cache_key=cache_key, ttl_seconds=3600
        )
        series = []
        for point in data or []:
            pegged = ((point.get("totalCirculating") or {}).get("peggedUSD"))
            if pegged is None:
                continue
            series.append({"date": int(point.get("date", 0)), "value": pegged})
        return series

    def get_chain_stablecoin_mcap_at_or_before(self, chain_name: str, target_epoch_seconds: int) -> Optional[float]:
        series = self.get_chain_stablecoin_chart(chain_name)
        candidates = [point for point in series if point["date"] <= target_epoch_seconds]
        if not candidates:
            return None
        return max(candidates, key=lambda point: point["date"])["value"]
