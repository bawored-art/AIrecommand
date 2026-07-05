import json
from datetime import date, datetime

import pytest

from common.config import load_config
from pipeline import publish


def _coin_ref(coin_id, symbol=None, name=None):
    return {"coin_id": coin_id, "symbol": symbol or coin_id, "name": name or coin_id}


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# 순위 변동 / NEW 뱃지 / 이탈 계산
# ---------------------------------------------------------------------------

def test_compute_rank_changes_marks_new_entries():
    current = [_coin_ref("a"), _coin_ref("b")]
    previous = {"items": [{"coin_id": "b", "rank": 1}]}

    changes = publish.compute_rank_changes(current, previous)

    assert changes["a"]["badge"] == "NEW"
    assert changes["a"]["previous_rank"] is None
    assert changes["b"]["badge"] is None
    assert changes["b"]["previous_rank"] == 1
    assert changes["b"]["rank_change"] == -1  # 1위 -> 2위, 하락


def test_compute_rank_changes_positive_when_moved_up():
    current = [_coin_ref("a")]
    previous = {"items": [{"coin_id": "a", "rank": 5}]}

    changes = publish.compute_rank_changes(current, previous)

    assert changes["a"]["rank_change"] == 4  # 5위 -> 1위


def test_compute_rank_changes_all_new_when_no_previous_run():
    changes = publish.compute_rank_changes([_coin_ref("a"), _coin_ref("b")], None)
    assert all(c["badge"] == "NEW" for c in changes.values())


def test_compute_exited_coins():
    current = [_coin_ref("a")]
    previous = {"items": [{"coin_id": "a", "rank": 1}, {"coin_id": "b", "symbol": "b", "name": "B", "rank": 2}]}

    exited = publish.compute_exited_coins(current, previous)

    assert len(exited) == 1
    assert exited[0]["coin_id"] == "b"
    assert exited[0]["previous_rank"] == 2


def test_compute_exited_coins_empty_when_no_previous_run():
    assert publish.compute_exited_coins([_coin_ref("a")], None) == []


# ---------------------------------------------------------------------------
# 다음 갱신 시각 계산
# ---------------------------------------------------------------------------

def test_compute_next_update_kst_same_day():
    now = datetime(2026, 7, 5, 10, 0, tzinfo=publish.KST)
    assert publish.compute_next_update_kst(["07:00", "19:00"], now) == datetime(2026, 7, 5, 19, 0, tzinfo=publish.KST)


def test_compute_next_update_kst_rolls_to_next_day():
    now = datetime(2026, 7, 5, 20, 0, tzinfo=publish.KST)
    assert publish.compute_next_update_kst(["07:00", "19:00"], now) == datetime(2026, 7, 6, 7, 0, tzinfo=publish.KST)


def test_history_slot_label():
    assert publish._history_slot_label(datetime(2026, 7, 5, 8, 0, tzinfo=publish.KST)) == "am"
    assert publish._history_slot_label(datetime(2026, 7, 5, 20, 0, tzinfo=publish.KST)) == "pm"


# ---------------------------------------------------------------------------
# 90일 보관 정리
# ---------------------------------------------------------------------------

def test_prune_old_history_removes_only_expired_files(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-01-01-am.json").write_text("{}")
    (history_dir / "2026-06-01-pm.json").write_text("{}")
    (history_dir / "not-a-history-file.json").write_text("{}")

    removed = publish.prune_old_history(history_dir, date(2026, 7, 5), retention_days=90)

    assert "2026-01-01-am.json" in removed
    assert "2026-06-01-pm.json" not in removed
    assert not (history_dir / "2026-01-01-am.json").exists()
    assert (history_dir / "2026-06-01-pm.json").exists()
    assert (history_dir / "not-a-history-file.json").exists()  # 패턴 불일치 파일은 건드리지 않는다


def test_prune_old_history_missing_dir_returns_empty(tmp_path):
    assert publish.prune_old_history(tmp_path / "nonexistent", date(2026, 7, 5), 90) == []


def test_build_history_index_lists_only_matching_files(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-01-01-am.json").write_text("{}")
    (history_dir / "2026-01-02-pm.json").write_text("{}")
    (history_dir / "index.json").write_text("{}")

    entries = publish.build_history_index(history_dir)

    assert entries == ["2026-01-01-am", "2026-01-02-pm"]


def test_build_history_index_missing_dir_returns_empty(tmp_path):
    assert publish.build_history_index(tmp_path / "nonexistent") == []


# ---------------------------------------------------------------------------
# run() 통합: Stage1/2/3 산출물을 조인해 frontend/public/data 전체를 생성
# ---------------------------------------------------------------------------

SAMPLE_ANALYZERS = {
    "onchain_growth": {"metrics": {"tvl_growth": {"change_30d_pct": 10}, "stablecoin_inflow": {"status": "not_applicable"}}, "data_quality": {"status": "ok"}},
    "user_ecosystem": {"metrics": {}, "data_quality": {"status": "ok"}},
    "developer": {"metrics": {}, "data_quality": {"status": "ok"}},
    "catalyst": {"metrics": {"catalysts": []}, "data_quality": {"status": "ok"}},
    "valuation": {"metrics": {}, "data_quality": {"status": "ok"}},
    "news": {"metrics": {}, "data_quality": {"status": "ok"}},
    "technical": {"metrics": {}, "data_quality": {"status": "ok"}, "evidence": []},
    "risk": {"metrics": {"risk_flags": []}, "data_quality": {"status": "ok"}},
}


def _sample_ranked_coin(coin_id):
    return {
        "coin_id": coin_id, "symbol": coin_id, "name": coin_id.title(),
        "base_score": 70.0, "final_score": 70.0,
        "breakdown": {
            "vpd": {"weight": 20, "points": 15.0, "fg_raw_pct": 5.0, "pg_raw_pct": -2.0, "percentile": 80.0,
                    "quadrant": "leading_opportunity", "quadrant_label": "선행 기회", "missing": False, "reason": "..."},
            "onchain_growth": {"weight": 25, "points": 15.0, "raw_value": 10.0, "percentile": 60.0,
                                "missing": False, "reason": "TVL 30일 +10%"},
            "developer": {"weight": 15, "points": 7.5, "raw_value": None, "percentile": None,
                          "missing": True, "reason": "GitHub 데이터 없음"},
            "user_ecosystem": {"weight": 10, "points": 5.0, "raw_value": None, "percentile": None,
                                "missing": True, "reason": "수수료 데이터 없음"},
            "catalyst": {"weight": 10, "points": 5.0, "raw_value": 0.0, "percentile": 50.0,
                         "missing": False, "reason": "향후 촉매 없음"},
            "valuation": {"weight": 10, "points": 5.0, "sector_percentile": None,
                          "missing": True, "reason": "섹터 표본 부족"},
            "risk": {"weight": 10, "points": 10.0, "raw_value": 0.0, "percentile": 100.0,
                     "missing": False, "reason": "감지된 리스크 없음"},
        },
        "overheat": {"excluded": False, "penalty": 0.0, "reasons": []},
        "overheat_relaxed_mode": False,
        "confidence": {"score": 70.0, "coverage": 0.7, "freshness": 0.8, "consistency": 0.9},
        "technical": {"rsi_14": 50.0, "ma_200d_deviation_pct": 0.0, "return_30d_pct": 5.0, "return_90d_pct": 10.0},
        "context": {"price_usd": 1.0, "market_cap_usd": 1000.0},
        "summary": "총점 70.0 = 온체인 +15.0 + ... + 과열필터 -0.0",
    }


def _sample_snapshot(coin_id):
    return {
        "id": coin_id, "symbol": coin_id, "name": coin_id.title(), "categories": [],
        "description_en": None, "genesis_date": None, "asset_platform_id": None,
    }


class FakeLLMClient:
    def __init__(self):
        self.calls_made = 0

    def generate_json(self, system_prompt, user_prompt, max_tokens=2000):
        self.calls_made += 1
        return {
            "leading_evidence_summary": "온체인 성장 15.0점으로 펀더멘털이 개선되고 있습니다.",
            "one_liner": "테스트 코인",
            "description_summary": None,
            "primary_use_case": "결제",
            "detailed_reasons": ["온체인 성장 15.0점입니다."],
            "risk_summary": "감지된 리스크가 없습니다.",
            "ai_summary": "펀더멘털이 개선되고 있어 지속 관찰이 필요합니다.",
        }


def _make_ranking(coin_ids):
    return {
        "date": "2026-07-05", "universe_count": len(coin_ids), "top_n": 20, "relaxed_mode": True,
        "candidate_count": len(coin_ids), "momentum_leader_count": 0,
        "top20": [_sample_ranked_coin(cid) for cid in coin_ids],
        "momentum_leaders": [],
    }


@pytest.fixture
def stage_inputs(tmp_path, monkeypatch):
    config = load_config("config.yaml")
    config["history"]["latest_output"] = str(tmp_path / "top300.json")
    config["analysis"]["latest_output"] = str(tmp_path / "analysis.json")
    config["ranking"]["latest_output"] = str(tmp_path / "ranking.json")
    config["publish"]["output_dir"] = str(tmp_path / "public_data")
    config["cache"]["dir"] = str(tmp_path / "cache")
    config["logging"]["dir"] = str(tmp_path / "logs")

    _write_json(tmp_path / "top300.json", {"coins": [_sample_snapshot("coin-a")]})
    _write_json(tmp_path / "analysis.json", {"coins": [
        {"coin_id": "coin-a", "symbol": "coin-a", "name": "Coin-A", "analyzers": SAMPLE_ANALYZERS}
    ]})
    _write_json(tmp_path / "ranking.json", _make_ranking(["coin-a"]))

    monkeypatch.setattr(publish, "load_config", lambda path: config)
    monkeypatch.setattr(publish, "build_llm_client", lambda cfg, max_calls_per_run=None: FakeLLMClient())
    monkeypatch.setattr(publish, "_build_market_clients", lambda cfg, cache: {"coingecko": None, "feargreed": None})

    return tmp_path


def test_run_generates_full_file_set(stage_inputs):
    publish.run(config_path="unused")

    output_dir = stage_inputs / "public_data"
    assert (output_dir / "recommendations.json").exists()
    assert (output_dir / "coins/coin-a.json").exists()
    assert (output_dir / "market.json").exists()
    assert (output_dir / "momentum-leaders.json").exists()
    assert (output_dir / "meta.json").exists()
    assert len(list((output_dir / "history").glob("*.json"))) == 2  # 스냅샷 1개 + index.json
    history_index = json.loads((output_dir / "history/index.json").read_text(encoding="utf-8"))
    assert len(history_index["entries"]) == 1

    recommendations = json.loads((output_dir / "recommendations.json").read_text(encoding="utf-8"))
    assert recommendations["items"][0]["coin_id"] == "coin-a"
    assert recommendations["items"][0]["badge"] == "NEW"

    coin_detail = json.loads((output_dir / "coins/coin-a.json").read_text(encoding="utf-8"))
    assert coin_detail["ai_summary"] is not None
    assert coin_detail["leading_evidence_summary"] is not None
    assert coin_detail["metric_series"]["stablecoin_inflow_usd"] is None  # not_applicable 상태라 결측


def test_run_records_fg_pg_and_metric_series_for_charts(stage_inputs):
    analyzers = json.loads((stage_inputs / "analysis.json").read_text(encoding="utf-8"))
    analyzers["coins"][0]["analyzers"]["onchain_growth"]["metrics"]["tvl_growth"] = {
        "current": 120.0, "value_30d_ago": 100.0, "value_90d_ago": 80.0,
        "change_30d_pct": 20.0, "change_90d_pct": 50.0,
    }
    _write_json(stage_inputs / "analysis.json", analyzers)

    publish.run(config_path="unused")

    recommendations = json.loads((stage_inputs / "public_data/recommendations.json").read_text(encoding="utf-8"))
    assert "fg_raw_pct" in recommendations["items"][0]
    assert "pg_raw_pct" in recommendations["items"][0]

    coin_detail = json.loads((stage_inputs / "public_data/coins/coin-a.json").read_text(encoding="utf-8"))
    series = coin_detail["metric_series"]["tvl_usd"]
    assert series["points"][0] == {"label": "90일 전", "value": 80.0}
    assert series["points"][2] == {"label": "현재", "value": 120.0}


def test_run_second_pass_detects_new_badge_and_exit(stage_inputs):
    publish.run(config_path="unused")  # 1회차: coin-a가 1위

    # 2회차: coin-b가 새로 등장, coin-a는 이탈
    _write_json(stage_inputs / "top300.json", {"coins": [_sample_snapshot("coin-b")]})
    _write_json(stage_inputs / "analysis.json", {"coins": [
        {"coin_id": "coin-b", "symbol": "coin-b", "name": "Coin-B", "analyzers": SAMPLE_ANALYZERS}
    ]})
    _write_json(stage_inputs / "ranking.json", _make_ranking(["coin-b"]))

    publish.run(config_path="unused")

    recommendations = json.loads((stage_inputs / "public_data/recommendations.json").read_text(encoding="utf-8"))
    assert recommendations["items"][0]["coin_id"] == "coin-b"
    assert recommendations["items"][0]["badge"] == "NEW"
    assert recommendations["exited_since_last_run"][0]["coin_id"] == "coin-a"

    # 두 회차 모두 history 스냅샷이 남아있어야 한다 (같은 슬롯이면 덮어써질 수 있으나 최소 1개는 존재)
    assert len(list((stage_inputs / "public_data/history").glob("*.json"))) >= 1


def test_run_no_rank_change_when_same_rank(stage_inputs):
    publish.run(config_path="unused")
    publish.run(config_path="unused")  # 동일한 랭킹으로 재실행

    recommendations = json.loads((stage_inputs / "public_data/recommendations.json").read_text(encoding="utf-8"))
    item = recommendations["items"][0]
    assert item["badge"] is None
    assert item["rank_change"] == 0


def test_run_fails_without_writing_when_input_missing(tmp_path, monkeypatch):
    config = load_config("config.yaml")
    config["history"]["latest_output"] = str(tmp_path / "missing_top300.json")
    config["analysis"]["latest_output"] = str(tmp_path / "analysis.json")
    config["ranking"]["latest_output"] = str(tmp_path / "ranking.json")
    config["publish"]["output_dir"] = str(tmp_path / "public_data")
    monkeypatch.setattr(publish, "load_config", lambda path: config)

    with pytest.raises(FileNotFoundError):
        publish.run(config_path="unused")

    assert not (tmp_path / "public_data").exists()
