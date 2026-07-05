import pytest

from pipeline import run_all


def test_run_all_executes_stages_in_order(monkeypatch):
    calls = []

    def _make_stage(name):
        def _stage(config_path):
            calls.append(name)
        return _stage

    monkeypatch.setattr(run_all, "STAGES", [
        ("collect", _make_stage("collect")),
        ("analyze", _make_stage("analyze")),
        ("rank", _make_stage("rank")),
        ("publish", _make_stage("publish")),
    ])

    run_all.run(config_path="config.yaml")

    assert calls == ["collect", "analyze", "rank", "publish"]


def test_run_all_stops_on_failure_and_skips_later_stages(monkeypatch):
    calls = []

    def _ok_stage(name):
        def _stage(config_path):
            calls.append(name)
        return _stage

    def _failing_stage(config_path):
        calls.append("analyze")
        raise RuntimeError("simulated analyze failure")

    monkeypatch.setattr(run_all, "STAGES", [
        ("collect", _ok_stage("collect")),
        ("analyze", _failing_stage),
        ("rank", _ok_stage("rank")),
        ("publish", _ok_stage("publish")),
    ])

    with pytest.raises(RuntimeError):
        run_all.run(config_path="config.yaml")

    assert calls == ["collect", "analyze"]  # rank/publish는 실행되지 않아야 한다
