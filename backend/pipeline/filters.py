import logging
import re

logger = logging.getLogger(__name__)


def is_stablecoin(coin: dict, filters_cfg: dict) -> bool:
    symbol = (coin.get("symbol") or "").lower()
    if symbol in {s.lower() for s in filters_cfg.get("stablecoin_symbols", [])}:
        return True
    categories = {(c or "").lower() for c in (coin.get("categories") or [])}
    stable_categories = {c.lower() for c in filters_cfg.get("stablecoin_categories", [])}
    return bool(categories & stable_categories)


def is_wrapped_token(coin: dict, filters_cfg: dict) -> bool:
    name = (coin.get("name") or "").lower()
    categories = {(c or "").lower() for c in (coin.get("categories") or [])}
    wrapped_categories = {c.lower() for c in filters_cfg.get("wrapped_categories", [])}
    if categories & wrapped_categories:
        return True
    for pattern in filters_cfg.get("wrapped_token_patterns", []):
        if re.search(pattern, name):
            return True
    return False


def is_suspected_scam(coin: dict, filters_cfg: dict) -> bool:
    scam_cfg = filters_cfg.get("scam_heuristics", {})
    market_cap = coin.get("market_cap") or 0
    volume = coin.get("total_volume") or 0

    if scam_cfg.get("require_positive_supply", True):
        supply = coin.get("circulating_supply")
        if supply is None or supply <= 0:
            return True

    if volume <= 0 and market_cap > 0:
        return True

    max_ratio = scam_cfg.get("max_mcap_to_volume_ratio")
    if max_ratio and volume > 0 and market_cap > 0 and (market_cap / volume) > max_ratio:
        return True

    return False


def passes_min_volume(coin: dict, filters_cfg: dict) -> bool:
    min_volume = filters_cfg.get("min_daily_volume_usd", 0)
    return (coin.get("total_volume") or 0) >= min_volume


def apply_filters(coins: list, filters_cfg: dict) -> tuple:
    """필터를 통과한 코인과, 거부된 코인+사유 목록을 함께 반환한다."""
    kept, rejected = [], []
    for coin in coins:
        reasons = []
        if filters_cfg.get("exclude_stablecoins", True) and is_stablecoin(coin, filters_cfg):
            reasons.append("stablecoin")
        if filters_cfg.get("exclude_wrapped_tokens", True) and is_wrapped_token(coin, filters_cfg):
            reasons.append("wrapped_token")
        if filters_cfg.get("exclude_suspected_scams", True) and is_suspected_scam(coin, filters_cfg):
            reasons.append("suspected_scam")
        if not passes_min_volume(coin, filters_cfg):
            reasons.append("low_volume")

        if reasons:
            rejected.append({"id": coin.get("id"), "reasons": reasons})
        else:
            kept.append(coin)

    logger.info("filters: kept %d / %d coins (%d rejected)", len(kept), len(coins), len(rejected))
    return kept, rejected
