import asyncio
import logging

from common.llm_client import LLMUnavailableError

from .base import AnalysisContext, AnalyzerResult, BaseAnalyzer

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "너는 암호화폐 뉴스 헤드라인의 감성과 영향도를 분류하는 애널리스트다. "
    "제목만으로 판단 가능한 범위에서만 분류하고, 확신이 없으면 sentiment는 neutral, impact는 낮게 설정하라."
)

SCHEMA_HINT = (
    "각 헤드라인에 대해 다음 JSON 객체를 정확히 하나씩, 입력과 같은 순서의 배열로 반환하라:\n"
    '{"sentiment": "positive|negative|neutral", "impact": 0.0~1.0}\n'
    "다른 텍스트 없이 JSON 배열만 출력하라."
)

_SENTIMENT_SIGN = {"positive": 1, "negative": -1, "neutral": 0}


class NewsAnalyzer(BaseAnalyzer):
    """뉴스 헤드라인 감성(긍정/부정/중립) + 영향도. LLM 배치 호출로 분류한다."""

    name = "news"

    async def analyze(self, context: AnalysisContext) -> AnalyzerResult:
        return await asyncio.to_thread(self._analyze_sync, context)

    def _analyze_sync(self, context: AnalysisContext) -> AnalyzerResult:
        headlines = context.headlines
        evidence = [
            {"type": "headline", "title": h.get("title"), "source": h.get("source"),
             "link": h.get("link"), "published": h.get("published")}
            for h in headlines
        ]

        if not headlines:
            return self._result(
                context.coin_id,
                metrics={"headlines_evaluated": 0, "positive_count": 0, "negative_count": 0,
                         "neutral_count": 0, "net_sentiment_score": None, "items": []},
                evidence=evidence,
                data_quality={"status": "ok", "notes": ["이 코인을 언급하는 헤드라인이 없음"]},
            )

        llm = context.client("llm")
        if llm is None:
            return self._unavailable(context.coin_id, "llm_client_not_configured")

        items = [{"title": h.get("title")} for h in headlines]
        try:
            classifications = llm.classify_batch(SYSTEM_PROMPT, items, SCHEMA_HINT)
        except LLMUnavailableError as exc:
            logger.warning("news: llm unavailable for %s: %s", context.coin_id, exc)
            return self._unavailable(context.coin_id, f"llm_error: {exc}")

        if classifications is None:
            return self._unavailable(context.coin_id, "llm_response_length_mismatch")

        results = []
        counts = {"positive": 0, "negative": 0, "neutral": 0}
        weighted_sum = 0.0
        for headline, classification in zip(headlines, classifications):
            sentiment = classification.get("sentiment", "neutral")
            impact = classification.get("impact") or 0.0
            counts[sentiment] = counts.get(sentiment, 0) + 1
            weighted_sum += _SENTIMENT_SIGN.get(sentiment, 0) * impact
            results.append({
                "title": headline.get("title"), "sentiment": sentiment, "impact": impact,
                "source": headline.get("source"), "url": headline.get("link"),
            })

        metrics = {
            "headlines_evaluated": len(headlines),
            "positive_count": counts["positive"],
            "negative_count": counts["negative"],
            "neutral_count": counts["neutral"],
            "net_sentiment_score": round(weighted_sum / len(headlines), 3),
            "items": results,
        }
        data_quality = {"status": "ok", "notes": ["헤드라인 제목만 분석 대상이며 기사 본문은 포함하지 않음"]}
        return self._result(context.coin_id, metrics, evidence, data_quality)
