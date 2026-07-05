"""Stage 4 Reason Generator v2.

Top20 각 코인에 대해 LLM으로 구조화된 설명을 생성한다. 입력은 점수 분해(breakdown)와
근거 데이터(evidence)뿐이며, 3중 필터를 통과한 텍스트만 채택한다:
  a. 프롬프트에 "제공된 데이터에 없는 수치/사실 생성 금지" 명시
  b. 생성 후 응답 내 모든 수치가 입력 데이터에 존재하는지 자동 대조, 불일치 시 재생성(최대 2회)
  c. 금지 표현 필터 (직접 매수/매도 지시, "이미 N% 상승했으므로 추천" 류 후행적 근거)
실패한 필드는 추측 대신 null + 사유로 남긴다.
"""
import json
import logging
import re
from typing import Optional

from common.llm_client import LLMUnavailableError

logger = logging.getLogger(__name__)

CONTENT_FIELDS = [
    "leading_evidence_summary", "one_liner", "description_summary",
    "primary_use_case", "detailed_reasons", "risk_summary", "ai_summary",
]

SYSTEM_PROMPT = (
    "너는 암호화폐 리서치 애널리스트다. 사용자 메시지에 주어진 데이터(점수 분해, 온체인/개발자/"
    "사용자/밸류에이션/리스크 지표, VPD, 촉매, 가격 정보, CoinGecko 설명)만 근거로 코인 설명을 작성한다.\n\n"
    "절대 규칙:\n"
    "1. 제공된 데이터에 없는 수치나 사실을 만들어내지 마라. 모르면 해당 필드를 null로 응답하라.\n"
    "2. \"매수하세요\", \"매도하세요\", \"지금 사세요\" 같은 직접적인 투자 지시를 하지 마라. "
    "이 리포트는 정보 제공 목적이며 투자 추천이 아니다.\n"
    "3. \"이미 N% 상승했으므로 유망하다\"처럼 과거 가격 상승 자체를 추천 근거로 쓰지 마라. "
    "이 시스템의 핵심 원칙은 '가격이 아직 반영하지 않은 펀더멘털 성장'을 찾는 것이다.\n"
    "4. 모든 수치는 제공된 데이터의 값을 그대로 인용하라 (반올림 표기는 허용하되 새 수치를 계산해 만들지 마라).\n"
    "5. 출력은 지정된 JSON 스키마를 정확히 따르고, 다른 텍스트 없이 JSON 객체만 반환하라."
)

PLATFORM_DISPLAY_NAMES = {
    "ethereum": "Ethereum", "binance-smart-chain": "BNB Chain", "polygon-pos": "Polygon",
    "solana": "Solana", "avalanche": "Avalanche", "arbitrum-one": "Arbitrum",
    "optimistic-ethereum": "Optimism", "base": "Base", "tron": "Tron",
}


# ---------------------------------------------------------------------------
# 금지 표현 필터 (3중 필터의 c)
# ---------------------------------------------------------------------------

_DIRECTIVE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"매수\s*(하세요|하십시오|하라|를\s*추천)",
        r"매도\s*(하세요|하십시오|하라|를\s*추천)",
        r"사세요", r"파세요", r"팔아라",
        r"지금\s*(사|매수)", r"지금\s*(팔|매도)",
        r"buy now", r"sell now", r"you should buy", r"you should sell",
    ]
]
_RISE_VERB = re.compile(r"(상승|급등|올랐|올라서|치솟|폭등)")
_RECOMMEND_WORD = re.compile(r"(추천|매수|유망|사야|담아야|주목할|담기\s*좋)")
_PCT_PATTERN = re.compile(r"\d+(\.\d+)?\s*%")


def _has_retrospective_justification(sentence: str) -> bool:
    """v2 신규: "이미 N% 상승했으므로 추천" 류 후행적 근거 탐지 (P1 재발 방지)."""
    return bool(_PCT_PATTERN.search(sentence) and _RISE_VERB.search(sentence) and _RECOMMEND_WORD.search(sentence))


def find_banned_phrases(text: Optional[str]) -> list:
    if not text:
        return []
    violations = []
    for pattern in _DIRECTIVE_PATTERNS:
        if pattern.search(text):
            violations.append(f"직접 매수/매도 지시 표현 감지: 패턴 '{pattern.pattern}'")
    for sentence in re.split(r"[.!?。\n]", text):
        if _has_retrospective_justification(sentence):
            violations.append(f"후행적 근거(이미 상승했으므로 추천) 표현 감지: '{sentence.strip()}'")
    return violations


# ---------------------------------------------------------------------------
# 수치 대조 검증 (3중 필터의 b)
# ---------------------------------------------------------------------------

_NUMBER_PATTERN = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?")


def _flatten_numbers(obj, out: set) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(round(float(obj), 4))
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _flatten_numbers(v, out)


def build_allowed_numbers(context: dict) -> set:
    """LLM이 인용할 수 있는 모든 수치의 허용 집합. 여기 없는 수치가 텍스트에 등장하면 위반이다."""
    numbers = set()
    for key in ("vpd", "onchain", "developer", "user_ecosystem", "catalyst", "valuation", "risk",
                "technical", "confidence", "overheat", "catalysts_detail"):
        _flatten_numbers(context.get(key), numbers)
    for key in ("rank", "final_score", "base_score", "price_usd", "market_cap_usd", "launch_year"):
        value = context.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numbers.add(round(float(value), 4))
    # 반올림/정수화 표기 변형도 허용한다 (예: 72.98점 -> "73점"은 새 수치 생성이 아니라 반올림)
    for n in list(numbers):
        numbers.add(round(n))
        numbers.add(round(n, 1))
    return numbers


def extract_numbers(text: Optional[str]) -> list:
    if not text:
        return []
    numbers = []
    for match in _NUMBER_PATTERN.finditer(text):
        try:
            numbers.append(float(match.group().replace(",", "")))
        except ValueError:
            continue
    return numbers


def _is_number_allowed(value: float, allowed: set) -> bool:
    if not allowed:
        return False
    for candidate in allowed:
        tolerance = max(0.5, abs(candidate) * 0.05)
        if abs(value - candidate) <= tolerance:
            return True
    return False


def find_unverified_numbers(text: Optional[str], allowed_numbers: set) -> list:
    return [n for n in extract_numbers(text) if not _is_number_allowed(n, allowed_numbers)]


def validate_text(text: Optional[str], allowed_numbers: set) -> list:
    """텍스트 하나를 금지표현 + 수치대조 두 필터로 검증해 위반 사유 목록을 반환한다."""
    violations = find_banned_phrases(text)
    unverified = find_unverified_numbers(text, allowed_numbers)
    if unverified:
        violations.append(f"입력 데이터에 없는 수치 인용: {unverified}")
    return violations


def _field_texts(raw: dict, field_name: str) -> list:
    value = raw.get(field_name)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


# ---------------------------------------------------------------------------
# 코인 개요 파생 필드 — LLM 없이 코드로 계산 (환각 위험 자체가 없음)
# ---------------------------------------------------------------------------

def is_native_chain_coin(coin_analyzers: dict) -> bool:
    """DefiLlama 체인 매칭에 성공한 코인(=자체 메인넷을 가진 L1)인지. Stage2 OnChainGrowthAnalyzer
    결과를 재사용해 추가 API 호출 없이 판별한다."""
    stablecoin = (coin_analyzers.get("onchain_growth", {}).get("metrics", {}) or {}).get("stablecoin_inflow")
    return isinstance(stablecoin, dict) and "current" in stablecoin


def derive_chain_label(snapshot: dict, coin_analyzers: dict) -> Optional[str]:
    platform_id = snapshot.get("asset_platform_id")
    if platform_id:
        return PLATFORM_DISPLAY_NAMES.get(platform_id, platform_id.replace("-", " ").title())
    if is_native_chain_coin(coin_analyzers):
        return f"{snapshot.get('name')} 자체 메인넷"
    return None


def derive_launch_year(genesis_date: Optional[str]) -> Optional[int]:
    if not genesis_date or len(genesis_date) < 4:
        return None
    try:
        return int(genesis_date[:4])
    except ValueError:
        return None


def build_catalyst_calendar(coin_analyzers: dict) -> dict:
    """CatalystAnalyzer 원자료를 그대로 노출한다 (LLM이 재작성하지 않아 환각 위험이 없음)."""
    catalyst_metrics = coin_analyzers.get("catalyst", {}).get("metrics", {}) or {}
    return {
        "catalysts": catalyst_metrics.get("catalysts"),  # None=LLM(Stage2) 미가용, []=실제로 없음
        "token_unlock_schedule": None,
        "token_unlock_note": "무료 언락 일정 API 미연동으로 결측 (Stage2 RiskAnalyzer와 동일 사유)",
    }


# ---------------------------------------------------------------------------
# 프롬프트 빌더
# ---------------------------------------------------------------------------

def build_llm_context(ranked_coin: dict, snapshot: dict, coin_analyzers: dict, rank_position: int) -> dict:
    """LLM 프롬프트 재료. 이 dict에 없는 사실/수치가 출력에 등장하면 검증에서 걸러진다."""
    breakdown = ranked_coin["breakdown"]
    genesis_date = snapshot.get("genesis_date")
    context = ranked_coin.get("context", {}) or {}
    return {
        "coin_id": ranked_coin["coin_id"], "symbol": ranked_coin["symbol"], "name": ranked_coin["name"],
        "rank": rank_position,
        "final_score": ranked_coin["final_score"], "base_score": ranked_coin["base_score"],
        "confidence": ranked_coin["confidence"],
        "vpd": breakdown["vpd"],
        "onchain": breakdown["onchain_growth"],
        "developer": breakdown["developer"],
        "user_ecosystem": breakdown["user_ecosystem"],
        "catalyst": breakdown["catalyst"],
        "valuation": breakdown["valuation"],
        "risk": breakdown["risk"],
        "technical": ranked_coin.get("technical", {}) or {},
        "overheat": ranked_coin.get("overheat", {}) or {},
        "price_usd": context.get("price_usd"),
        "market_cap_usd": context.get("market_cap_usd"),
        "categories": snapshot.get("categories") or [],
        "description_en": snapshot.get("description_en"),
        "genesis_date": genesis_date,
        "launch_year": derive_launch_year(genesis_date),
        "chain": derive_chain_label(snapshot, coin_analyzers),
        "catalysts_detail": (coin_analyzers.get("catalyst", {}).get("metrics", {}) or {}).get("catalysts") or [],
    }


def _fmt_pct(value) -> str:
    return f"{value}%" if value is not None else "데이터 없음"


def build_user_prompt(context: dict) -> str:
    catalysts_json = (
        json.dumps(context["catalysts_detail"], ensure_ascii=False) if context["catalysts_detail"] else "없음"
    )
    return f"""다음은 {context['name']}({str(context['symbol']).upper()}) 코인의 유니버스 내 순위 {context['rank']}위 데이터다.
이 데이터에 없는 수치나 사실은 절대 만들어내지 마라.

[점수]
- 총점 {context['final_score']}점 (기본 {context['base_score']}점, 과열필터 감점 {context['overheat'].get('penalty', 0)}점)
- Confidence(신뢰도) {context['confidence']['score']}점 (커버리지 {context['confidence']['coverage']}, 신선도 {context['confidence']['freshness']}, 일관성 {context['confidence']['consistency']})

[VPD - 가치가격괴리]
- FG(펀더멘털 성장) {_fmt_pct(context['vpd'].get('fg_raw_pct'))}, PG(가격 변화) {_fmt_pct(context['vpd'].get('pg_raw_pct'))}
- 사분면: {context['vpd'].get('quadrant_label')}
- VPD 백분위: {context['vpd'].get('percentile')}

[카테고리별 점수와 근거]
- 온체인 성장 {context['onchain']['points']}점 (백분위 {context['onchain'].get('percentile')}): {context['onchain']['reason']}
- 개발자 활동 {context['developer']['points']}점: {context['developer']['reason']}
- 사용자/생태계 {context['user_ecosystem']['points']}점: {context['user_ecosystem']['reason']}
- 촉매 {context['catalyst']['points']}점: {context['catalyst']['reason']}
- 밸류에이션 {context['valuation']['points']}점: {context['valuation']['reason']}
- 리스크 {context['risk']['points']}점: {context['risk']['reason']}

[참고 - 점수에 반영되지 않는 기술적 지표]
RSI(14) {context['technical'].get('rsi_14')}, 200일MA 괴리율 {_fmt_pct(context['technical'].get('ma_200d_deviation_pct'))},
30일 수익률 {_fmt_pct(context['technical'].get('return_30d_pct'))}, 90일 수익률 {_fmt_pct(context['technical'].get('return_90d_pct'))}

[가격/시가총액]
현재가 {context['price_usd']}달러, 시가총액 {context['market_cap_usd']}달러

[코인 개요 원자료]
카테고리: {', '.join(context['categories']) if context['categories'] else '정보 없음'}
체인: {context['chain'] or '정보 없음'}
출시 연도: {context['launch_year'] or '정보 없음'}
CoinGecko 설명(영문 원문): {context['description_en'] or '정보 없음 — description_summary는 null로 응답할 것'}

[향후 촉매 원자료 (참고용 — 최종 산출물에는 이 데이터가 그대로 별도 노출되므로 재인용하지 않아도 됨)]
{catalysts_json}

다음 JSON 스키마로만, 다른 텍스트 없이 응답하라:
{{
  "leading_evidence_summary": "1~2문장. 왜 가격보다 가치가 먼저 오르고 있는지 수치를 인용해 설명",
  "one_liner": "코인 한 줄 소개",
  "description_summary": "CoinGecko 설명 원문을 3~4문장 한국어로 요약 (원문이 없으면 null)",
  "primary_use_case": "카테고리/설명에 근거한 주요 용도 한 문장",
  "detailed_reasons": ["점수 근거 수치를 인용한 이유 문장들의 배열 (2~4개)"],
  "risk_summary": "리스크 카테고리 근거를 바탕으로 한 리스크 요약 문장",
  "ai_summary": "3~4문장 총평. 투자 지시나 후행적(이미 올랐으므로) 근거는 절대 쓰지 말 것"
}}
"""


# ---------------------------------------------------------------------------
# 메인 생성 함수
# ---------------------------------------------------------------------------

def generate_coin_explanation(context: dict, llm_client, max_content_retries: int = 2) -> dict:
    """3중 필터를 통과한 필드만 채택한다. 통과하지 못한 필드는 null + 사유로 남는다.

    반환: {"fields": {필드명: 값 또는 None}, "field_status": {필드명: {...}}, "attempts_used": int}
    """
    allowed_numbers = build_allowed_numbers(context)
    user_prompt = build_user_prompt(context)

    fields_to_generate = list(CONTENT_FIELDS)
    best_values = {f: None for f in CONTENT_FIELDS}
    best_status = {f: {"status": "missing", "reason": "llm_unavailable"} for f in CONTENT_FIELDS}

    # description_en이 없으면 애초에 description_summary를 LLM에 기대하지 않는다 (원본이 없으므로 결측이 정답)
    if not context.get("description_en"):
        fields_to_generate.remove("description_summary")
        best_status["description_summary"] = {"status": "not_applicable", "reason": "no_coingecko_description"}

    max_attempts = max_content_retries + 1  # 최초 1회 + 재생성 최대 max_content_retries회
    attempts_used = 0

    for attempt in range(1, max_attempts + 1):
        pending = [f for f in fields_to_generate if best_values[f] is None]
        if not pending:
            break
        attempts_used = attempt
        is_last_attempt = attempt == max_attempts

        try:
            raw = llm_client.generate_json(SYSTEM_PROMPT, user_prompt, max_tokens=2000)
        except LLMUnavailableError as exc:
            logger.warning("explain: llm unavailable for %s: %s", context.get("coin_id"), exc)
            for f in pending:
                best_status[f] = {"status": "missing", "reason": f"llm_unavailable: {exc}"}
            break

        for f in pending:
            texts = _field_texts(raw, f)
            if not texts:
                best_status[f] = {
                    "status": "failed_validation" if is_last_attempt else "pending",
                    "reason": "llm_returned_empty_field", "attempts": attempt,
                }
                continue
            violations = []
            for text in texts:
                violations.extend(validate_text(text, allowed_numbers))
            if violations:
                best_status[f] = {
                    "status": "failed_validation" if is_last_attempt else "pending",
                    "violations": violations, "attempts": attempt,
                }
                logger.warning("explain: %s field '%s' failed validation (attempt %d): %s",
                                context.get("coin_id"), f, attempt, violations)
                continue
            best_values[f] = raw.get(f)
            best_status[f] = {"status": "ok", "attempts": attempt}

    return {"fields": best_values, "field_status": best_status, "attempts_used": attempts_used}


def explain_top20(top20: list, analyzers_by_id: dict, snapshots_by_id: dict, llm_client,
                   max_content_retries: int = 2) -> dict:
    """Top20 각 코인의 설명을 생성한다. 반환: {coin_id: {fields, field_status, catalyst_calendar, overview_facts}}"""
    results = {}
    for idx, ranked_coin in enumerate(top20, start=1):
        coin_id = ranked_coin["coin_id"]
        coin_analyzers = analyzers_by_id.get(coin_id, {})
        snapshot = snapshots_by_id.get(coin_id, {})
        context = build_llm_context(ranked_coin, snapshot, coin_analyzers, rank_position=idx)

        explanation = generate_coin_explanation(context, llm_client, max_content_retries=max_content_retries)
        explanation["catalyst_calendar"] = build_catalyst_calendar(coin_analyzers)
        explanation["overview_facts"] = {
            "categories": context["categories"],
            "chain": context["chain"],
            "launch_year": context["launch_year"],
            "description_source": "CoinGecko" if context["description_en"] else None,
        }
        results[coin_id] = explanation
    return results
