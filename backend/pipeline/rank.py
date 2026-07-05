import argparse
import json
import logging
from datetime import date
from pathlib import Path

from common.config import load_config
from common.logging_config import setup_logging
from pipeline import scoring

logger = logging.getLogger(__name__)

# (extractor, higher_is_better) — vpd와 valuation은 별도 로직이라 여기 포함하지 않는다.
CATEGORY_EXTRACTORS = {
    "onchain_growth": (scoring.extract_onchain_composite, True),
    "developer": (scoring.extract_developer_composite, True),
    "user_ecosystem": (scoring.extract_user_composite, True),
    "catalyst": (scoring.extract_catalyst_composite, True),
    "risk": (scoring.extract_risk_composite, False),
}


def _fmt_pct(value) -> str:
    return f"{value:+.1f}%" if value is not None else "N/A"


def _round_or_none(value, digits=2):
    return round(value, digits) if value is not None else None


def _onchain_reason(analyzers: dict) -> str:
    metrics = analyzers.get("onchain_growth", {}).get("metrics", {}) or {}
    tvl = metrics.get("tvl_growth") or {}
    stablecoin = metrics.get("stablecoin_inflow") or {}
    parts = [f"TVL 30일 {_fmt_pct(tvl.get('change_30d_pct'))}"]
    sc_30 = stablecoin.get("change_30d_pct")
    if sc_30 is not None:
        parts.append(f"스테이블코인 유입 30일 {_fmt_pct(sc_30)}")
    return ", ".join(parts)


def _developer_reason(analyzers: dict) -> str:
    metrics = analyzers.get("developer", {}).get("metrics", {}) or {}
    pace = metrics.get("commit_pace_ratio")
    if pace is None:
        return "GitHub 데이터 없음"
    trend = "가속" if pace > 1 else "둔화" if pace < 1 else "유지"
    return f"커밋 페이스(30일/90일 평균 대비) {pace:.2f}배 ({trend}), 릴리즈 30일 {metrics.get('releases_30d')}건"


def _user_reason(analyzers: dict) -> str:
    metrics = analyzers.get("user_ecosystem", {}).get("metrics", {}) or {}
    fees = metrics.get("fees_growth") or {}
    change = fees.get("change_30d_pct")
    return f"프로토콜 수수료 30일 {_fmt_pct(change)}" if change is not None else "수수료 데이터 없음"


def _catalyst_reason(analyzers: dict) -> str:
    metrics = analyzers.get("catalyst", {}).get("metrics", {}) or {}
    catalysts = metrics.get("catalysts")
    if catalysts is None:
        return "LLM 미가용으로 촉매 분석 결측"
    if not catalysts:
        return "향후 촉매 없음"
    types = ", ".join(c.get("catalyst_type", "") for c in catalysts[:3])
    return f"향후 촉매 {len(catalysts)}건 ({types})"


def _valuation_reason(analyzers: dict, missing: bool) -> str:
    if missing:
        return "섹터 동료 표본 부족으로 밸류에이션 백분위 결측"
    metrics = analyzers.get("valuation", {}).get("metrics", {}) or {}
    return (
        f"MC/TVL 백분위 {metrics.get('mc_to_tvl_percentile')}, "
        f"MC/Fees 백분위 {metrics.get('mc_to_fees_percentile')} (높을수록 저평가)"
    )


def _risk_reason(analyzers: dict) -> str:
    metrics = analyzers.get("risk", {}).get("metrics", {}) or {}
    flags = metrics.get("risk_flags") or []
    if not flags:
        return "감지된 리스크 플래그 없음"
    return "; ".join(f"{f.get('type')}({f.get('severity')}): {f.get('reason')}" for f in flags[:3])


def _vpd_reason(fg_raw, pg_raw, quadrant: str, missing: bool) -> str:
    if missing:
        return "FG 또는 PG 계산 불가로 VPD 결측"
    return f"FG(펀더멘털 성장) {_fmt_pct(fg_raw)}, PG(가격 변화) {_fmt_pct(pg_raw)} → {scoring.QUADRANT_LABELS_KO[quadrant]}"


_REASON_BUILDERS = {
    "onchain_growth": _onchain_reason,
    "developer": _developer_reason,
    "user_ecosystem": _user_reason,
    "catalyst": _catalyst_reason,
    "risk": _risk_reason,
}


def _score_category(name: str, raw_value, population: list, weight: float, neutral_ratio: float,
                     higher_is_better: bool, analyzers: dict) -> dict:
    percentile = scoring.percentile_of(raw_value, population, higher_is_better=higher_is_better)
    missing = percentile is None
    points = (weight * neutral_ratio) if missing else (weight * percentile / 100)
    return {
        "weight": weight, "points": round(points, 2),
        "raw_value": _round_or_none(raw_value), "percentile": percentile,
        "missing": missing, "reason": _REASON_BUILDERS[name](analyzers),
    }


def score_universe(coins: list, config: dict) -> list:
    """coins: analysis.json의 coins 리스트. 각 항목은 {coin_id, symbol, name, analyzers}."""
    scoring_cfg = config["scoring"]
    weights = scoring_cfg["weights"]
    fg_weights = scoring_cfg["fg_weights"]
    neutral_ratio = scoring_cfg.get("neutral_score_ratio", 0.5)
    confidence_weights = (config.get("confidence") or {}).get("weights", {})
    overheat_cfg = config["overheat_filter"]

    coin_ids = [c["coin_id"] for c in coins]
    analyzers_by_id = {c["coin_id"]: c["analyzers"] for c in coins}

    fg_raw = {cid: scoring.compute_fg(analyzers_by_id[cid], fg_weights) for cid in coin_ids}
    pg_raw = {cid: scoring.compute_pg(analyzers_by_id[cid]) for cid in coin_ids}
    fg_z = scoring.zscore_population(fg_raw)
    pg_z = scoring.zscore_population(pg_raw)
    vpd_raw = {
        cid: (fg_z[cid] - pg_z[cid]) if fg_z[cid] is not None and pg_z[cid] is not None else None
        for cid in coin_ids
    }
    vpd_population = list(vpd_raw.values())

    category_raw = {
        name: {cid: extractor(analyzers_by_id[cid]) for cid in coin_ids}
        for name, (extractor, _hib) in CATEGORY_EXTRACTORS.items()
    }
    category_population = {name: list(values.values()) for name, values in category_raw.items()}
    valuation_pct = {cid: scoring.extract_valuation_percentile(analyzers_by_id[cid]) for cid in coin_ids}

    results = []
    for coin in coins:
        cid = coin["coin_id"]
        analyzers = analyzers_by_id[cid]
        breakdown = {}
        missing_flags = {}

        vpd_percentile = scoring.percentile_of(vpd_raw[cid], vpd_population, higher_is_better=True)
        quadrant = scoring.classify_vpd_quadrant(fg_z[cid], pg_z[cid])
        vpd_missing = vpd_percentile is None
        vpd_points = (weights["vpd"] * neutral_ratio) if vpd_missing else (weights["vpd"] * vpd_percentile / 100)
        breakdown["vpd"] = {
            "weight": weights["vpd"], "points": round(vpd_points, 2),
            "fg_raw_pct": _round_or_none(fg_raw[cid]), "fg_z": _round_or_none(fg_z[cid]),
            "pg_raw_pct": _round_or_none(pg_raw[cid]), "pg_z": _round_or_none(pg_z[cid]),
            "vpd": _round_or_none(vpd_raw[cid]), "percentile": vpd_percentile,
            "quadrant": quadrant, "quadrant_label": scoring.QUADRANT_LABELS_KO[quadrant],
            "missing": vpd_missing,
            "reason": _vpd_reason(fg_raw[cid], pg_raw[cid], quadrant, vpd_missing),
        }
        missing_flags["vpd"] = vpd_missing

        for name, (_extractor, higher_is_better) in CATEGORY_EXTRACTORS.items():
            breakdown[name] = _score_category(
                name, category_raw[name][cid], category_population[name], weights[name],
                neutral_ratio, higher_is_better, analyzers,
            )
            missing_flags[name] = breakdown[name]["missing"]

        val_pct = valuation_pct[cid]
        val_missing = val_pct is None
        val_points = (weights["valuation"] * neutral_ratio) if val_missing else (weights["valuation"] * val_pct / 100)
        breakdown["valuation"] = {
            "weight": weights["valuation"], "points": round(val_points, 2),
            "sector_percentile": val_pct, "missing": val_missing,
            "reason": _valuation_reason(analyzers, val_missing),
        }
        missing_flags["valuation"] = val_missing

        base_score = round(sum(cat["points"] for cat in breakdown.values()), 2)
        confidence = scoring.compute_confidence(analyzers, missing_flags, confidence_weights)

        results.append({
            "coin_id": cid, "symbol": coin.get("symbol"), "name": coin.get("name"),
            "base_score": base_score,
            "breakdown": breakdown,
            "overheat_strict": scoring.evaluate_overheat(analyzers, overheat_cfg, relaxed=False),
            "overheat_relaxed": scoring.evaluate_overheat(analyzers, overheat_cfg, relaxed=True),
            "confidence": confidence,
            "technical": scoring.extract_technical_metrics(analyzers),
            "context": scoring.extract_price_context(analyzers),
        })
    return results


def _build_summary(base_score: float, final_score: float, breakdown: dict, overheat: dict) -> str:
    parts = []
    for name, cat in breakdown.items():
        label = scoring.CATEGORY_LABELS_KO.get(name, name)
        sign = "+" if cat["points"] >= 0 else ""
        parts.append(f"{label} {sign}{cat['points']:.1f}")
    penalty = overheat.get("penalty", 0.0)
    parts.append(f"과열필터 -{penalty:.1f}")
    return f"총점 {final_score:.1f} (기본 {base_score:.1f}) = " + " + ".join(parts)


def _finalize(item: dict, overheat_key: str, relaxed: bool) -> dict:
    overheat = item[overheat_key]
    final_score = round(max(0.0, item["base_score"] - overheat["penalty"]), 2)
    return {
        "coin_id": item["coin_id"], "symbol": item["symbol"], "name": item["name"],
        "base_score": item["base_score"], "final_score": final_score,
        "breakdown": item["breakdown"],
        "overheat": overheat, "overheat_relaxed_mode": relaxed,
        "confidence": item["confidence"], "technical": item["technical"], "context": item["context"],
        "summary": _build_summary(item["base_score"], final_score, item["breakdown"], overheat),
    }


def _build_candidates(scored: list, relaxed: bool):
    overheat_key = "overheat_relaxed" if relaxed else "overheat_strict"
    candidates, momentum_leaders = [], []
    for item in scored:
        finalized = _finalize(item, overheat_key, relaxed)
        if finalized["overheat"]["excluded"]:
            momentum_leaders.append(finalized)
        else:
            candidates.append(finalized)
    return candidates, momentum_leaders


def apply_overheat_and_rank(scored: list, config: dict) -> dict:
    top_n = config["ranking"]["top_n"]

    candidates, momentum_leaders = _build_candidates(scored, relaxed=False)
    relaxed_mode = False
    if len(candidates) < top_n:
        relaxed_mode = True
        candidates, momentum_leaders = _build_candidates(scored, relaxed=True)
        logger.warning(
            "rank: 과열 제외 후 후보(%d)가 top_n(%d) 미만이라 완화 모드로 재랭킹합니다.",
            len(candidates), top_n,
        )

    candidates.sort(key=lambda x: x["final_score"], reverse=True)
    momentum_leaders.sort(key=lambda x: x["base_score"], reverse=True)

    return {
        "top20": candidates[:top_n],
        "momentum_leaders": momentum_leaders,
        "relaxed_mode": relaxed_mode,
        "candidate_count": len(candidates),
    }


def _save_outputs(config: dict, today: date, payload: dict) -> None:
    ranking_cfg = config["ranking"]
    out_dir = Path(ranking_cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{today.isoformat()}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    latest_path = Path(ranking_cfg["latest_output"])
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run(config_path: str = "config.yaml", analysis_path: str = None) -> dict:
    config = load_config(config_path)
    setup_logging(config["logging"]["dir"], config["logging"]["level"], config["logging"]["retention_days"])

    input_path = Path(analysis_path or config["analysis"]["latest_output"])
    if not input_path.exists():
        raise FileNotFoundError(
            f"Stage2 분석 산출물을 찾을 수 없습니다: {input_path} — 먼저 `python -m pipeline.analyze`를 실행하세요."
        )
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    coins = payload.get("coins", [])
    if not coins:
        raise ValueError("분석 대상 코인이 없습니다 — 먼저 pipeline.analyze를 실행하세요.")

    scored = score_universe(coins, config)
    ranking = apply_overheat_and_rank(scored, config)

    today = date.today()
    output = {
        "date": today.isoformat(),
        "universe_count": len(coins),
        "top_n": config["ranking"]["top_n"],
        "relaxed_mode": ranking["relaxed_mode"],
        "candidate_count": ranking["candidate_count"],
        "momentum_leader_count": len(ranking["momentum_leaders"]),
        "top20": ranking["top20"],
        "momentum_leaders": ranking["momentum_leaders"],
    }
    _save_outputs(config, today, output)
    logger.info(
        "rank: 완료 (universe=%d, top20=%d, momentum_leaders=%d, relaxed=%s)",
        len(coins), len(ranking["top20"]), len(ranking["momentum_leaders"]), ranking["relaxed_mode"],
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Top20 랭킹 산출 (VPD·과열필터·Confidence 포함)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--input", default=None, help="Stage2 analysis.json 경로 (기본: config의 analysis.latest_output)")
    args = parser.parse_args()
    run(config_path=args.config, analysis_path=args.input)


if __name__ == "__main__":
    main()
