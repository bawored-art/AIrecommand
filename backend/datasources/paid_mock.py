import logging

from .base import BaseDataSource

logger = logging.getLogger(__name__)


class SantimentInterface(BaseDataSource):
    """유료 온체인/소셜 데이터 소스(Santiment 등) 인터페이스.

    API 키가 있을 때만 실제 구현체를 연결하고, 없으면 MockSantimentClient를 사용한다.
    """

    def get_social_volume(self, symbol: str, days: int = 30) -> dict:
        raise NotImplementedError

    def get_dev_activity(self, symbol: str, days: int = 30) -> dict:
        raise NotImplementedError


class MockSantimentClient(SantimentInterface):
    def __init__(self, cache=None, **kwargs):
        super().__init__(name="santiment_mock", base_url="", cache=cache, **kwargs)

    def get_social_volume(self, symbol: str, days: int = 30) -> dict:
        logger.info("santiment_mock: API 키 없음 — %s 소셜 볼륨 mock 반환", symbol)
        return {"symbol": symbol, "days": days, "social_volume": None, "is_mock": True}

    def get_dev_activity(self, symbol: str, days: int = 30) -> dict:
        logger.info("santiment_mock: API 키 없음 — %s 개발 활동 mock 반환", symbol)
        return {"symbol": symbol, "days": days, "dev_activity": None, "is_mock": True}
