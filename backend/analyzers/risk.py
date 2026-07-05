import asyncio
import logging
from typing import Optional

from common.llm_client import LLMUnavailableError

from .base import AnalysisContext, AnalyzerResult, BaseAnalyzer

logger = logging.getLogger(__name__)

RISK_KEYWORDS = ["hack", "exploit", "breach", "lawsuit", "sec ", "regulation", "regulatory", "ban", "sanction"]

SYSTEM_PROMPT = (
    "너는 암호화폐 리스크 애널리스트다. 주어진 헤드라인 중 해킹/보안사고/규제·소송 이슈에 해당하는 것만 "
    "구조화된 형태로 추출하라. 해당하지 않으면 risk_type을 \"none\"으로 하라. "
    "추측하지 말고 텍스트에 명시된 것만 사용하라."
)
SCHEMA_HINT = (
    "각 헤드라인에 대해 다음 JSON 객체를 정확히 하나씩, 입력과 같은 순서의 배열로 반환하라:\n"
    '{"risk_type": "hack|regulatory|lawsuit|none", "severity": "low|medium|high", "summary": "한 문장 요약"}\n'
    "다른 텍스트 없이 JSON 배열만 출력하라."
)


class RiskAnalyzer(BaseAnalyzer):
    """유동성(거래량/시총)은 직접 계산하고, 해킹 이력/규제 이슈는 뉴스 헤드라인에서 LLM으로 추출한다.

    Token Unlock 일정과 고래 집중도는 무료 소스로 커버되지 않아 결측 처리한다.
    모든 감점 요인은 risk_flags에 사유와 함께 기록한다.
    """

    name = "risk"

    async def analyze(self, context: AnalysisContext) -> AnalyzerResult:
        return await asyncio.to_thread(self._analyze_sync, context)

    def _analyze_sync(self, context: AnalysisContext) -> AnalyzerResult:
        snapshot = context.snapshot
        risk_flags = []

        liquidity_ratio = _safe_ratio(snapshot.get("volume_24h_usd"), snapshot.get("market_cap_usd"))
        if liquidity_ratio is not None and liquidity_ratio < 0.01:
            risk_flags.append({
                "type": "low_liquidity", "severity": "medium",
                "reason": f"24h 거래량/시총 비율이 {liquidity_ratio:.4f}로 낮음", "source": "coingecko",
            })

        evidence = [{
            "type": "liquidity_inputs",
            "volume_24h_usd": snapshot.get("volume_24h_usd"),
            "market_cap_usd": snapshot.get("market_cap_usd"),
        }]
        notes = [
            "token_unlock_schedule: 무료 언락 일정 API(TokenUnlocks 등) 미연동으로 결측",
            "whale_concentration: 온체인 홀더 분포 API 미연동으로 결측",
        ]

        candidate_headlines = [
            h for h in context.headlines
            if any(keyword in (h.get("title") or "").lower() for keyword in RISK_KEYWORDS)
        ]
        evidence.extend(_headline_evidence(h) for h in candidate_headlines)

        hack_history, regulatory_issues = self._extract_headline_risks(
            context, candidate_headlines, risk_flags, notes
        )

        metrics = {
            "liquidity_ratio": liquidity_ratio,
            "token_unlock_schedule": None,
            "whale_concentration": None,
            "hack_history": hack_history,
            "regulatory_issues": regulatory_issues,
            "risk_flags": risk_flags,
        }
        data_quality = {"status": "partial", "notes": notes}
        return self._result(context.coin_id, metrics, evidence, data_quality)

    def _extract_headline_risks(self, context: AnalysisContext, candidate_headlines: list,
                                 risk_flags: list, notes: list):
        if not candidate_headlines:
            notes.append("hack_history/regulatory_issues: 위험 키워드에 해당하는 헤드라인 없음 (0건으로 판단)")
            return [], []

        llm = context.client("llm")
        if llm is None:
            notes.append("hack_history/regulatory_issues: llm_client_not_configured로 결측")
            return None, None

        items = [{"title": h.get("title")} for h in candidate_headlines]
        try:
            classifications = llm.classify_batch(SYSTEM_PROMPT, items, SCHEMA_HINT)
        except LLMUnavailableError as exc:
            logger.warning("risk: llm unavailable for %s: %s", context.coin_id, exc)
            notes.append(f"hack_history/regulatory_issues: llm_error: {exc}")
            return None, None

        if classifications is None:
            notes.append("hack_history/regulatory_issues: llm_response_length_mismatch로 결측")
            return None, None

        hacks, regs = [], []
        for headline, classification in zip(candidate_headlines, classifications):
            risk_type = classification.get("risk_type")
            if risk_type in (None, "none"):
                continue
            entry = {
                "risk_type": risk_type,
                "severity": classification.get("severity"),
                "summary": classification.get("summary"),
                "source": headline.get("source"),
                "url": headline.get("link"),
                "published": headline.get("published"),
            }
            (hacks if risk_type == "hack" else regs).append(entry)
            risk_flags.append({
                "type": risk_type, "severity": classification.get("severity") or "unknown",
                "reason": classification.get("summary"), "source": headline.get("link"),
            })
        return hacks, regs


def _safe_ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _headline_evidence(headline: dict) -> dict:
    return {
        "type": "risk_candidate_headline", "title": headline.get("title"),
        "source": headline.get("source"), "link": headline.get("link"),
    }
