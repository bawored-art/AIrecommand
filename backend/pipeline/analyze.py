import argparse
import asyncio
import concurrent.futures
import json
import logging
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from analyzers.base import AnalysisContext, AnalyzerResult
from analyzers.catalyst import CatalystAnalyzer
from analyzers.developer import DeveloperAnalyzer
from analyzers.news import NewsAnalyzer
from analyzers.onchain_growth import OnChainGrowthAnalyzer
from analyzers.risk import RiskAnalyzer
from analyzers.technical import TechnicalAnalyzer
from analyzers.user_ecosystem import UserEcosystemAnalyzer
from analyzers.valuation import ValuationAnalyzer
from common.cache import FileCache
from common.config import load_config
from common.llm_client import build_llm_client
from common.logging_config import setup_logging
from datasources.coingecko import CoinGeckoClient
from datasources.defillama import DefiLlamaClient
from datasources.github import GitHubClient

logger = logging.getLogger(__name__)

ANALYZER_CLASSES = [
    OnChainGrowthAnalyzer, UserEcosystemAnalyzer, DeveloperAnalyzer, CatalystAnalyzer,
    ValuationAnalyzer, NewsAnalyzer, TechnicalAnalyzer, RiskAnalyzer,
]


def _headline_mentions_coin(title, symbol, name) -> bool:
    if not title:
        return False
    title_lower = title.lower()
    if symbol and re.search(rf"\b{re.escape(symbol.lower())}\b", title_lower):
        return True
    if name and len(name) > 2 and name.lower() in title_lower:
        return True
    return False


def build_headline_index(coins: list, headlines: list) -> dict:
    """각 코인 id -> 그 코인을 언급하는 헤드라인 목록. 심볼/이름 단어 경계 매칭 사용."""
    index = {coin["id"]: [] for coin in coins}
    for headline in headlines:
        title = headline.get("title")
        for coin in coins:
            if _headline_mentions_coin(title, coin.get("symbol"), coin.get("name")):
                index[coin["id"]].append(headline)
    return index


def build_sector_peers_index(coins: list, max_peers: int = 60) -> dict:
    """카테고리를 하나라도 공유하는 코인들을 동료(peer)로 묶는다. ValuationAnalyzer의 백분위 계산에 사용."""
    category_map = {}
    for coin in coins:
        for category in coin.get("categories") or []:
            category_map.setdefault(category, []).append(coin)

    peers_by_id = {}
    for coin in coins:
        peer_set = {}
        for category in coin.get("categories") or []:
            for peer in category_map.get(category, []):
                if peer["id"] != coin["id"]:
                    peer_set[peer["id"]] = peer
        peers = sorted(peer_set.values(), key=lambda c: c.get("market_cap_usd") or 0, reverse=True)
        peers_by_id[coin["id"]] = peers[:max_peers]
    return peers_by_id


def _build_clients(config: dict, cache: FileCache) -> dict:
    sources_cfg = config["sources"]
    http_cfg = config["http"]
    common_kwargs = dict(
        timeout=http_cfg["timeout_seconds"], max_retries=http_cfg["max_retries"],
        backoff_factor=http_cfg["backoff_factor"], retry_on_status=http_cfg["retry_on_status"],
    )
    clients = {"coingecko": None, "defillama": None, "github": None, "llm": None}

    if sources_cfg["coingecko"]["enabled"]:
        clients["coingecko"] = CoinGeckoClient(
            cache=cache, api_key=os.getenv("COINGECKO_API_KEY"),
            base_url=sources_cfg["coingecko"]["base_url"], **common_kwargs,
        )
    if sources_cfg["defillama"]["enabled"]:
        clients["defillama"] = DefiLlamaClient(cache=cache, base_url=sources_cfg["defillama"]["base_url"], **common_kwargs)
    if sources_cfg["github"]["enabled"]:
        github_kwargs = {k: v for k, v in common_kwargs.items() if k != "retry_on_status"}
        clients["github"] = GitHubClient(
            cache=cache, token=os.getenv("GITHUB_TOKEN"),
            base_url=sources_cfg["github"]["base_url"], **github_kwargs,
        )
    clients["llm"] = build_llm_client(config)
    return clients


async def analyze_coin(coin: dict, sector_peers: list, headlines: list, clients: dict,
                        config: dict, now: datetime, semaphore: asyncio.Semaphore) -> dict:
    context = AnalysisContext(
        coin_id=coin["id"], symbol=coin.get("symbol"), name=coin.get("name"),
        snapshot=coin, sector_peers=sector_peers, headlines=headlines,
        clients=clients, config=config, now=now,
    )

    async def run_one(analyzer) -> AnalyzerResult:
        async with semaphore:
            try:
                return await analyzer.analyze(context)
            except Exception as exc:  # 개별 Analyzer 장애가 전체 배치를 중단시키지 않도록 격리
                logger.error("analyze: %s failed for %s: %s", analyzer.name, coin["id"], exc)
                return AnalyzerResult(
                    analyzer=analyzer.name, coin_id=coin["id"], metrics={}, evidence=[],
                    data_quality={"status": "error", "reason": str(exc)},
                )

    analyzers = [cls() for cls in ANALYZER_CLASSES]
    results = await asyncio.gather(*(run_one(a) for a in analyzers))
    return {
        "coin_id": coin["id"],
        "symbol": coin.get("symbol"),
        "name": coin.get("name"),
        "analyzers": {r.analyzer: r.to_dict() for r in results},
    }


async def _run_all(coins: list, headline_index: dict, peers_index: dict, clients: dict,
                    config: dict, now: datetime, max_concurrency: int) -> list:
    # asyncio.to_thread의 기본 executor는 CPU 코어 수 기준으로 작아 동시성이 병목될 수 있어 명시적으로 키운다.
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=max(32, max_concurrency)))

    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = [
        analyze_coin(coin, peers_index.get(coin["id"], []), headline_index.get(coin["id"], []),
                     clients, config, now, semaphore)
        for coin in coins
    ]
    return await asyncio.gather(*tasks)


def _save_outputs(config: dict, today: date, results: list, elapsed_seconds: float) -> None:
    analysis_cfg = config["analysis"]
    payload = {
        "date": today.isoformat(),
        "count": len(results),
        "elapsed_seconds": round(elapsed_seconds, 1),
        "coins": results,
    }

    out_dir = Path(analysis_cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{today.isoformat()}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    latest_path = Path(analysis_cfg["latest_output"])
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run(config_path: str = "config.yaml", top300_path: str = None, limit: int = None) -> list:
    config = load_config(config_path)
    setup_logging(config["logging"]["dir"], config["logging"]["level"], config["logging"]["retention_days"])

    input_path = Path(top300_path or config["history"]["latest_output"])
    if not input_path.exists():
        raise FileNotFoundError(
            f"Stage1 산출물을 찾을 수 없습니다: {input_path} — 먼저 `python -m pipeline.collect`를 실행하세요."
        )
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    coins = payload.get("coins", [])
    headlines = payload.get("headlines", [])
    if limit:
        coins = coins[:limit]

    cache = FileCache(config["cache"]["dir"], config["cache"]["default_ttl_seconds"])
    clients = _build_clients(config, cache)

    headline_index = build_headline_index(coins, headlines)
    peers_index = build_sector_peers_index(coins)

    now = datetime.now(timezone.utc)
    max_concurrency = (config.get("analysis") or {}).get("max_concurrency", 20)

    started_at = datetime.now(timezone.utc)
    results = asyncio.run(_run_all(coins, headline_index, peers_index, clients, config, now, max_concurrency))
    elapsed_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()

    logger.info("analyze: completed %d coins in %.1fs (max_concurrency=%d)", len(results), elapsed_seconds, max_concurrency)
    _save_outputs(config, date.today(), results, elapsed_seconds)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Top300 펀더멘털 Analyzer 배치 실행")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--input", default=None, help="Stage1 top300 JSON 경로 (기본: config의 history.latest_output)")
    parser.add_argument("--limit", type=int, default=None, help="테스트용: 상위 N개 코인만 분석")
    args = parser.parse_args()
    run(config_path=args.config, top300_path=args.input, limit=args.limit)


if __name__ == "__main__":
    main()
