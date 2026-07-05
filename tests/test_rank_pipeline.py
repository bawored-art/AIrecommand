import copy

import pytest

from pipeline import rank
from tests.conftest import make_analyzer_bundle

FG_WEIGHTS = {
    "onchain_tvl_growth": 0.35,
    "onchain_stablecoin_inflow": 0.15,
    "user_fees_growth": 0.25,
    "developer_commit_accel": 0.25,
}

BASE_CONFIG = {
    "scoring": {
        "weights": {
            "onchain_growth": 25, "vpd": 20, "developer": 15, "user_ecosystem": 10,
            "catalyst": 10, "valuation": 10, "risk": 10,
        },
        "fg_weights": FG_WEIGHTS,
        "neutral_score_ratio": 0.5,
    },
    "confidence": {"weights": {"coverage": 0.4, "freshness": 0.3, "consistency": 0.3}},
    "overheat_filter": {
        "exclude": {"return_30d_pct_gt": 60, "return_90d_pct_gt": 150},
        "penalty": {
            "rsi_gt": 75, "rsi_penalty": 5,
            "ma200_deviation_gt": 80, "ma200_penalty": 5,
            "high90d_within_pct": -5, "high90d_penalty": 3,
        },
        "relaxed_penalty": {"return_30d_pct_gt_penalty": 15, "return_90d_pct_gt_penalty": 20},
    },
    "ranking": {"top_n": 20, "output_dir": "unused", "latest_output": "unused"},
}


def _make_coin(idx, onchain_30d=5.0, fees_30d=5.0, pace_ratio=1.05, valuation_pct=50.0,
               risk_flags=None, catalysts=None, return_30d=5.0, return_90d=10.0,
               rsi=50.0, ma_dev=0.0, high90=-20.0):
    analyzers = make_analyzer_bundle(
        onchain={"tvl_growth": {"change_30d_pct": onchain_30d, "change_90d_pct": onchain_30d}},
        user={"fees_growth": {"change_30d_pct": fees_30d, "change_90d_pct": fees_30d}},
        developer={"commit_pace_ratio": pace_ratio, "releases_30d": 1, "releases_90d": 3},
        technical={
            "return_30d_pct": return_30d, "return_90d_pct": return_90d, "rsi_14": rsi,
            "ma_200d_deviation_pct": ma_dev, "high_90d_position_pct": high90,
        },
        catalyst={"catalysts": catalysts if catalysts is not None else []},
        valuation={"mc_to_tvl_percentile": valuation_pct, "mc_to_fees_percentile": valuation_pct},
        risk={"risk_flags": risk_flags if risk_flags is not None else []},
    )
    cid = f"coin-{idx}"
    return {"coin_id": cid, "symbol": cid, "name": cid, "analyzers": analyzers}


def _make_universe(n=25, seed_variation=True):
    coins = []
    for i in range(n):
        # 코인마다 조금씩 다른 값을 줘서 percentile 계산에 변별력이 생기게 한다.
        spread = (i - n / 2) if seed_variation else 0
        coins.append(_make_coin(
            i, onchain_30d=5.0 + spread, fees_30d=5.0 + spread * 0.5,
            pace_ratio=1.0 + spread * 0.01, valuation_pct=50.0 + spread,
            return_30d=5.0 + spread * 0.3, return_90d=10.0 + spread * 0.5,
        ))
    return coins


# ---------------------------------------------------------------------------
# P1 회귀 방지: 30일 +60% 이상 상승한 코인은 Top20에 없어야 한다
# ---------------------------------------------------------------------------

def test_overheated_coin_never_appears_in_top20():
    coins = _make_universe(n=25)
    coins.append(_make_coin(999, onchain_30d=50, fees_30d=50, pace_ratio=2.0,
                             valuation_pct=90, return_30d=65.0, return_90d=10.0))

    scored = rank.score_universe(coins, BASE_CONFIG)
    result = rank.apply_overheat_and_rank(scored, BASE_CONFIG)

    assert result["relaxed_mode"] is False
    top20_ids = {c["coin_id"] for c in result["top20"]}
    assert "coin-999" not in top20_ids
    assert any(m["coin_id"] == "coin-999" for m in result["momentum_leaders"])


def test_overheated_coin_excluded_even_when_fundamentals_are_best():
    """펀더멘털 점수가 가장 높아도 과열 기준을 넘으면 momentum_leaders로 빠져야 한다."""
    coins = _make_universe(n=25)
    coins.append(_make_coin(999, onchain_30d=1000, fees_30d=1000, pace_ratio=5.0,
                             valuation_pct=100, return_90d=200.0))  # 90일 초과 케이스

    scored = rank.score_universe(coins, BASE_CONFIG)
    result = rank.apply_overheat_and_rank(scored, BASE_CONFIG)

    top20_ids = {c["coin_id"] for c in result["top20"]}
    assert "coin-999" not in top20_ids
    momentum_ids = {m["coin_id"] for m in result["momentum_leaders"]}
    assert "coin-999" in momentum_ids


def test_top20_sorted_descending_by_final_score():
    coins = _make_universe(n=25)
    scored = rank.score_universe(coins, BASE_CONFIG)
    result = rank.apply_overheat_and_rank(scored, BASE_CONFIG)

    scores = [c["final_score"] for c in result["top20"]]
    assert scores == sorted(scores, reverse=True)
    assert len(result["top20"]) == 20


# ---------------------------------------------------------------------------
# 가중치 변경 시나리오
# ---------------------------------------------------------------------------

def test_increasing_category_weight_increases_its_point_contribution():
    coins = _make_universe(n=25)
    scored_base = rank.score_universe(coins, BASE_CONFIG)

    heavy_risk_config = copy.deepcopy(BASE_CONFIG)
    heavy_risk_config["scoring"]["weights"]["risk"] = 40
    scored_heavy = rank.score_universe(coins, heavy_risk_config)

    base_points = next(c for c in scored_base if c["coin_id"] == "coin-0")["breakdown"]["risk"]["points"]
    heavy_points = next(c for c in scored_heavy if c["coin_id"] == "coin-0")["breakdown"]["risk"]["points"]

    # 가중치가 10 -> 40으로 4배가 되면 동일 percentile에서 포인트도 비례해 커진다
    assert heavy_points == pytest.approx(base_points * 4, rel=0.01)


def test_weight_change_can_alter_final_ranking_order():
    # coin-0은 다른 모든 지표에서 유니버스 최하위(가장 부정적인 spread)다.
    coins = _make_universe(n=25)
    scored = rank.score_universe(coins, BASE_CONFIG)
    order_base = [c["coin_id"] for c in rank.apply_overheat_and_rank(scored, BASE_CONFIG)["top20"]]
    assert order_base[0] != "coin-0"  # 기본 가중치에서는 최하위권일 것

    # catalyst 가중치를 압도적으로 올리고 나머지는 거의 0에 가깝게 낮추면,
    # 다른 지표가 전부 꼴찌인 coin-0이라도 촉매 신호 하나로 1위가 될 수 있어야 한다.
    catalyst_dominant_config = copy.deepcopy(BASE_CONFIG)
    for name in catalyst_dominant_config["scoring"]["weights"]:
        catalyst_dominant_config["scoring"]["weights"][name] = 1
    catalyst_dominant_config["scoring"]["weights"]["catalyst"] = 1000

    coins_with_catalyst = copy.deepcopy(coins)
    coins_with_catalyst[0]["analyzers"]["catalyst"]["metrics"] = {
        "catalysts": [{"confidence": 0.95}, {"confidence": 0.9}, {"confidence": 0.9}]
    }
    scored_heavy = rank.score_universe(coins_with_catalyst, catalyst_dominant_config)
    order_heavy = [c["coin_id"] for c in rank.apply_overheat_and_rank(scored_heavy, catalyst_dominant_config)["top20"]]

    assert order_base != order_heavy
    assert order_heavy[0] == "coin-0"


# ---------------------------------------------------------------------------
# 과열 기준 변경 시나리오
# ---------------------------------------------------------------------------

def test_relaxing_overheat_threshold_allows_previously_excluded_coin():
    coins = _make_universe(n=25)
    coins.append(_make_coin(999, onchain_30d=50, valuation_pct=90, return_30d=65.0))

    strict_scored = rank.score_universe(coins, BASE_CONFIG)
    strict_result = rank.apply_overheat_and_rank(strict_scored, BASE_CONFIG)
    assert "coin-999" not in {c["coin_id"] for c in strict_result["top20"]}

    lenient_config = copy.deepcopy(BASE_CONFIG)
    lenient_config["overheat_filter"]["exclude"]["return_30d_pct_gt"] = 100
    lenient_scored = rank.score_universe(coins, lenient_config)
    lenient_result = rank.apply_overheat_and_rank(lenient_scored, lenient_config)
    assert "coin-999" not in {m["coin_id"] for m in lenient_result["momentum_leaders"]}


def test_tightening_overheat_penalty_lowers_final_score():
    coins = _make_universe(n=25, seed_variation=False)
    for coin in coins:
        coin["analyzers"]["technical"]["metrics"]["rsi_14"] = 80  # 모두 RSI 과열 상태

    lenient_config = copy.deepcopy(BASE_CONFIG)
    lenient_config["overheat_filter"]["penalty"]["rsi_penalty"] = 1
    strict_config = copy.deepcopy(BASE_CONFIG)
    strict_config["overheat_filter"]["penalty"]["rsi_penalty"] = 20

    lenient_scored = rank.score_universe(coins, lenient_config)
    strict_scored = rank.score_universe(coins, strict_config)
    lenient_result = rank.apply_overheat_and_rank(lenient_scored, lenient_config)
    strict_result = rank.apply_overheat_and_rank(strict_scored, strict_config)

    lenient_top_score = lenient_result["top20"][0]["final_score"]
    strict_top_score = strict_result["top20"][0]["final_score"]
    assert strict_top_score < lenient_top_score


# ---------------------------------------------------------------------------
# 완화 모드 (후보 20개 미만일 때 제외 -> 감점으로 재랭킹)
# ---------------------------------------------------------------------------

def test_relaxed_mode_triggers_when_too_few_candidates_survive():
    # 유니버스 자체가 20개 미만이거나 대부분 과열 상태라 정상 후보가 top_n 미만인 극단 상황
    coins = [_make_coin(i, return_30d=70.0 + i) for i in range(10)]  # 전부 30일 +60% 초과

    scored = rank.score_universe(coins, BASE_CONFIG)
    result = rank.apply_overheat_and_rank(scored, BASE_CONFIG)

    assert result["relaxed_mode"] is True
    # 완화 모드에서는 하드 제외 대신 감점이 적용되어 후보 풀에 남는다
    assert len(result["momentum_leaders"]) == 0
    assert len(result["top20"]) == 10
    for coin in result["top20"]:
        assert coin["overheat"]["excluded"] is False
        assert coin["overheat_relaxed_mode"] is True


def test_summary_string_reflects_breakdown_and_penalty():
    coins = _make_universe(n=25)
    scored = rank.score_universe(coins, BASE_CONFIG)
    result = rank.apply_overheat_and_rank(scored, BASE_CONFIG)

    top1 = result["top20"][0]
    assert "총점" in top1["summary"]
    assert "과열필터" in top1["summary"]
    assert scoring_label_present(top1)


def scoring_label_present(coin_result):
    from pipeline import scoring
    return all(scoring.CATEGORY_LABELS_KO[name] in coin_result["summary"] for name in coin_result["breakdown"])
