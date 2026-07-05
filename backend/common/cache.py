import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Optional


class FileCache:
    """Redis 없이 GitHub Actions 러너에서도 재사용 가능한 파일 기반 TTL 캐시.

    actions/cache로 .cache/ 디렉토리를 그대로 캐싱하면 워크플로 실행 간에도 재사용된다.
    """

    def __init__(self, cache_dir: str = ".cache", default_ttl_seconds: int = 86400):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl_seconds = default_ttl_seconds

    def _path_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def get(self, key: str) -> Optional[Any]:
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("expires_at", 0) < time.time():
            return None
        return payload.get("data")

    def set(self, key: str, data: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        payload = {"expires_at": time.time() + ttl, "cached_at": time.time(), "data": data}
        self._path_for(key).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def get_or_set(self, key: str, fetch_fn: Callable[[], Any], ttl_seconds: Optional[int] = None) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        data = fetch_fn()
        self.set(key, data, ttl_seconds)
        return data
