import asyncio
import logging
from typing import Optional

from datasources.base import DataSourceError

from .base import AnalysisContext, AnalyzerResult, BaseAnalyzer

logger = logging.getLogger(__name__)


class DeveloperAnalyzer(BaseAnalyzer):
    """GitHub 커밋 페이스(30일 vs 90일 평균), 컨트리뷰터 수, 최근 릴리즈 빈도."""

    name = "developer"

    async def analyze(self, context: AnalysisContext) -> AnalyzerResult:
        return await asyncio.to_thread(self._analyze_sync, context)

    def _analyze_sync(self, context: AnalysisContext) -> AnalyzerResult:
        snapshot = context.snapshot
        owner_repo = snapshot.get("github_owner_repo")
        github = context.client("github")

        if not owner_repo:
            reason = (snapshot.get("data_flags") or {}).get("github", "no_repo")
            return self._unavailable(context.coin_id, reason=reason)
        if github is None:
            return self._unavailable(context.coin_id, reason="github_disabled")

        owner, repo = owner_repo.split("/", 1)
        commits_30d = snapshot.get("commits_30d")
        commits_90d = snapshot.get("commits_90d")

        metrics = {
            "commits_30d": commits_30d,
            "commits_90d": commits_90d,
            # 1보다 크면 최근 30일 커밋 페이스가 90일 평균보다 가속되고 있다는 뜻
            "commit_pace_ratio": _pace_ratio(commits_30d, commits_90d),
            "contributors_count": None,
            "releases_30d": None,
            "releases_90d": None,
        }
        evidence = [{"type": "github_repo", "repo": owner_repo, "source": "github"}]
        notes = []

        try:
            metrics["contributors_count"] = github.get_contributors_count(owner, repo)
        except DataSourceError as exc:
            logger.warning("developer: contributors fetch failed for %s: %s", owner_repo, exc)
            notes.append("contributors_count: github API 호출 실패로 결측")

        try:
            release_counts = github.get_release_counts(owner, repo, context.now)
            metrics["releases_30d"] = release_counts.get("releases_30d")
            metrics["releases_90d"] = release_counts.get("releases_90d")
        except DataSourceError as exc:
            logger.warning("developer: releases fetch failed for %s: %s", owner_repo, exc)
            notes.append("releases_30d/90d: github API 호출 실패로 결측")

        data_quality = {"status": "ok" if not notes else "partial", "notes": notes}
        return self._result(context.coin_id, metrics, evidence, data_quality)


def _pace_ratio(commits_30d: Optional[int], commits_90d: Optional[int]) -> Optional[float]:
    if commits_30d is None or commits_90d is None or commits_90d == 0:
        return None
    recent_daily_avg = commits_30d / 30.0
    baseline_daily_avg = commits_90d / 90.0
    if baseline_daily_avg == 0:
        return None
    return round(recent_daily_avg / baseline_daily_avg, 3)
