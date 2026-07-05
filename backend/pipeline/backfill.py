import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from datasources.base import DataSourceError

logger = logging.getLogger(__name__)


def _load_local_snapshot_index(raw_dir: str, target_date: date) -> Optional[dict]:
    path = Path(raw_dir) / f"{target_date.isoformat()}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("backfill: failed to read local snapshot %s: %s", path, exc)
        return None
    return {coin["id"]: coin for coin in payload.get("coins", [])}


def get_baseline(
    coin_id: str,
    today: date,
    days_ago: int,
    raw_dir: str,
    coingecko_client=None,
    defillama_client=None,
    defillama_slug: Optional[str] = None,
) -> dict:
    """coin_id의 days_ago일 전 기준값을 확보한다.

    1) 로컬에 그날 스냅샷이 이미 있으면 그 값을 사용한다.
    2) 없으면 (최초 실행 등) 과거 데이터 API로 소급 조회한다.
    3) 그마저 실패하면 값을 결측(None) 처리한다.
    """
    target_date = today - timedelta(days=days_ago)

    local_index = _load_local_snapshot_index(raw_dir, target_date)
    if local_index and coin_id in local_index:
        snap = local_index[coin_id]
        return {
            "price_usd": snap.get("price_usd"),
            "market_cap_usd": snap.get("market_cap_usd"),
            "volume_24h_usd": snap.get("volume_24h_usd"),
            "tvl_usd": snap.get("tvl_usd"),
            "source": "local_history",
            "as_of": target_date.isoformat(),
        }

    baseline = {
        "price_usd": None,
        "market_cap_usd": None,
        "volume_24h_usd": None,
        "tvl_usd": None,
        "source": "missing",
        "as_of": target_date.isoformat(),
    }

    if coingecko_client is not None:
        try:
            cg_date_str = target_date.strftime("%d-%m-%Y")
            cg_data = coingecko_client.get_historical_snapshot(coin_id, cg_date_str)
            for key, value in cg_data.items():
                if value is not None:
                    baseline[key] = value
                    baseline["source"] = "api_backfill"
        except DataSourceError as exc:
            logger.warning("backfill: coingecko history failed for %s (%s): %s", coin_id, target_date, exc)

    if defillama_client is not None and defillama_slug:
        try:
            target_epoch = int(datetime.combine(target_date, datetime.min.time()).timestamp())
            tvl = defillama_client.get_tvl_at_or_before(defillama_slug, target_epoch)
            if tvl is not None:
                baseline["tvl_usd"] = tvl
                if baseline["source"] == "missing":
                    baseline["source"] = "api_backfill"
        except DataSourceError as exc:
            logger.warning(
                "backfill: defillama tvl failed for %s (%s): %s", defillama_slug, target_date, exc
            )

    return baseline
