import asyncio
import logging
from typing import Optional

from datasources.base import DataSourceError

from .base import AnalysisContext, AnalyzerResult, BaseAnalyzer, growth_from_snapshot_baseline, pct_change

logger = logging.getLogger(__name__)


class TechnicalAnalyzer(BaseAnalyzer):
    """RSI(14), 200일 MA 괴리율, 30/90일 수익률, 90일 고점 대비 위치.

    주의: 이 Analyzer의 출력은 점수 산정에 쓰이지 않는다. 용도는 두 가지뿐이다 —
    (a) Stage3 과열 필터의 입력값, (b) 상세 페이지 "참고 정보" 표시.
    """

    name = "technical"

    async def analyze(self, context: AnalysisContext) -> AnalyzerResult:
        return await asyncio.to_thread(self._analyze_sync, context)

    def _analyze_sync(self, context: AnalysisContext) -> AnalyzerResult:
        snapshot = context.snapshot
        returns = growth_from_snapshot_baseline(snapshot, "price_usd")
        metrics = {
            "return_30d_pct": returns["change_30d_pct"],
            "return_90d_pct": returns["change_90d_pct"],
            "rsi_14": None,
            "ma_200d_deviation_pct": None,
            "high_90d_position_pct": None,
        }
        evidence = [{"type": "price_baseline", "current_price_usd": snapshot.get("price_usd")}]
        notes = []

        coingecko = context.client("coingecko")
        if coingecko is None:
            notes.append("rsi_14/ma_200d_deviation_pct/high_90d_position_pct: coingecko 비활성화로 결측")
            return self._result(context.coin_id, metrics, evidence, {"status": "partial", "notes": notes})

        try:
            chart = coingecko.get_market_chart(context.coin_id, days=200)
            prices = [point[1] for point in (chart.get("prices") or [])]
        except DataSourceError as exc:
            logger.warning("technical: market_chart failed for %s: %s", context.coin_id, exc)
            notes.append("rsi_14/ma_200d_deviation_pct/high_90d_position_pct: coingecko 호출 실패로 결측")
            return self._result(context.coin_id, metrics, evidence, {"status": "partial", "notes": notes})

        current_price = snapshot.get("price_usd")

        rsi = _compute_rsi(prices)
        metrics["rsi_14"] = rsi
        if rsi is None:
            notes.append("rsi_14: 14일치 가격 데이터 부족")

        if len(prices) >= 200:
            ma_200 = sum(prices[-200:]) / 200
            metrics["ma_200d_deviation_pct"] = pct_change(current_price, ma_200)
        else:
            notes.append(f"ma_200d_deviation_pct: 200일치 데이터 부족 ({len(prices)}일 확보)")

        if prices:
            high_90d = max(prices[-90:])
            metrics["high_90d_position_pct"] = pct_change(current_price, high_90d)
            if len(prices) < 90:
                notes.append(f"high_90d_position_pct: 90일치 미만 데이터로 근사 ({len(prices)}일 확보)")

        evidence.append({"type": "market_chart", "days_available": len(prices), "source": "coingecko"})
        data_quality = {"status": "ok" if not notes else "partial", "notes": notes}
        return self._result(context.coin_id, metrics, evidence, data_quality)


def _compute_rsi(prices: list, period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)
