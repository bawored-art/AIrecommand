from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class CoinSnapshot:
    id: str
    symbol: str
    name: str
    price_usd: Optional[float] = None
    market_cap_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    circulating_supply: Optional[float] = None
    fdv_usd: Optional[float] = None
    categories: list = field(default_factory=list)
    # Stage4 코인 개요(설명/체인/출시연도)용 정적 메타데이터. coin_detail에서 추가 API 호출 없이 추출.
    description_en: Optional[str] = None
    genesis_date: Optional[str] = None
    asset_platform_id: Optional[str] = None
    tvl_usd: Optional[float] = None
    fees_24h_usd: Optional[float] = None
    github_owner_repo: Optional[str] = None
    github_stars: Optional[int] = None
    commits_30d: Optional[int] = None
    commits_90d: Optional[int] = None
    baseline_30d: dict = field(default_factory=dict)
    baseline_90d: dict = field(default_factory=dict)
    # 각 지표를 어떤 소스/경로로 채웠는지(ok / fallback / missing 등) 기록해 투명성을 보장
    data_flags: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
