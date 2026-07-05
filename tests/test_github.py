from unittest.mock import MagicMock

from datasources.github import GitHubClient


def test_get_commit_counts_sums_recent_weeks(tmp_cache, mock_json_response):
    client = GitHubClient(cache=tmp_cache, max_retries=1)
    client.session = MagicMock()
    weeks = [{"total": i} for i in range(1, 54)]  # 53주치 데이터
    client.session.request.return_value = mock_json_response(weeks)

    counts = client.get_commit_counts("owner", "repo")

    assert counts["commits_30d"] == sum(range(50, 54))
    assert counts["commits_90d"] == sum(range(41, 54))


def test_get_repo_returns_parsed_json(tmp_cache, mock_json_response):
    client = GitHubClient(cache=tmp_cache, max_retries=1)
    client.session = MagicMock()
    client.session.request.return_value = mock_json_response({"stargazers_count": 42})

    repo = client.get_repo("owner", "repo")

    assert repo["stargazers_count"] == 42
