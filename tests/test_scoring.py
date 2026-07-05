import pytest

from pipeline import scoring
from tests.conftest import make_analyzer_bundle as _analyzers


FG_WEIGHTS = {
    "onchain_tvl_growth": 0.35,
    "onchain_stablecoin_inflow": 0.15,
    "user_fees_growth": 0.25,
    "developer_commit_accel": 0.25,
}


# ---------------------------------------------------------------------------
# 통계 유틸
# ---------------------------------------------------------------------------

def test_zscore_population_normal():
    z = scoring.zscore_population({"a": 10, "b": 20, "c": 30})
    assert z["b"] == 0.0
    assert z["a"] < 0 < z["c"]
    assert z["a"] == pytest.approx(-z["c"])


def test_zscore_population_keeps_none():
    z = scoring.zscore_population({"a": 10, "b": None, "c": 30})
    assert z["b"] is None
    assert z["a"] == -1.0
    assert z["c"] == 1.0


def test_zscore_population_too_few_or_zero_stdev():
    assert scoring.zscore_population({"a": 10})["a"] == 0.0
    z = scoring.zscore_population({"a": 10, "b": 10})
    assert z["a"] == 0.0 and z["b"] == 0.0


def test_percentile_of_higher_is_better():
    # mid-rank: 동점이 없는 4개 값은 각자 순위 구간(25%)의 중앙에 놓인다 -> 12.5/37.5/62.5/87.5
    population = [10, 20, 30, 40]
    assert scoring.percentile_of(10, population, higher_is_better=True) == 12.5
    assert scoring.percentile_of(40, population, higher_is_better=True) == 87.5


def test_percentile_of_lower_is_better():
    population = [10, 20, 30, 40]
    assert scoring.percentile_of(10, population, higher_is_better=False) == 87.5
    assert scoring.percentile_of(40, population, higher_is_better=False) == 12.5


def test_percentile_of_none_cases():
    assert scoring.percentile_of(None, [1, 2, 3]) is None
    assert scoring.percentile_of(5, [1]) is None


def test_percentile_of_ties_share_mid_rank():
    # 24개가 0, 1개만 2.75인 경우 — 0인 코인들은 부당하게 최상위 근처가 아니라 중간 정도를 받아야 한다
    population = [0] * 24 + [2.75]
    tied_percentile = scoring.percentile_of(0, population, higher_is_better=True)
    outlier_percentile = scoring.percentile_of(2.75, population, higher_is_better=True)
    assert tied_percentile == pytest.approx(48.0)
    assert outlier_percentile == pytest.approx(98.0)


def test_weighted_average_renormalizes_missing():
    result = scoring.weighted_average(
        {"a": 10, "b": 20, "c": None}, {"a": 0.5, "b": 0.3, "c": 0.2}
    )
    assert result == pytest.approx((10 * 0.5 + 20 * 0.3) / 0.8)


def test_weighted_average_all_missing_is_none():
    assert scoring.weighted_average({"a": None}, {"a": 1.0}) is None


# ---------------------------------------------------------------------------
# FG / PG / VPD
# ---------------------------------------------------------------------------

def test_compute_fg_weighted_average_of_30d_changes():
    analyzers = _analyzers(
        onchain={"tvl_growth": {"change_30d_pct": 10}, "stablecoin_inflow": {"change_30d_pct": 20}},
        user={"fees_growth": {"change_30d_pct": 30}},
        developer={"commit_pace_ratio": 1.2},
    )
    fg = scoring.compute_fg(analyzers, FG_WEIGHTS)
    expected = (10 * 0.35 + 20 * 0.15 + 30 * 0.25 + 20 * 0.25) / 1.0
    assert fg == pytest.approx(expected)


def test_compute_fg_none_when_all_missing():
    analyzers = _analyzers()
    assert scoring.compute_fg(analyzers, FG_WEIGHTS) is None


def test_compute_pg_uses_technical_return_30d():
    analyzers = _analyzers(technical={"return_30d_pct": -5.5})
    assert scoring.compute_pg(analyzers) == -5.5


def test_compute_pg_none_when_missing():
    assert scoring.compute_pg(_analyzers()) is None


@pytest.mark.parametrize("fg_z,pg_z,expected", [
    (1.0, -1.0, "leading_opportunity"),
    (1.0, 1.0, "co_movement"),
    (-1.0, 1.0, "pure_pump"),
    (-1.0, -1.0, "stagnation"),
    (None, 1.0, "unknown"),
    (1.0, None, "unknown"),
])
def test_classify_vpd_quadrant(fg_z, pg_z, expected):
    assert scoring.classify_vpd_quadrant(fg_z, pg_z) == expected


# ---------------------------------------------------------------------------
# 카테고리 원자료 추출
# ---------------------------------------------------------------------------

def test_extract_onchain_composite_averages_available_horizons():
    analyzers = _analyzers(onchain={
        "tvl_growth": {"change_30d_pct": 10, "change_90d_pct": 30},
        "stablecoin_inflow": {"change_30d_pct": None},
    })
    assert scoring.extract_onchain_composite(analyzers) == pytest.approx(20.0)


def test_extract_onchain_composite_none_when_no_data():
    assert scoring.extract_onchain_composite(_analyzers()) is None


def test_extract_developer_composite_combines_commit_and_release_pace():
    analyzers = _analyzers(developer={
        "commit_pace_ratio": 1.5, "releases_30d": 3, "releases_90d": 3,
    })
    # commit accel = 50; release: expected_30d_rate=1.0, actual=3 -> (3/1 - 1)*100 = 200
    assert scoring.extract_developer_composite(analyzers) == pytest.approx((50 + 200) / 2)


def test_extract_developer_composite_none_when_missing():
    assert scoring.extract_developer_composite(_analyzers()) is None


def test_extract_catalyst_composite_sums_confidence():
    analyzers = _analyzers(catalyst={"catalysts": [{"confidence": 0.9}, {"confidence": 0.5}]})
    assert scoring.extract_catalyst_composite(analyzers) == pytest.approx(1.4)


def test_extract_catalyst_composite_zero_confidence_is_not_treated_as_missing():
    analyzers = _analyzers(catalyst={"catalysts": [{"confidence": 0.0}]})
    assert scoring.extract_catalyst_composite(analyzers) == 0.0


def test_extract_catalyst_composite_none_when_llm_unavailable():
    analyzers = _analyzers(catalyst={"catalysts": None})
    assert scoring.extract_catalyst_composite(analyzers) is None


def test_extract_valuation_percentile_averages_available():
    analyzers = _analyzers(valuation={"mc_to_tvl_percentile": 80, "mc_to_fees_percentile": None})
    assert scoring.extract_valuation_percentile(analyzers) == 80.0


def test_extract_risk_composite_weights_by_severity():
    analyzers = _analyzers(risk={"risk_flags": [{"severity": "high"}, {"severity": "low"}]})
    assert scoring.extract_risk_composite(analyzers) == 4.0


def test_extract_risk_composite_none_when_missing():
    assert scoring.extract_risk_composite(_analyzers()) is None


def test_extract_risk_composite_zero_when_no_flags():
    assert scoring.extract_risk_composite(_analyzers(risk={"risk_flags": []})) == 0.0


# ---------------------------------------------------------------------------
# 과열 필터
# ---------------------------------------------------------------------------

OVERHEAT_CFG = {
    "exclude": {"return_30d_pct_gt": 60, "return_90d_pct_gt": 150},
    "penalty": {
        "rsi_gt": 75, "rsi_penalty": 5,
        "ma200_deviation_gt": 80, "ma200_penalty": 5,
        "high90d_within_pct": -5, "high90d_penalty": 3,
    },
    "relaxed_penalty": {"return_30d_pct_gt_penalty": 15, "return_90d_pct_gt_penalty": 20},
}


def test_overheat_excludes_on_30d_threshold():
    analyzers = _analyzers(technical={"return_30d_pct": 65})
    result = scoring.evaluate_overheat(analyzers, OVERHEAT_CFG, relaxed=False)
    assert result["excluded"] is True
    assert result["penalty"] == 0.0


def test_overheat_excludes_on_90d_threshold():
    analyzers = _analyzers(technical={"return_90d_pct": 160})
    result = scoring.evaluate_overheat(analyzers, OVERHEAT_CFG, relaxed=False)
    assert result["excluded"] is True


def test_overheat_not_excluded_below_threshold():
    analyzers = _analyzers(technical={"return_30d_pct": 59, "return_90d_pct": 100})
    result = scoring.evaluate_overheat(analyzers, OVERHEAT_CFG, relaxed=False)
    assert result["excluded"] is False


def test_overheat_penalties_accumulate():
    analyzers = _analyzers(technical={
        "return_30d_pct": 10, "return_90d_pct": 10,
        "rsi_14": 80, "ma_200d_deviation_pct": 90, "high_90d_position_pct": -3,
    })
    result = scoring.evaluate_overheat(analyzers, OVERHEAT_CFG, relaxed=False)
    assert result["excluded"] is False
    assert result["penalty"] == 13.0
    assert len(result["reasons"]) == 3


def test_overheat_missing_technical_data_is_not_penalized():
    result = scoring.evaluate_overheat(_analyzers(), OVERHEAT_CFG, relaxed=False)
    assert result["excluded"] is False
    assert result["penalty"] == 0.0


def test_overheat_relaxed_converts_exclusion_to_penalty():
    analyzers = _analyzers(technical={"return_30d_pct": 65})
    result = scoring.evaluate_overheat(analyzers, OVERHEAT_CFG, relaxed=True)
    assert result["excluded"] is False
    assert result["penalty"] == 15.0


def test_overheat_config_change_shifts_exclusion_boundary():
    lenient_cfg = {**OVERHEAT_CFG, "exclude": {"return_30d_pct_gt": 100, "return_90d_pct_gt": 150}}
    analyzers = _analyzers(technical={"return_30d_pct": 65})
    assert scoring.evaluate_overheat(analyzers, OVERHEAT_CFG, relaxed=False)["excluded"] is True
    assert scoring.evaluate_overheat(analyzers, lenient_cfg, relaxed=False)["excluded"] is False


# ---------------------------------------------------------------------------
# Confidence Score
# ---------------------------------------------------------------------------

CONFIDENCE_WEIGHTS = {"coverage": 0.4, "freshness": 0.3, "consistency": 0.3}


def test_confidence_full_coverage_and_consistency_scores_high():
    analyzers = _analyzers(
        onchain={"tvl_growth": {"change_30d_pct": 10}},
        user={"fees_growth": {"change_30d_pct": 10}},
        developer={"commit_pace_ratio": 1.1},
    )
    missing_flags = {k: False for k in ["vpd", "onchain_growth", "developer", "user_ecosystem", "catalyst", "valuation", "risk"]}
    result = scoring.compute_confidence(analyzers, missing_flags, CONFIDENCE_WEIGHTS)
    assert result["coverage"] == 1.0
    assert result["consistency"] == 1.0
    assert result["score"] > 80


def test_confidence_low_coverage_scores_lower():
    missing_flags = {k: True for k in ["vpd", "onchain_growth", "developer", "user_ecosystem", "catalyst", "valuation", "risk"]}
    result = scoring.compute_confidence(_analyzers(), missing_flags, CONFIDENCE_WEIGHTS)
    assert result["coverage"] == 0.0
    assert result["score"] < 50


def test_confidence_consistency_neutral_when_fewer_than_two_signals():
    analyzers = _analyzers(onchain={"tvl_growth": {"change_30d_pct": 10}})
    missing_flags = {"vpd": False}
    result = scoring.compute_confidence(analyzers, missing_flags, CONFIDENCE_WEIGHTS)
    assert result["consistency"] == 0.5
