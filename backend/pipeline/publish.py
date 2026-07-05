"""Stage 4 정적 JSON 생성기 — python -m pipeline.publish

Stage1(top300.json) + Stage2(analysis.json) + Stage3(ranking.json)를 조인하고
Reason Generator(explain.py)로 Top20 설명을 생성한 뒤, frontend/public/data/ 아래에
정적 JSON 파일 세트를 만든다.

모든 산출물은 메모리에서 먼저 전부 구성한 뒤 마지막에 한 번에 디스크에 쓴다 —
중간에 예외가 나면 기존 파일은 하나도 건드리지 않는다 (부분 갱신 금지).
"""
import argparse
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from common.cache import FileCache
from common.config import load_config
from common.llm_client import build_llm_client
from common.logging_config import setup_logging
from datasources.base import DataSourceError
from datasources.coingecko import CoinGeckoClient
from datasources.feargreed import FearGreedClient
from pipeline import explain

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
_HISTORY_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(am|pm)\.json$")


# ---------------------------------------------------------------------------
# 입력 로딩
# ---------------------------------------------------------------------------

def _load_json(path_str: str, label: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"{label} 산출물을 찾을 수 없습니다: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_existing_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("publish: 이전 %s 읽기 실패, 신규 진입 비교 없이 진행합니다: %s", path, exc)
        return None


def _build_market_clients(config: dict, cache: FileCache) -> dict:
    sources_cfg = config["sources"]
    http_cfg = config["http"]
    common_kwargs = dict(
        timeout=http_cfg["timeout_seconds"], max_retries=http_cfg["max_retries"],
        backoff_factor=http_cfg["backoff_factor"], retry_on_status=http_cfg["retry_on_status"],
    )
    clients = {"coingecko": None, "feargreed": None}
    if sources_cfg["coingecko"]["enabled"]:
        clients["coingecko"] = CoinGeckoClient(
            cache=cache, api_key=os.getenv("COINGECKO_API_KEY"),
            base_url=sources_cfg["coingecko"]["base_url"], **common_kwargs,
        )
    feargreed_cfg = sources_cfg.get("feargreed", {"enabled": True, "base_url": "https://api.alternative.me"})
    if feargreed_cfg.get("enabled", True):
        clients["feargreed"] = FearGreedClient(cache=cache, base_url=feargreed_cfg["base_url"], **common_kwargs)
    return clients


def _collect_market_data(clients: dict) -> dict:
    data = {}
    coingecko = clients.get("coingecko")
    if coingecko is not None:
        try:
            data.update(coingecko.get_global_market_data())
        except DataSourceError as exc:
            logger.warning("publish: coingecko global 데이터 조회 실패: %s", exc)

    feargreed = clients.get("feargreed")
    if feargreed is not None:
        try:
            data["fear_greed"] = feargreed.get_latest() or None
        except DataSourceError as exc:
            logger.warning("publish: fear&greed 조회 실패: %s", exc)
    return data


# ---------------------------------------------------------------------------
# 전 회차 대비 신규진입(NEW)/이탈/순위 변동
# ---------------------------------------------------------------------------

def compute_rank_changes(current_top20: list, previous_recommendations: Optional[dict]) -> dict:
    """coin_id -> {"badge": "NEW"|None, "previous_rank": int|None, "rank_change": int|None}"""
    previous_items = (previous_recommendations or {}).get("items", [])
    previous_rank_by_id = {item["coin_id"]: item["rank"] for item in previous_items}

    changes = {}
    for idx, coin in enumerate(current_top20, start=1):
        coin_id = coin["coin_id"]
        prev_rank = previous_rank_by_id.get(coin_id)
        if prev_rank is None:
            changes[coin_id] = {"badge": "NEW", "previous_rank": None, "rank_change": None}
        else:
            changes[coin_id] = {"badge": None, "previous_rank": prev_rank, "rank_change": prev_rank - idx}
    return changes


def compute_exited_coins(current_top20: list, previous_recommendations: Optional[dict]) -> list:
    previous_items = (previous_recommendations or {}).get("items", [])
    current_ids = {coin["coin_id"] for coin in current_top20}
    return [
        {"coin_id": item["coin_id"], "symbol": item.get("symbol"), "name": item.get("name"),
         "previous_rank": item["rank"]}
        for item in previous_items if item["coin_id"] not in current_ids
    ]


# ---------------------------------------------------------------------------
# 갱신 시각 계산 (KST)
# ---------------------------------------------------------------------------

def compute_next_update_kst(schedule_kst: list, now_kst: datetime) -> datetime:
    today = now_kst.date()
    candidates = []
    for time_str in schedule_kst:
        hour, minute = (int(part) for part in time_str.split(":"))
        candidates.append(datetime(today.year, today.month, today.day, hour, minute, tzinfo=KST))

    later_today = [c for c in candidates if c > now_kst]
    if later_today:
        return min(later_today)

    tomorrow = today + timedelta(days=1)
    hour, minute = (int(part) for part in schedule_kst[0].split(":"))
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, minute, tzinfo=KST)


def _history_slot_label(now_kst: datetime) -> str:
    return "am" if now_kst.hour < 12 else "pm"


def build_history_index(history_dir: Path) -> list:
    """정적 호스팅은 디렉터리 목록을 제공하지 않으므로, 프론트엔드가 어떤 회차 파일이
    있는지 알 수 있도록 파일명 목록을 별도 index.json으로 남긴다."""
    if not history_dir.exists():
        return []
    entries = []
    for path in sorted(history_dir.glob("*.json")):
        if _HISTORY_FILENAME_RE.match(path.name):
            entries.append(path.stem)  # 예: "2026-07-05-pm"
    return entries


def prune_old_history(history_dir: Path, today: date, retention_days: int) -> list:
    if not history_dir.exists():
        return []
    cutoff = today - timedelta(days=retention_days)
    removed = []
    for path in history_dir.glob("*.json"):
        match = _HISTORY_FILENAME_RE.match(path.name)
        if not match:
            continue
        file_date = date.fromisoformat(match.group(1))
        if file_date < cutoff:
            path.unlink()
            removed.append(path.name)
    return removed


# ---------------------------------------------------------------------------
# 출력 JSON 빌더
# ---------------------------------------------------------------------------

def _build_recommendations(ranking: dict, rank_changes: dict, exited: list,
                            explanations: dict, now_kst: datetime) -> dict:
    items = []
    for idx, coin in enumerate(ranking["top20"], start=1):
        coin_id = coin["coin_id"]
        change = rank_changes.get(coin_id, {})
        fields = explanations.get(coin_id, {}).get("fields", {})
        context = coin.get("context", {}) or {}
        vpd = (coin.get("breakdown") or {}).get("vpd", {}) or {}
        items.append({
            "rank": idx, "coin_id": coin_id, "symbol": coin["symbol"], "name": coin["name"],
            "final_score": coin["final_score"], "confidence_score": coin["confidence"]["score"],
            "leading_evidence_summary": fields.get("leading_evidence_summary"),
            "price_usd": context.get("price_usd"), "market_cap_usd": context.get("market_cap_usd"),
            # FG/PG를 회차마다 남겨두면 history/ 축적분으로 코인 상세의 FG vs PG 라인차트를 그릴 수 있다
            "fg_raw_pct": vpd.get("fg_raw_pct"), "pg_raw_pct": vpd.get("pg_raw_pct"),
            "badge": change.get("badge"), "previous_rank": change.get("previous_rank"),
            "rank_change": change.get("rank_change"),
        })
    return {
        "date": now_kst.date().isoformat(),
        "generated_at_kst": now_kst.isoformat(),
        "universe_count": ranking.get("universe_count"),
        "relaxed_mode": ranking.get("relaxed_mode"),
        "items": items,
        "exited_since_last_run": exited,
    }


def _build_metric_series(coin_analyzers: dict) -> dict:
    """온체인/사용자 지표의 90일전-30일전-현재 3점 시계열. 스파크라인용 (보간·추정 없이 실측값만)."""
    onchain = coin_analyzers.get("onchain_growth", {}).get("metrics", {}) or {}
    user = coin_analyzers.get("user_ecosystem", {}).get("metrics", {}) or {}

    def _series(growth_obj):
        if not isinstance(growth_obj, dict) or "current" not in growth_obj:
            return None
        return {"points": [
            {"label": "90일 전", "value": growth_obj.get("value_90d_ago")},
            {"label": "30일 전", "value": growth_obj.get("value_30d_ago")},
            {"label": "현재", "value": growth_obj.get("current")},
        ]}

    return {
        "tvl_usd": _series(onchain.get("tvl_growth")),
        "stablecoin_inflow_usd": _series(onchain.get("stablecoin_inflow")),
        "fees_24h_usd": _series(user.get("fees_growth")),
    }


def _build_coin_detail(idx: int, ranked_coin: dict, explanation: dict, rank_change: dict,
                        coin_analyzers: dict) -> dict:
    fields = explanation.get("fields", {})
    overview_facts = explanation.get("overview_facts", {})
    context = ranked_coin.get("context", {}) or {}
    return {
        "rank": idx, "coin_id": ranked_coin["coin_id"], "symbol": ranked_coin["symbol"], "name": ranked_coin["name"],
        "badge": rank_change.get("badge"), "previous_rank": rank_change.get("previous_rank"),
        "rank_change": rank_change.get("rank_change"),
        "overview": {
            "one_liner": fields.get("one_liner"),
            "description_summary": fields.get("description_summary"),
            "description_source": overview_facts.get("description_source"),
            "primary_use_case": fields.get("primary_use_case"),
            "categories": overview_facts.get("categories", []),
            "chain": overview_facts.get("chain"),
            "launch_year": overview_facts.get("launch_year"),
        },
        "score": {
            "final_score": ranked_coin["final_score"], "base_score": ranked_coin["base_score"],
            "breakdown": ranked_coin["breakdown"], "summary": ranked_coin.get("summary"),
        },
        "leading_evidence_summary": fields.get("leading_evidence_summary"),
        "detailed_reasons": fields.get("detailed_reasons"),
        "risk_summary": fields.get("risk_summary"),
        "upcoming_catalysts": explanation.get("catalyst_calendar"),
        "ai_summary": fields.get("ai_summary"),
        "confidence": ranked_coin["confidence"],
        "technical_reference": ranked_coin.get("technical"),
        "overheat": ranked_coin.get("overheat"),
        "price_usd": context.get("price_usd"), "market_cap_usd": context.get("market_cap_usd"),
        "field_status": explanation.get("field_status"),
        "metric_series": _build_metric_series(coin_analyzers),
    }


def _build_market_json(market_data: dict, now_kst: datetime) -> dict:
    return {
        "date": now_kst.date().isoformat(),
        "generated_at_kst": now_kst.isoformat(),
        "btc_dominance_pct": market_data.get("btc_dominance_pct"),
        "eth_dominance_pct": market_data.get("eth_dominance_pct"),
        "total_market_cap_usd": market_data.get("total_market_cap_usd"),
        "market_cap_change_24h_pct": market_data.get("market_cap_change_24h_pct"),
        "fear_greed": market_data.get("fear_greed"),
    }


def _build_momentum_leaders(ranking: dict, now_kst: datetime) -> dict:
    items = []
    for coin in ranking.get("momentum_leaders", []):
        technical = coin.get("technical", {}) or {}
        items.append({
            "coin_id": coin["coin_id"], "symbol": coin["symbol"], "name": coin["name"],
            "base_score": coin["base_score"],
            "excluded_reasons": (coin.get("overheat") or {}).get("reasons", []),
            "return_30d_pct": technical.get("return_30d_pct"), "return_90d_pct": technical.get("return_90d_pct"),
        })
    return {
        "date": now_kst.date().isoformat(), "generated_at_kst": now_kst.isoformat(),
        "count": len(items), "items": items,
    }


def _build_meta(config: dict, ranking: dict, explanations: dict, now_kst: datetime) -> dict:
    top20 = ranking.get("top20", [])
    ai_summary_ok = sum(1 for e in explanations.values() if e.get("fields", {}).get("ai_summary"))
    coverage = (ai_summary_ok / len(top20)) if top20 else 0.0
    return {
        "last_updated_kst": now_kst.isoformat(),
        "next_update_kst": compute_next_update_kst(config["app"]["schedule_kst"], now_kst).isoformat(),
        "status": "ok" if (not top20 or coverage >= 0.5) else "degraded",
        "universe_count": ranking.get("universe_count"),
        "top20_count": len(top20),
        "momentum_leader_count": len(ranking.get("momentum_leaders", [])),
        "relaxed_mode": ranking.get("relaxed_mode"),
        "llm_available": coverage > 0,
        "ai_summary_coverage": round(coverage, 3),
    }


def _write_all(output_dir: Path, files: dict) -> None:
    for relative_path, content in files.items():
        full_path = output_dir / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 오케스트레이션
# ---------------------------------------------------------------------------

def run(config_path: str = "config.yaml") -> dict:
    config = load_config(config_path)
    setup_logging(config["logging"]["dir"], config["logging"]["level"], config["logging"]["retention_days"])

    top300 = _load_json(config["history"]["latest_output"], "Stage1 top300")
    analysis = _load_json(config["analysis"]["latest_output"], "Stage2 analysis")
    ranking = _load_json(config["ranking"]["latest_output"], "Stage3 ranking")

    snapshots_by_id = {c["id"]: c for c in top300.get("coins", [])}
    analyzers_by_id = {c["coin_id"]: c["analyzers"] for c in analysis.get("coins", [])}

    cache = FileCache(config["cache"]["dir"], config["cache"]["default_ttl_seconds"])
    explain_cfg = config["explain"]
    llm_client = build_llm_client(config, max_calls_per_run=explain_cfg["max_llm_calls_per_run"])
    explanations = explain.explain_top20(
        ranking["top20"], analyzers_by_id, snapshots_by_id, llm_client,
        max_content_retries=explain_cfg["content_retry_count"],
    )

    market_clients = _build_market_clients(config, cache)
    market_data = _collect_market_data(market_clients)

    now_kst = datetime.now(KST)
    output_dir = Path(config["publish"]["output_dir"])
    previous_recommendations = _read_existing_json(output_dir / "recommendations.json")

    rank_changes = compute_rank_changes(ranking["top20"], previous_recommendations)
    exited = compute_exited_coins(ranking["top20"], previous_recommendations)

    files = {
        "recommendations.json": _build_recommendations(ranking, rank_changes, exited, explanations, now_kst),
        "market.json": _build_market_json(market_data, now_kst),
        "momentum-leaders.json": _build_momentum_leaders(ranking, now_kst),
    }
    for idx, ranked_coin in enumerate(ranking["top20"], start=1):
        coin_id = ranked_coin["coin_id"]
        files[f"coins/{coin_id}.json"] = _build_coin_detail(
            idx, ranked_coin, explanations.get(coin_id, {}), rank_changes.get(coin_id, {}),
            analyzers_by_id.get(coin_id, {}),
        )
    files["meta.json"] = _build_meta(config, ranking, explanations, now_kst)

    today = now_kst.date()
    slot = _history_slot_label(now_kst)
    files[f"history/{today.isoformat()}-{slot}.json"] = files["recommendations.json"]

    # 여기까지 예외 없이 도달한 경우에만 실제로 디스크에 쓴다 (부분 갱신 방지)
    _write_all(output_dir, files)
    removed = prune_old_history(output_dir / "history", today, config["publish"]["history_retention_days"])

    history_dir = output_dir / "history"
    (history_dir / "index.json").write_text(
        json.dumps({"entries": build_history_index(history_dir)}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(
        "publish: 완료 (%d개 파일 기록, history %d개 정리, llm_calls=%d)",
        len(files), len(removed), llm_client.calls_made,
    )
    return {"files_written": sorted(files.keys()), "history_removed": removed, "output_dir": str(output_dir)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Top20 정적 JSON 세트 생성 (frontend/public/data/)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    run(config_path=args.config)


if __name__ == "__main__":
    main()
