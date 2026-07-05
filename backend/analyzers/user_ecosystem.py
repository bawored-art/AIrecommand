import asyncio
import logging

from datasources.base import DataSourceError

from .base import AnalysisContext, AnalyzerResult, BaseAnalyzer, epoch_seconds, pct_change

logger = logging.getLogger(__name__)


class UserEcosystemAnalyzer(BaseAnalyzer):
    """DefiLlama 프로토콜 fees의 30·90일 성장률. DAU는 무료 소스로 커버되지 않아 결측 처리한다."""

    name = "user_ecosystem"

    async def analyze(self, context: AnalysisContext) -> AnalyzerResult:
        return await asyncio.to_thread(self._analyze_sync, context)

    def _analyze_sync(self, context: AnalysisContext) -> AnalyzerResult:
        fees_growth, evidence, fees_status = self._fees_growth(context)
        metrics = {
            "dau_trend": None,
            "fees_growth": fees_growth,
        }
        data_quality = {
            "status": fees_status,
            "notes": ["dau_trend: DAU를 제공하는 무료 API 미연동으로 항상 결측"],
        }
        return self._result(context.coin_id, metrics, evidence, data_quality)

    def _fees_growth(self, context: AnalysisContext):
        defillama = context.client("defillama")
        if defillama is None:
            return ({"status": "unavailable", "reason": "defillama_disabled"}, [], "unavailable")

        try:
            gecko_index = defillama.build_gecko_id_index()
        except DataSourceError as exc:
            logger.warning("user_ecosystem: protocol index unavailable: %s", exc)
            return ({"status": "unavailable", "reason": "defillama_fetch_failed"}, [], "unavailable")

        protocol = gecko_index.get(context.coin_id)
        if protocol is None:
            return ({"status": "not_applicable", "reason": "no_matching_defillama_protocol"}, [], "partial")

        slug = protocol.get("slug")
        try:
            current = defillama.get_fees_at_or_before(slug, epoch_seconds(context.now))
            value_30d = defillama.get_fees_at_or_before(slug, epoch_seconds(context.now, 30))
            value_90d = defillama.get_fees_at_or_before(slug, epoch_seconds(context.now, 90))
        except DataSourceError as exc:
            logger.warning("user_ecosystem: fees series failed for %s: %s", slug, exc)
            return ({"status": "unavailable", "reason": "defillama_fees_fetch_failed"}, [], "unavailable")

        if current is None:
            return ({"status": "no_data", "reason": "protocol_has_no_fees_tracking"}, [], "partial")

        growth = {
            "current": current,
            "value_30d_ago": value_30d,
            "value_90d_ago": value_90d,
            "change_30d_pct": pct_change(current, value_30d),
            "change_90d_pct": pct_change(current, value_90d),
        }
        evidence = [{"type": "fees_series", "slug": slug, "source": "defillama"}]
        return (growth, evidence, "ok")
