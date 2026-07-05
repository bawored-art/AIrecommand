import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from .base import BaseDataSource

logger = logging.getLogger(__name__)

# GitHub commit_activity 엔드포인트는 통계를 처음 계산할 때 202를 반환하므로 재시도 대상에 포함한다.
DEFAULT_RETRY_ON_STATUS = (429, 500, 502, 503, 504, 202)


class GitHubClient(BaseDataSource):
    def __init__(
        self,
        cache=None,
        token: Optional[str] = None,
        base_url: str = "https://api.github.com",
        **kwargs,
    ):
        kwargs.setdefault("retry_on_status", DEFAULT_RETRY_ON_STATUS)
        super().__init__(name="github", base_url=base_url, cache=cache, **kwargs)
        self.token = token

    def _headers(self) -> dict:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_repo(self, owner: str, repo: str) -> dict:
        cache_key = f"github:repo:{owner}/{repo}"
        return self.fetch_json(
            f"/repos/{owner}/{repo}", cache_key=cache_key, ttl_seconds=86400, headers=self._headers()
        ) or {}

    def get_weekly_commit_activity(self, owner: str, repo: str) -> list:
        cache_key = f"github:commit_activity:{owner}/{repo}"
        data = self.fetch_json(
            f"/repos/{owner}/{repo}/stats/commit_activity",
            cache_key=cache_key, ttl_seconds=43200, headers=self._headers(),
        )
        return data or []

    def get_commit_counts(self, owner: str, repo: str) -> dict:
        """최근 52주 주간 커밋 수 배열에서 최근 30/90일치를 근사(4주/13주)로 합산."""
        weeks = self.get_weekly_commit_activity(owner, repo)
        last_4_weeks = sum(week.get("total", 0) for week in weeks[-4:])
        last_13_weeks = sum(week.get("total", 0) for week in weeks[-13:])
        return {"commits_30d": last_4_weeks, "commits_90d": last_13_weeks}

    def get_contributors_count(self, owner: str, repo: str, sample_size: int = 100) -> Optional[int]:
        """상위 sample_size명까지의 컨트리뷰터 수를 근사치로 반환 (그 이상은 페이지네이션 생략)."""
        cache_key = f"github:contributors:{owner}/{repo}"
        data = self.fetch_json(
            f"/repos/{owner}/{repo}/contributors",
            params={"per_page": sample_size, "anon": "true"},
            cache_key=cache_key, ttl_seconds=86400, headers=self._headers(),
        )
        if data is None:
            return None
        return len(data)

    def get_releases(self, owner: str, repo: str, per_page: int = 30) -> list:
        cache_key = f"github:releases:{owner}/{repo}"
        data = self.fetch_json(
            f"/repos/{owner}/{repo}/releases",
            params={"per_page": per_page},
            cache_key=cache_key, ttl_seconds=43200, headers=self._headers(),
        )
        return data or []

    def get_release_counts(self, owner: str, repo: str, now: datetime) -> dict:
        """최근 30/90일 내 릴리즈 수 (published_at 기준)."""
        releases = self.get_releases(owner, repo)
        cutoff_30 = now - timedelta(days=30)
        cutoff_90 = now - timedelta(days=90)
        count_30, count_90 = 0, 0
        for release in releases:
            published_at = release.get("published_at")
            if not published_at:
                continue
            try:
                published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(tzinfo=timezone.utc)
            if published_dt >= cutoff_30:
                count_30 += 1
            if published_dt >= cutoff_90:
                count_90 += 1
        return {"releases_30d": count_30, "releases_90d": count_90}
