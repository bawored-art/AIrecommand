"""Stage 3 점수 모델 v2 — VPD, 카테고리별 백분위 점수, 과열 필터, Confidence Score.

순수 계산 함수만 담는다 (파일 I/O 없음). 오케스트레이션은 pipeline/rank.py가 담당한다.
"""
import statistics
from typing import Optional

CATEGORY_LABELS_KO = {
    "onchain_growth": "온체인",
    "vpd": "VPD",
    "developer": "개발자",
    "user_ecosystem": "사용자",
    "catalyst": "촉매",
    "valuation": "밸류에이션",
    "risk": "리스크",
}

QUADRANT_LABELS_KO = {
    "leading_opportunity": "선행 기회 (펀더멘털 개선, 가격 미반영)",
    "co_movement": "동반 상승 (펀더멘털·가격 함께 개선)",
    "pure_pump": "순수 펌핑 (가격만 상승, 펀더멘털 부진)",
    "stagnation": "침체 (펀더멘털·가격 모두 부진)",
    "unknown": "판단 불가 (FG 또는 PG 데이터 부족)",
}

_SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3, "unknown": 2}


# ---------------------------------------------------------------------------
# 공통 통계 유틸
# ---------------------------------------------------------------------------

def zscore_population(values: dict) -> dict:
    """{key: value} 중 value가 None이 아닌 항목만 z-score로 표준화한다.

    표본이 2개 미만이거나 표준편차가 0이면(변별력 없음) 해당 항목은 전부 0.0으로 처리한다.
    입력에 없던 key는 만들지 않고, None이었던 key는 결과에서도 None으로 유지한다.
    """
    clean = {k: v for k, v in values.items() if v is not None}
    result = {k: None for k in values}
    if len(clean) < 2:
        for k in clean:
            result[k] = 0.0
        return result
    mean = statistics.fmean(clean.values())
    stdev = statistics.pstdev(clean.values())
    if stdev == 0:
        for k in clean:
            result[k] = 0.0
        return result
    for k, v in clean.items():
        result[k] = (v - mean) / stdev
    return result


def percentile_of(value: Optional[float], population: list, higher_is_better: bool = True) -> Optional[float]:
    """population 내에서 value의 백분위(0~100, 높을수록 좋은 점수)를 계산한다.

    동점(tie)은 중간 순위(mid-rank)로 처리한다 — 예: 코인 대부분이 촉매/리스크 플래그 0개로
    묶여 있을 때, 단순 "이하 개수" 방식이면 그 다수가 부당하게 최상위 근처 백분위를 받게 된다.
    mid-rank는 동점 집단 전체를 자기 순위 구간의 중앙에 놓아 이런 왜곡을 막는다.

    higher_is_better=False면 값이 낮을수록 좋은 지표(예: 리스크)로 취급해 방향을 뒤집는다.
    population 안에 value 자신이 포함되어 있어도 무방하다 (자기 자신도 유니버스의 일원).
    """
    clean = [v for v in population if v is not None]
    if value is None or len(clean) < 2:
        return None
    if higher_is_better:
        strictly_better = sum(1 for v in clean if v < value)
    else:
        strictly_better = sum(1 for v in clean if v > value)
    tied = sum(1 for v in clean if v == value)
    rank = strictly_better + 0.5 * tied
    return round(rank / len(clean) * 100, 2)


def weighted_average(components: dict, weights: dict) -> Optional[float]:
    """components 중 None을 제외하고 남은 항목의 weights를 재정규화해 가중평균을 낸다."""
    available = {k: v for k, v in components.items() if v is not None and k in weights}
    if not available:
        return None
    weight_sum = sum(weights[k] for k in available)
    if weight_sum == 0:
        return None
    return sum(v * weights[k] for k, v in available.items()) / weight_sum


# ---------------------------------------------------------------------------
# FG / PG / VPD
# ---------------------------------------------------------------------------

def extract_fg_components(coin_analyzers: dict) -> dict:
    """VPD의 FG(Fundamental Growth) 산출용 30일 변화율 원자료를 추출한다."""
    onchain = coin_analyzers.get("onchain_growth", {}).get("metrics", {}) or {}
    user = coin_analyzers.get("user_ecosystem", {}).get("metrics", {}) or {}
    developer = coin_analyzers.get("developer", {}).get("metrics", {}) or {}

    tvl_growth = onchain.get("tvl_growth") or {}
    stablecoin = onchain.get("stablecoin_inflow") or {}
    fees_growth = user.get("fees_growth") or {}
    pace_ratio = developer.get("commit_pace_ratio")

    return {
        "onchain_tvl_growth": tvl_growth.get("change_30d_pct"),
        "onchain_stablecoin_inflow": stablecoin.get("change_30d_pct"),
        "user_fees_growth": fees_growth.get("change_30d_pct"),
        "developer_commit_accel": (pace_ratio - 1) * 100 if pace_ratio is not None else None,
    }


def compute_fg(coin_analyzers: dict, fg_weights: dict) -> Optional[float]:
    return weighted_average(extract_fg_components(coin_analyzers), fg_weights)


def compute_pg(coin_analyzers: dict) -> Optional[float]:
    """PG(Price Growth) = 동일 기간(30일) 가격 변화율. TechnicalAnalyzer의 산출값을 그대로 쓴다."""
    technical = coin_analyzers.get("technical", {}).get("metrics", {}) or {}
    return technical.get("return_30d_pct")


def classify_vpd_quadrant(fg_z: Optional[float], pg_z: Optional[float]) -> str:
    if fg_z is None or pg_z is None:
        return "unknown"
    fg_up, pg_up = fg_z > 0, pg_z > 0
    if fg_up and not pg_up:
        return "leading_opportunity"
    if fg_up and pg_up:
        return "co_movement"
    if not fg_up and pg_up:
        return "pure_pump"
    return "stagnation"


# ---------------------------------------------------------------------------
# 카테고리별 원자료 추출 (population 대비 백분위 계산의 입력)
# ---------------------------------------------------------------------------

def extract_onchain_composite(coin_analyzers: dict) -> Optional[float]:
    """OnChainGrowth의 30·90일 변화율 전부를 평균해 성장 신호를 만든다."""
    metrics = coin_analyzers.get("onchain_growth", {}).get("metrics", {}) or {}
    tvl = metrics.get("tvl_growth") or {}
    stablecoin = metrics.get("stablecoin_inflow") or {}
    values = [
        tvl.get("change_30d_pct"), tvl.get("change_90d_pct"),
        stablecoin.get("change_30d_pct"), stablecoin.get("change_90d_pct"),
    ]
    clean = [v for v in values if v is not None]
    return statistics.fmean(clean) if clean else None


def extract_user_composite(coin_analyzers: dict) -> Optional[float]:
    metrics = coin_analyzers.get("user_ecosystem", {}).get("metrics", {}) or {}
    fees = metrics.get("fees_growth") or {}
    values = [fees.get("change_30d_pct"), fees.get("change_90d_pct")]
    clean = [v for v in values if v is not None]
    return statistics.fmean(clean) if clean else None


def extract_developer_composite(coin_analyzers: dict) -> Optional[float]:
    """커밋 페이스 가속도와 릴리즈 페이스 가속도(30일 실측 vs 90일 평균 기대치)를 평균한다."""
    metrics = coin_analyzers.get("developer", {}).get("metrics", {}) or {}
    pace_ratio = metrics.get("commit_pace_ratio")
    releases_30d = metrics.get("releases_30d")
    releases_90d = metrics.get("releases_90d")

    signals = []
    if pace_ratio is not None:
        signals.append((pace_ratio - 1) * 100)
    if releases_30d is not None and releases_90d:
        expected_30d_rate = releases_90d / 3.0
        if expected_30d_rate > 0:
            signals.append((releases_30d / expected_30d_rate - 1) * 100)
    return statistics.fmean(signals) if signals else None


def extract_catalyst_composite(coin_analyzers: dict) -> Optional[float]:
    """향후 촉매의 신뢰도 가중 개수. LLM 미가용으로 catalysts가 None이면 결측."""
    metrics = coin_analyzers.get("catalyst", {}).get("metrics", {}) or {}
    catalysts = metrics.get("catalysts")
    if catalysts is None:
        return None
    return sum(c.get("confidence") if c.get("confidence") is not None else 0.5 for c in catalysts)


def extract_valuation_percentile(coin_analyzers: dict) -> Optional[float]:
    """ValuationAnalyzer가 이미 산출한 섹터 내 백분위(0~100, 높을수록 저평가)를 그대로 평균한다."""
    metrics = coin_analyzers.get("valuation", {}).get("metrics", {}) or {}
    values = [metrics.get("mc_to_tvl_percentile"), metrics.get("mc_to_fees_percentile")]
    clean = [v for v in values if v is not None]
    return statistics.fmean(clean) if clean else None


def extract_risk_composite(coin_analyzers: dict) -> Optional[float]:
    """risk_flags의 심각도 가중 합. 높을수록 위험함 (점수화 시 higher_is_better=False로 반전)."""
    metrics = coin_analyzers.get("risk", {}).get("metrics", {}) or {}
    flags = metrics.get("risk_flags")
    if flags is None:
        return None
    return float(sum(_SEVERITY_WEIGHT.get(f.get("severity"), 2) for f in flags))


def extract_technical_metrics(coin_analyzers: dict) -> dict:
    return coin_analyzers.get("technical", {}).get("metrics", {}) or {}


def extract_price_context(coin_analyzers: dict) -> dict:
    """상세페이지/랭킹 표시용 현재가·시가총액. Valuation/Technical의 evidence에서 그대로 가져온다."""
    price = None
    for item in coin_analyzers.get("technical", {}).get("evidence", []) or []:
        if item.get("type") == "price_baseline":
            price = item.get("current_price_usd")
    market_cap = None
    for item in coin_analyzers.get("valuation", {}).get("evidence", []) or []:
        if item.get("type") == "valuation_inputs":
            market_cap = item.get("market_cap_usd")
    return {"price_usd": price, "market_cap_usd": market_cap}


# ---------------------------------------------------------------------------
# 과열 필터 (Entry Feasibility Filter)
# ---------------------------------------------------------------------------

def evaluate_overheat(coin_analyzers: dict, cfg: dict, relaxed: bool = False) -> dict:
    """과열 필터 평가. Technical 지표가 결측이면 페널티를 주지 않는다 (데이터 없음을 불리하게 쓰지 않음).

    반환: {"excluded": bool, "penalty": float, "reasons": [str, ...]}
    """
    technical = extract_technical_metrics(coin_analyzers)
    return_30d = technical.get("return_30d_pct")
    return_90d = technical.get("return_90d_pct")
    rsi = technical.get("rsi_14")
    ma_dev = technical.get("ma_200d_deviation_pct")
    high90_pos = technical.get("high_90d_position_pct")

    exclude_cfg = cfg["exclude"]
    reasons = []
    penalty = 0.0

    if not relaxed:
        excluded = False
        if return_30d is not None and return_30d > exclude_cfg["return_30d_pct_gt"]:
            excluded = True
            reasons.append(f"30일 수익률 {return_30d:+.1f}% > {exclude_cfg['return_30d_pct_gt']}% (제외)")
        if return_90d is not None and return_90d > exclude_cfg["return_90d_pct_gt"]:
            excluded = True
            reasons.append(f"90일 수익률 {return_90d:+.1f}% > {exclude_cfg['return_90d_pct_gt']}% (제외)")
        if excluded:
            return {"excluded": True, "penalty": 0.0, "reasons": reasons}
    else:
        relaxed_cfg = cfg["relaxed_penalty"]
        if return_30d is not None and return_30d > exclude_cfg["return_30d_pct_gt"]:
            penalty += relaxed_cfg["return_30d_pct_gt_penalty"]
            reasons.append(
                f"30일 수익률 {return_30d:+.1f}% > {exclude_cfg['return_30d_pct_gt']}% "
                f"(완화 감점 -{relaxed_cfg['return_30d_pct_gt_penalty']})"
            )
        if return_90d is not None and return_90d > exclude_cfg["return_90d_pct_gt"]:
            penalty += relaxed_cfg["return_90d_pct_gt_penalty"]
            reasons.append(
                f"90일 수익률 {return_90d:+.1f}% > {exclude_cfg['return_90d_pct_gt']}% "
                f"(완화 감점 -{relaxed_cfg['return_90d_pct_gt_penalty']})"
            )

    penalty_cfg = cfg["penalty"]
    if rsi is not None and rsi > penalty_cfg["rsi_gt"]:
        penalty += penalty_cfg["rsi_penalty"]
        reasons.append(f"RSI(14) {rsi:.1f} > {penalty_cfg['rsi_gt']} (-{penalty_cfg['rsi_penalty']})")
    if ma_dev is not None and ma_dev > penalty_cfg["ma200_deviation_gt"]:
        penalty += penalty_cfg["ma200_penalty"]
        reasons.append(
            f"200일 MA 대비 {ma_dev:+.1f}% > {penalty_cfg['ma200_deviation_gt']}% (-{penalty_cfg['ma200_penalty']})"
        )
    if high90_pos is not None and high90_pos >= penalty_cfg["high90d_within_pct"]:
        penalty += penalty_cfg["high90d_penalty"]
        reasons.append(
            f"90일 고점 대비 {high90_pos:+.1f}% "
            f"({penalty_cfg['high90d_within_pct']}% 이내) (-{penalty_cfg['high90d_penalty']})"
        )

    return {"excluded": False, "penalty": penalty, "reasons": reasons}


# ---------------------------------------------------------------------------
# Confidence Score
# ---------------------------------------------------------------------------

_ANALYZER_NAMES = [
    "onchain_growth", "user_ecosystem", "developer", "catalyst",
    "valuation", "news", "technical", "risk",
]


def compute_confidence(coin_analyzers: dict, category_missing_flags: dict, weights: dict) -> dict:
    """데이터 커버리지 + 소스 신선도 + 소스 간 일관성을 합성한 0~100 신뢰도 점수.

    코인 자체에 대한 사실 주장이 아니라 "이 점수를 얼마나 신뢰할 수 있는가"를 나타내는
    엔지니어링 휴리스틱이다.
    """
    total_categories = len(category_missing_flags) or 1
    covered = sum(1 for missing in category_missing_flags.values() if not missing)
    coverage = covered / total_categories

    freshness_scores = []
    for name in _ANALYZER_NAMES:
        status = ((coin_analyzers.get(name, {}) or {}).get("data_quality", {}) or {}).get("status")
        if status == "ok":
            freshness_scores.append(1.0)
        elif status == "partial":
            freshness_scores.append(0.5)
        else:
            freshness_scores.append(0.0)
    freshness = statistics.fmean(freshness_scores) if freshness_scores else 0.0

    fg_components = extract_fg_components(coin_analyzers)
    signs = [1 if v > 0 else (-1 if v < 0 else 0) for v in fg_components.values() if v is not None]
    if len(signs) < 2:
        consistency = 0.5  # 비교할 신호가 2개 미만이면 합치도를 판단할 수 없어 중립 처리
    else:
        positive = sum(1 for s in signs if s >= 0)
        consistency = max(positive, len(signs) - positive) / len(signs)

    score = round(100 * (
        weights.get("coverage", 0.4) * coverage
        + weights.get("freshness", 0.3) * freshness
        + weights.get("consistency", 0.3) * consistency
    ), 1)
    return {
        "score": score,
        "coverage": round(coverage, 3),
        "freshness": round(freshness, 3),
        "consistency": round(consistency, 3),
    }
