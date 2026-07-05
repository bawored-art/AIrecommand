from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class AnalysisContext:
    """8개 Analyzer가 공유하는 입력. Analyzer는 서로를 참조하지 않고 이 컨텍스트만으로 동작한다."""

    coin_id: str
    symbol: str
    name: str
    snapshot: dict                              # Stage1 CoinSnapshot.to_dict()
    sector_peers: list = field(default_factory=list)   # 동일 카테고리 다른 코인들의 snapshot dict
    headlines: list = field(default_factory=list)      # 이 코인을 언급하는 RSS 헤드라인만 사전 필터링됨
    clients: dict = field(default_factory=dict)        # {"coingecko", "defillama", "github", "llm"}
    config: dict = field(default_factory=dict)
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def client(self, name: str):
        return self.clients.get(name)


@dataclass
class AnalyzerResult:
    analyzer: str
    coin_id: str
    metrics: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    data_quality: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "analyzer": self.analyzer,
            "coin_id": self.coin_id,
            "metrics": self.metrics,
            "evidence": self.evidence,
            "data_quality": self.data_quality,
        }


class BaseAnalyzer(ABC):
    """모든 Analyzer의 공통 계약.

    - 다른 Analyzer의 출력에 의존하지 않는다 (AnalysisContext만 입력으로 받는다).
    - 데이터가 없으면 추정하지 않고 metrics를 null로, data_quality에 사유를 남긴다 (Hallucination 0%).
    - analyze()는 async이며 내부 I/O는 asyncio.to_thread로 오프로드해 여러 Analyzer가 동시에 진행되게 한다.
    """

    name: str = "base"

    @abstractmethod
    async def analyze(self, context: AnalysisContext) -> AnalyzerResult:
        raise NotImplementedError

    def _result(self, coin_id: str, metrics: dict, evidence: list, data_quality: dict) -> AnalyzerResult:
        return AnalyzerResult(analyzer=self.name, coin_id=coin_id, metrics=metrics,
                               evidence=evidence, data_quality=data_quality)

    def _unavailable(self, coin_id: str, reason: str, metrics: Optional[dict] = None) -> AnalyzerResult:
        return AnalyzerResult(
            analyzer=self.name, coin_id=coin_id, metrics=metrics or {}, evidence=[],
            data_quality={"status": "unavailable", "reason": reason},
        )


def epoch_seconds(dt: datetime, days_ago: int = 0) -> int:
    return int((dt - timedelta(days=days_ago)).timestamp())


def pct_change(current: Optional[float], baseline: Optional[float]) -> Optional[float]:
    """current가 baseline 대비 몇 % 변했는지. 값이 없거나 baseline이 0이면 계산하지 않고 None."""
    if current is None or baseline is None or baseline == 0:
        return None
    return (current - baseline) / abs(baseline) * 100.0


def growth_from_snapshot_baseline(snapshot: dict, field_key: str) -> dict:
    """Stage1 스냅샷의 baseline_30d/90d에서 특정 필드의 30/90일 변화율을 계산한다."""
    current = snapshot.get(field_key)
    baseline_30 = (snapshot.get("baseline_30d") or {}).get(field_key)
    baseline_90 = (snapshot.get("baseline_90d") or {}).get(field_key)
    return {
        "current": current,
        "value_30d_ago": baseline_30,
        "value_90d_ago": baseline_90,
        "change_30d_pct": pct_change(current, baseline_30),
        "change_90d_pct": pct_change(current, baseline_90),
    }


def percentile_rank_cheapness(value: Optional[float], peer_values: list) -> Optional[float]:
    """peer_values 중 이 값보다 큰(더 비싼) 비율을 0~100 백분위로 반환. 높을수록 상대적으로 저평가."""
    clean_peers = [v for v in peer_values if v is not None]
    if value is None or len(clean_peers) < 2:
        return None
    more_expensive = sum(1 for v in clean_peers if v > value)
    return round(more_expensive / len(clean_peers) * 100.0, 1)
