import asyncio
from typing import Optional

from .base import AnalysisContext, AnalyzerResult, BaseAnalyzer, percentile_rank_cheapness


def _safe_ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


class ValuationAnalyzer(BaseAnalyzer):
    """MC/TVL, MC/Fees(연환산), FDV/MC — 동일 섹터(카테고리) 내 백분위로 상대 저평가를 측정한다.

    섹터 동료 표본이 부족하면 백분위는 결측 처리하고 원자료 비율만 제공한다 (추측 금지).
    """

    name = "valuation"

    async def analyze(self, context: AnalysisContext) -> AnalyzerResult:
        return await asyncio.to_thread(self._analyze_sync, context)

    def _analyze_sync(self, context: AnalysisContext) -> AnalyzerResult:
        snapshot = context.snapshot
        market_cap = snapshot.get("market_cap_usd")
        tvl = snapshot.get("tvl_usd")
        fees_24h = snapshot.get("fees_24h_usd")
        fdv = snapshot.get("fdv_usd")

        mc_to_tvl = _safe_ratio(market_cap, tvl)
        mc_to_fees = _safe_ratio(market_cap, fees_24h * 365 if fees_24h is not None else None)
        fdv_to_mc = _safe_ratio(fdv, market_cap)

        min_peers = (context.config.get("analysis") or {}).get("min_sector_peers", 5)
        peers = context.sector_peers
        has_enough_peers = len(peers) >= min_peers

        peer_mc_to_tvl, peer_mc_to_fees = [], []
        for peer in peers:
            peer_fees = peer.get("fees_24h_usd")
            peer_mc_to_tvl.append(_safe_ratio(peer.get("market_cap_usd"), peer.get("tvl_usd")))
            peer_mc_to_fees.append(
                _safe_ratio(peer.get("market_cap_usd"), peer_fees * 365 if peer_fees is not None else None)
            )

        def _pctile(value, peer_values):
            return percentile_rank_cheapness(value, peer_values) if has_enough_peers else None

        metrics = {
            "mc_to_tvl": mc_to_tvl,
            "mc_to_fees_annualized": mc_to_fees,
            "fdv_to_mc": fdv_to_mc,
            "sector_peer_count": len(peers),
            "mc_to_tvl_percentile": _pctile(mc_to_tvl, peer_mc_to_tvl),
            "mc_to_fees_percentile": _pctile(mc_to_fees, peer_mc_to_fees),
            "categories": snapshot.get("categories") or [],
        }
        evidence = [{
            "type": "valuation_inputs", "market_cap_usd": market_cap, "tvl_usd": tvl,
            "fees_24h_usd": fees_24h, "fdv_usd": fdv,
        }]

        notes = []
        if not has_enough_peers:
            notes.append(f"섹터 동료 표본 부족({len(peers)}/{min_peers})으로 백분위 결측")
        data_quality = {"status": "partial" if notes else "ok", "notes": notes}
        return self._result(context.coin_id, metrics, evidence, data_quality)
