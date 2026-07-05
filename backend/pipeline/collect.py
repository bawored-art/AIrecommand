import argparse
import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

from common.cache import FileCache
from common.config import load_config
from common.logging_config import setup_logging
from datasources.base import DataSourceError
from datasources.coingecko import CoinGeckoClient
from datasources.defillama import DefiLlamaClient
from datasources.github import GitHubClient
from datasources.rss import RSSClient
from pipeline.backfill import get_baseline
from pipeline.filters import apply_filters
from pipeline.models import CoinSnapshot

logger = logging.getLogger(__name__)


def _extract_github_owner_repo(coin_detail: dict) -> Optional[tuple]:
    repos = ((coin_detail or {}).get("links") or {}).get("repos_url") or {}
    github_urls = repos.get("github") or []
    if not github_urls or not github_urls[0]:
        return None
    parts = github_urls[0].rstrip("/").split("/")
    if len(parts) < 2:
        return None
    return parts[-2], parts[-1]


def _build_clients(config: dict, cache: FileCache) -> dict:
    sources_cfg = config["sources"]
    http_cfg = config["http"]
    common_kwargs = dict(
        timeout=http_cfg["timeout_seconds"],
        max_retries=http_cfg["max_retries"],
        backoff_factor=http_cfg["backoff_factor"],
        retry_on_status=http_cfg["retry_on_status"],
    )

    clients = {"coingecko": None, "defillama": None, "github": None, "rss": None}

    if sources_cfg["coingecko"]["enabled"]:
        clients["coingecko"] = CoinGeckoClient(
            cache=cache, api_key=os.getenv("COINGECKO_API_KEY"),
            base_url=sources_cfg["coingecko"]["base_url"], **common_kwargs,
        )
    if sources_cfg["defillama"]["enabled"]:
        clients["defillama"] = DefiLlamaClient(
            cache=cache, base_url=sources_cfg["defillama"]["base_url"], **common_kwargs
        )
    if sources_cfg["github"]["enabled"]:
        # GitHub은 stats 엔드포인트가 202를 반환할 수 있어 클라이언트 자체 기본 재시도 상태코드를 사용한다.
        github_kwargs = {k: v for k, v in common_kwargs.items() if k != "retry_on_status"}
        clients["github"] = GitHubClient(
            cache=cache, token=os.getenv("GITHUB_TOKEN"),
            base_url=sources_cfg["github"]["base_url"], **github_kwargs,
        )
    if sources_cfg["rss"]["enabled"]:
        clients["rss"] = RSSClient(cache=cache, feeds=sources_cfg["rss"]["feeds"], **common_kwargs)

    return clients


def _enrich_with_defillama(snapshot: CoinSnapshot, defillama, protocol: Optional[dict], data_flags: dict) -> Optional[str]:
    if protocol is None:
        data_flags["defillama"] = "no_match"
        data_flags["defillama_fees"] = "no_match"
        return None

    snapshot.tvl_usd = protocol.get("tvl")
    data_flags["defillama"] = "ok"
    slug = protocol.get("slug")

    try:
        fees_summary = defillama.get_protocol_fees_summary(slug)
        snapshot.fees_24h_usd = fees_summary.get("total24h")
        data_flags["defillama_fees"] = "ok" if snapshot.fees_24h_usd is not None else "no_data"
    except DataSourceError as exc:
        logger.info("collect: defillama fees unavailable for %s: %s", slug, exc)
        data_flags["defillama_fees"] = "unavailable"

    return slug


def _enrich_with_github(snapshot: CoinSnapshot, coin_detail: dict, github, coin_id: str, data_flags: dict) -> None:
    if github is None:
        data_flags["github"] = "disabled"
        return
    try:
        owner_repo = _extract_github_owner_repo(coin_detail)
        if not owner_repo:
            data_flags["github"] = "no_repo"
            return
        owner, repo = owner_repo
        snapshot.github_owner_repo = f"{owner}/{repo}"
        repo_info = github.get_repo(owner, repo)
        snapshot.github_stars = repo_info.get("stargazers_count")
        commit_counts = github.get_commit_counts(owner, repo)
        snapshot.commits_30d = commit_counts.get("commits_30d")
        snapshot.commits_90d = commit_counts.get("commits_90d")
        data_flags["github"] = "ok"
    except DataSourceError as exc:
        logger.warning("collect: github enrichment failed for %s: %s", coin_id, exc)
        data_flags["github"] = "fetch_failed"


def _save_outputs(config: dict, today: date, snapshots: list, rejected: list, headlines: list) -> None:
    raw_dir = Path(config["history"]["raw_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": today.isoformat(),
        "count": len(snapshots),
        "coins": [s.to_dict() for s in snapshots],
        "rejected_count": len(rejected),
    }
    (raw_dir / f"{today.isoformat()}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    latest_path = Path(config["history"]["latest_output"])
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_payload = dict(payload)
    latest_payload["headlines"] = headlines
    latest_payload["rejected"] = rejected
    latest_path.write_text(json.dumps(latest_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run(config_path: str = "config.yaml", run_date: Optional[date] = None) -> list:
    config = load_config(config_path)
    setup_logging(config["logging"]["dir"], config["logging"]["level"], config["logging"]["retention_days"])
    today = run_date or date.today()

    cache = FileCache(config["cache"]["dir"], config["cache"]["default_ttl_seconds"])
    clients = _build_clients(config, cache)
    coingecko, defillama, github, rss = (
        clients["coingecko"], clients["defillama"], clients["github"], clients["rss"]
    )

    raw_coins = []
    if coingecko is not None:
        universe_cfg = config["universe"]
        try:
            raw_coins = coingecko.get_top_coins(
                vs_currency=universe_cfg["vs_currency"],
                per_page=universe_cfg["per_page"],
                max_pages=universe_cfg["max_pages"],
                top_n=universe_cfg["top_n"],
            )
        except DataSourceError as exc:
            logger.error("collect: coingecko top coins fetch failed entirely: %s", exc)
    else:
        logger.error("collect: coingecko source disabled — no universe available")

    logger.info("collect: fetched %d raw coins from coingecko", len(raw_coins))

    filtered_coins, rejected = apply_filters(raw_coins, config["filters"])

    gecko_index = {}
    if defillama is not None:
        try:
            gecko_index = defillama.build_gecko_id_index()
        except DataSourceError as exc:
            logger.warning("collect: defillama protocols fetch failed, TVL enrichment skipped: %s", exc)

    raw_dir = config["history"]["raw_dir"]
    lookback_days = config["history"]["lookback_days"]

    snapshots = []
    for coin in filtered_coins:
        coin_id = coin["id"]
        snapshot = CoinSnapshot(
            id=coin_id,
            symbol=coin.get("symbol"),
            name=coin.get("name"),
            price_usd=coin.get("current_price"),
            market_cap_usd=coin.get("market_cap"),
            volume_24h_usd=coin.get("total_volume"),
            circulating_supply=coin.get("circulating_supply"),
            fdv_usd=coin.get("fully_diluted_valuation"),
        )
        data_flags: dict = {}

        coin_detail = {}
        if coingecko is not None:
            try:
                coin_detail = coingecko.get_coin_detail(coin_id)
            except DataSourceError as exc:
                logger.warning("collect: coingecko detail fetch failed for %s: %s", coin_id, exc)
        snapshot.categories = coin_detail.get("categories") or []
        snapshot.description_en = (coin_detail.get("description") or {}).get("en") or None
        snapshot.genesis_date = coin_detail.get("genesis_date")
        snapshot.asset_platform_id = coin_detail.get("asset_platform_id")

        defillama_slug = None
        if defillama is not None:
            defillama_slug = _enrich_with_defillama(snapshot, defillama, gecko_index.get(coin_id), data_flags)
        else:
            data_flags["defillama"] = "disabled"

        _enrich_with_github(snapshot, coin_detail, github, coin_id, data_flags)

        for days_ago in lookback_days:
            baseline = get_baseline(
                coin_id, today, days_ago, raw_dir,
                coingecko_client=coingecko, defillama_client=defillama, defillama_slug=defillama_slug,
            )
            if days_ago == 30:
                snapshot.baseline_30d = baseline
            elif days_ago == 90:
                snapshot.baseline_90d = baseline
            data_flags[f"baseline_{days_ago}d"] = baseline["source"]

        snapshot.data_flags = data_flags
        snapshots.append(snapshot)

    headlines = []
    if rss is not None:
        try:
            headlines = rss.get_headlines()
        except DataSourceError as exc:
            logger.warning("collect: rss fetch failed: %s", exc)

    _save_outputs(config, today, snapshots, rejected, headlines)
    logger.info("collect: run complete for %s — %d coins saved", today.isoformat(), len(snapshots))
    return snapshots


def main() -> None:
    parser = argparse.ArgumentParser(description="Top300 알트코인 수집 파이프라인")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    run(config_path=args.config)


if __name__ == "__main__":
    main()
