import asyncio
import logging

from common.llm_client import LLMUnavailableError

from .base import AnalysisContext, AnalyzerResult, BaseAnalyzer

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "너는 암호화폐 뉴스에서 향후 촉매(catalyst) 이벤트를 추출하는 애널리스트다. "
    "추측하지 말고 기사 텍스트에 명시된 내용만 근거로 분류하라. 확실하지 않으면 null을 사용하라."
)

SCHEMA_HINT = (
    "각 헤드라인에 대해 다음 JSON 객체를 정확히 하나씩, 입력과 같은 순서의 배열로 반환하라:\n"
    '{"catalyst_type": "mainnet_upgrade|tokenomics_change|partnership|listing|other|none", '
    '"event_date": "YYYY-MM-DD 또는 null (기사에 명시된 경우만)", '
    '"confidence": 0.0~1.0, "summary": "한 문장 요약"}\n'
    "촉매로 볼 수 없으면 catalyst_type을 \"none\"으로 하라. 다른 텍스트 없이 JSON 배열만 출력하라."
)


class CatalystAnalyzer(BaseAnalyzer):
    """뉴스 헤드라인에서 향후 촉매(메인넷/업그레이드/토큰이코노미/파트너십/상장)를 추출한다.

    분류는 LLM 배치 호출로 수행한다. LLM을 쓸 수 없으면 헤드라인 원문만 evidence로 남기고
    metrics는 null 처리한다 (추측 금지, 날짜·출처 없는 촉매는 만들어내지 않는다).
    """

    name = "catalyst"

    async def analyze(self, context: AnalysisContext) -> AnalyzerResult:
        return await asyncio.to_thread(self._analyze_sync, context)

    def _analyze_sync(self, context: AnalysisContext) -> AnalyzerResult:
        headlines = context.headlines
        evidence = [_headline_evidence(h) for h in headlines]

        if not headlines:
            return self._result(
                context.coin_id,
                metrics={"catalysts": [], "catalyst_count": 0},
                evidence=evidence,
                data_quality={"status": "ok", "notes": ["이 코인을 언급하는 헤드라인이 없어 촉매 0건으로 판단"]},
            )

        llm = context.client("llm")
        if llm is None:
            return self._unavailable_with_evidence(context.coin_id, evidence, "llm_client_not_configured")

        items = [{"title": h.get("title"), "published": h.get("published")} for h in headlines]
        try:
            classifications = llm.classify_batch(SYSTEM_PROMPT, items, SCHEMA_HINT)
        except LLMUnavailableError as exc:
            logger.warning("catalyst: llm unavailable for %s: %s", context.coin_id, exc)
            return self._unavailable_with_evidence(context.coin_id, evidence, f"llm_error: {exc}")

        if classifications is None:
            return self._unavailable_with_evidence(context.coin_id, evidence, "llm_response_length_mismatch")

        catalysts = []
        for headline, classification in zip(headlines, classifications):
            catalyst_type = classification.get("catalyst_type")
            if catalyst_type in (None, "none"):
                continue
            catalysts.append({
                "catalyst_type": catalyst_type,
                "event_date": classification.get("event_date"),
                "confidence": classification.get("confidence"),
                "summary": classification.get("summary"),
                "source": headline.get("source"),
                "url": headline.get("link"),
                "published": headline.get("published"),
            })

        metrics = {"catalysts": catalysts, "catalyst_count": len(catalysts)}
        data_quality = {"status": "ok", "notes": ["헤드라인 제목만 분석 대상이며 기사 본문은 포함하지 않음"]}
        return self._result(context.coin_id, metrics, evidence, data_quality)

    def _unavailable_with_evidence(self, coin_id: str, evidence: list, reason: str) -> AnalyzerResult:
        return AnalyzerResult(
            analyzer=self.name, coin_id=coin_id,
            metrics={"catalysts": None, "catalyst_count": None},
            evidence=evidence,
            data_quality={"status": "unavailable", "reason": reason},
        )


def _headline_evidence(headline: dict) -> dict:
    return {
        "type": "headline",
        "title": headline.get("title"),
        "source": headline.get("source"),
        "link": headline.get("link"),
        "published": headline.get("published"),
    }
