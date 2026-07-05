import logging
import time
from typing import Any, Callable, Iterable, Optional

import requests

logger = logging.getLogger(__name__)


class DataSourceError(Exception):
    """재시도를 모두 소진했거나 복구 불가능한 응답을 받았을 때 발생."""


def _build_session(pool_maxsize: int) -> requests.Session:
    """Stage2 analyze.py는 코인당 여러 Analyzer를 동시에 실행하므로 기본 커넥션 풀(10)보다
    넉넉한 풀을 마운트해 'connection pool is full' 경고와 불필요한 재연결을 줄인다."""
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=pool_maxsize, pool_maxsize=pool_maxsize)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class BaseDataSource:
    """모든 외부 API 클라이언트가 공유하는 재시도/백오프/캐시 인프라.

    각 소스별 클라이언트는 이 클래스를 상속해 자신만의 엔드포인트 메서드를 추가한다.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        cache: Optional[Any] = None,
        timeout: int = 15,
        max_retries: int = 4,
        backoff_factor: float = 1.5,
        retry_on_status: Iterable[int] = (429, 500, 502, 503, 504),
        session: Optional[requests.Session] = None,
        pool_maxsize: int = 32,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.retry_on_status = set(retry_on_status)
        self.session = session or _build_session(pool_maxsize)

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            sleep_s = self.backoff_factor**attempt
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "%s: request error on attempt %d/%d for %s: %s",
                    self.name, attempt, self.max_retries, url, exc,
                )
            else:
                if response.status_code not in self.retry_on_status:
                    try:
                        response.raise_for_status()
                    except requests.HTTPError as exc:
                        raise DataSourceError(
                            f"{self.name}: HTTP {response.status_code} for {url}"
                        ) from exc
                    return response

                last_exc = DataSourceError(
                    f"{self.name}: retryable status {response.status_code} for {url}"
                )
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    sleep_s = float(retry_after)
                logger.warning(
                    "%s: retryable status %s on attempt %d/%d for %s, sleeping %.1fs",
                    self.name, response.status_code, attempt, self.max_retries, url, sleep_s,
                )

            if attempt < self.max_retries:
                time.sleep(sleep_s)

        raise DataSourceError(
            f"{self.name}: failed after {self.max_retries} attempts for {url}"
        ) from last_exc

    def fetch_json(
        self,
        path: str,
        method: str = "GET",
        params: Optional[dict] = None,
        cache_key: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        **kwargs,
    ) -> Any:
        def _do_fetch():
            response = self._request(method, path, params=params, **kwargs)
            return response.json()

        if self.cache is None or cache_key is None:
            return _do_fetch()
        return self.cache.get_or_set(cache_key, _do_fetch, ttl_seconds)
