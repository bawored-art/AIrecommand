import asyncio
import logging

from datasources.base import DataSourceError

from .base import AnalysisContext, AnalyzerResult, BaseAnalyzer, epoch_seconds, growth_from_snapshot_baseline, pct_change

logger = logging.getLogger(__name__)


class OnChainGrowthAnalyzer(BaseAnalyzer):
    """TVL/스테이블코인 유입의 30·90일 변화율. 활성주소·트랜잭션·신규홀더·거래소 순유출입은
    Stage1 데이터 소스(CoinGecko/DefiLlama/GitHub/RSS)로 커버되지 않아 항상 결측 처리한다."""

    name = "onchain_growth"

    async def analyze(self, context: AnalysisContext) -> AnalyzerResult:
        return await asyncio.to_thread(self._analyze_sync, context)

    def _analyze_sync(self, context: AnalysisContext) -> AnalyzerResult:
        snapshot = context.snapshot
        metrics = {
            "tvl_growth": growth_from_snapshot_baseline(snapshot, "tvl_usd"),
            "active_address_growth": None,
            "transaction_count_growth": None,
            "new_holder_growth": None,
            "exchange_net_flow": None,
            "stablecoin_inflow": self._stablecoin_inflow(context),
        }
        evidence = [{
            "type": "tvl_snapshot",
            "tvl_usd": snapshot.get("tvl_usd"),
            "source": "defillama",
            "defillama_match": (snapshot.get("data_flags") or {}).get("defillama"),
        }]
        data_quality = {
            "status": "partial",
            "notes": [
                "active_address_growth/transaction_count_growth/new_holder_growth/exchange_net_flow: "
                "무료 온체인 지표 API(Glassnode·Nansen 등) 미연동으로 항상 결측",
            ],
        }
        return self._result(context.coin_id, metrics, evidence, data_quality)

    def _stablecoin_inflow(self, context: AnalysisContext) -> dict:
        defillama = context.client("defillama")
        chain_index = {}
        if defillama is not None:
            try:
                # defillama 클라이언트의 FileCache(1시간 TTL)가 재사용되므로 코인마다 호출해도 네트워크 비용은 1회뿐
                chain_index = defillama.build_chain_gecko_index()
            except DataSourceError as exc:
                logger.warning("onchain_growth: chain index unavailable: %s", exc)

        chain = chain_index.get(context.coin_id)
        if chain is None:
            return {"status": "not_applicable", "reason": "coin_is_not_an_l1_chain"}
        if defillama is None:
            return {"status": "unavailable", "reason": "defillama_disabled"}

        try:
            chain_name = chain.get("name")
            current = defillama.get_chain_stablecoin_mcap_at_or_before(chain_name, epoch_seconds(context.now))
            value_30d = defillama.get_chain_stablecoin_mcap_at_or_before(chain_name, epoch_seconds(context.now, 30))
            value_90d = defillama.get_chain_stablecoin_mcap_at_or_before(chain_name, epoch_seconds(context.now, 90))
            return {
                "current": current,
                "value_30d_ago": value_30d,
                "value_90d_ago": value_90d,
                "change_30d_pct": pct_change(current, value_30d),
                "change_90d_pct": pct_change(current, value_90d),
            }
        except DataSourceError as exc:
            logger.warning("onchain_growth: stablecoin chart failed for %s: %s", context.coin_id, exc)
            return {"status": "unavailable", "reason": "defillama_fetch_failed"}
