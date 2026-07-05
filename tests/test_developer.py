import asyncio

from analyzers.developer import DeveloperAnalyzer


class FakeGitHub:
    def __init__(self, contributors=12, releases=None):
        self.contributors = contributors
        self.releases = releases or {"releases_30d": 2, "releases_90d": 5}

    def get_contributors_count(self, owner, repo):
        return self.contributors

    def get_release_counts(self, owner, repo, now):
        return self.releases


def test_unavailable_when_no_github_repo(context_factory, base_snapshot, fixed_now):
    base_snapshot["github_owner_repo"] = None
    base_snapshot["data_flags"]["github"] = "no_repo"
    context = context_factory(base_snapshot, clients={"github": FakeGitHub()}, now=fixed_now)

    result = asyncio.run(DeveloperAnalyzer().analyze(context))

    assert result.data_quality["status"] == "unavailable"
    assert result.data_quality["reason"] == "no_repo"


def test_unavailable_when_github_client_disabled(context_factory, base_snapshot, fixed_now):
    context = context_factory(base_snapshot, clients={"github": None}, now=fixed_now)

    result = asyncio.run(DeveloperAnalyzer().analyze(context))

    assert result.data_quality["status"] == "unavailable"
    assert result.data_quality["reason"] == "github_disabled"


def test_commit_pace_ratio_and_enrichment(context_factory, base_snapshot, fixed_now):
    # commits_30d=60 -> 2/day, commits_90d=150 -> 1.667/day => pace_ratio ~1.2 (accelerating)
    context = context_factory(base_snapshot, clients={"github": FakeGitHub()}, now=fixed_now)

    result = asyncio.run(DeveloperAnalyzer().analyze(context))

    assert result.metrics["commits_30d"] == 60
    assert result.metrics["commits_90d"] == 150
    assert result.metrics["commit_pace_ratio"] == round((60 / 30) / (150 / 90), 3)
    assert result.metrics["contributors_count"] == 12
    assert result.metrics["releases_30d"] == 2
    assert result.metrics["releases_90d"] == 5
    assert result.data_quality["status"] == "ok"


def test_commit_pace_ratio_none_when_baseline_missing(context_factory, base_snapshot, fixed_now):
    base_snapshot["commits_90d"] = None
    context = context_factory(base_snapshot, clients={"github": FakeGitHub()}, now=fixed_now)

    result = asyncio.run(DeveloperAnalyzer().analyze(context))

    assert result.metrics["commit_pace_ratio"] is None
