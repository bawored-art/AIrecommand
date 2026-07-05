from pipeline import explain

SAMPLE_CONTEXT = {
    "coin_id": "test-coin", "symbol": "tst", "name": "Test Coin", "rank": 3,
    "final_score": 72.18, "base_score": 72.18,
    "confidence": {"score": 77.3, "coverage": 0.714, "freshness": 0.625, "consistency": 1.0},
    "vpd": {"fg_raw_pct": -25.99, "pg_raw_pct": -1.81, "percentile": 78.57, "quadrant_label": "선행 기회"},
    "onchain": {"points": 12.5, "percentile": 50.0, "reason": "TVL 30일 -5.0%"},
    "developer": {"points": 7.5, "reason": "커밋 페이스 1.2배"},
    "user_ecosystem": {"points": 6.2, "reason": "수수료 30일 +10%"},
    "catalyst": {"points": 5.0, "reason": "향후 촉매 없음"},
    "valuation": {"points": 5.0, "reason": "밸류에이션 백분위 50"},
    "risk": {"points": 6.4, "reason": "감지된 리스크 플래그 없음"},
    "technical": {"rsi_14": 55.58, "ma_200d_deviation_pct": -10.0, "return_30d_pct": -1.8, "return_90d_pct": -9.2},
    "overheat": {"penalty": 0.0},
    "price_usd": 65000.0, "market_cap_usd": 1_280_000_000_000,
    "categories": ["Layer 1 (L1)"], "description_en": "Test Coin is a decentralized network.",
    "genesis_date": "2013-04-28", "launch_year": 2013, "chain": "Test Coin 자체 메인넷",
    "catalysts_detail": [],
}

VALID_RESPONSE = {
    "leading_evidence_summary": "온체인 성장 12.5점, VPD 백분위 78.57로 펀더멘털이 가격보다 먼저 개선되고 있습니다.",
    "one_liner": "탈중앙 네트워크",
    "description_summary": "테스트 코인은 탈중앙화된 네트워크입니다. 다양한 참여자가 운영합니다. 개발이 활발합니다.",
    "primary_use_case": "가치 저장 및 결제",
    "detailed_reasons": ["온체인 성장 12.5점으로 상위권입니다.", "리스크 점수 6.4점으로 특이 플래그가 없습니다."],
    "risk_summary": "감지된 리스크 플래그가 없어 상대적으로 안정적입니다.",
    "ai_summary": "펀더멘털 지표가 개선되는 가운데 가격은 아직 이를 반영하지 않았습니다. 지속적인 관찰이 필요합니다.",
}


class FakeLLMClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_json(self, system_prompt, user_prompt, max_tokens=2000):
        self.calls.append((system_prompt, user_prompt, max_tokens))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


# ---------------------------------------------------------------------------
# 금지 표현 필터
# ---------------------------------------------------------------------------

def test_find_banned_phrases_detects_direct_buy_directive():
    violations = explain.find_banned_phrases("지금 매수하세요, 좋은 기회입니다.")
    assert violations


def test_find_banned_phrases_detects_direct_sell_directive():
    violations = explain.find_banned_phrases("위험하니 매도하세요.")
    assert violations


def test_find_banned_phrases_detects_retrospective_justification():
    violations = explain.find_banned_phrases("이미 65% 상승했으므로 매수를 추천합니다.")
    assert violations
    assert any("후행적" in v for v in violations)


def test_find_banned_phrases_clean_text_has_no_violations():
    text = "가격은 30일간 5% 하락했지만 온체인 지표는 개선되고 있습니다."
    assert explain.find_banned_phrases(text) == []


def test_find_banned_phrases_percentage_without_recommend_word_is_fine():
    text = "가격이 이미 20% 상승했습니다."
    assert explain.find_banned_phrases(text) == []


# ---------------------------------------------------------------------------
# 수치 대조 검증
# ---------------------------------------------------------------------------

def test_extract_numbers_parses_percentages_and_commas():
    numbers = explain.extract_numbers("시가총액은 1,280,000 달러이고 RSI는 55.58, 변화율은 -25.99%입니다.")
    assert 1280000.0 in numbers
    assert 55.58 in numbers
    assert -25.99 in numbers


def test_build_allowed_numbers_includes_context_values():
    allowed = explain.build_allowed_numbers(SAMPLE_CONTEXT)
    assert 55.58 in allowed
    assert -25.99 in allowed
    assert 72.18 in allowed or 72.2 in allowed
    assert 2013.0 in allowed


def test_find_unverified_numbers_flags_fabricated_value():
    allowed = explain.build_allowed_numbers(SAMPLE_CONTEXT)
    unverified = explain.find_unverified_numbers("RSI는 55.58이고 무려 500% 상승했습니다.", allowed)
    assert 500.0 in unverified


def test_find_unverified_numbers_allows_rounded_citation():
    allowed = explain.build_allowed_numbers(SAMPLE_CONTEXT)
    # 72.18점을 "72점"으로 반올림 인용하는 것은 허용되어야 한다
    assert explain.find_unverified_numbers("총점은 72점입니다.", allowed) == []


def test_validate_text_combines_both_filters():
    allowed = explain.build_allowed_numbers(SAMPLE_CONTEXT)
    violations = explain.validate_text("이미 999% 급등했으므로 매수 추천합니다.", allowed)
    assert len(violations) >= 2  # 금지표현 + 수치불일치 둘 다 잡혀야 한다


# ---------------------------------------------------------------------------
# 코인 개요 파생 필드
# ---------------------------------------------------------------------------

def test_derive_launch_year_parses_genesis_date():
    assert explain.derive_launch_year("2013-04-28") == 2013


def test_derive_launch_year_none_when_missing():
    assert explain.derive_launch_year(None) is None


def test_is_native_chain_coin_true_when_stablecoin_inflow_computed():
    analyzers = {"onchain_growth": {"metrics": {"stablecoin_inflow": {"current": 100.0}}}}
    assert explain.is_native_chain_coin(analyzers) is True


def test_is_native_chain_coin_false_when_not_applicable():
    analyzers = {"onchain_growth": {"metrics": {"stablecoin_inflow": {"status": "not_applicable"}}}}
    assert explain.is_native_chain_coin(analyzers) is False


def test_derive_chain_label_uses_platform_id_when_present():
    snapshot = {"asset_platform_id": "ethereum"}
    assert explain.derive_chain_label(snapshot, {}) == "Ethereum"


def test_derive_chain_label_native_chain_fallback():
    snapshot = {"asset_platform_id": None, "name": "Bitcoin"}
    analyzers = {"onchain_growth": {"metrics": {"stablecoin_inflow": {"current": 1.0}}}}
    assert "Bitcoin" in explain.derive_chain_label(snapshot, analyzers)


def test_derive_chain_label_none_when_unknown():
    snapshot = {"asset_platform_id": None, "name": "Unknown"}
    assert explain.derive_chain_label(snapshot, {}) is None


# ---------------------------------------------------------------------------
# generate_coin_explanation — 3중 필터 + 재생성 로직
# ---------------------------------------------------------------------------

def test_generate_succeeds_on_first_attempt():
    llm = FakeLLMClient([VALID_RESPONSE])
    result = explain.generate_coin_explanation(SAMPLE_CONTEXT, llm, max_content_retries=2)

    for field in explain.CONTENT_FIELDS:
        assert result["fields"][field] is not None
        assert result["field_status"][field]["status"] == "ok"
    assert result["attempts_used"] == 1
    assert len(llm.calls) == 1


def test_generate_retries_after_banned_phrase_then_succeeds():
    bad_response = dict(VALID_RESPONSE, ai_summary="이미 70% 상승했으므로 매수를 추천합니다.")
    llm = FakeLLMClient([bad_response, VALID_RESPONSE])

    result = explain.generate_coin_explanation(SAMPLE_CONTEXT, llm, max_content_retries=2)

    assert result["field_status"]["ai_summary"]["status"] == "ok"
    assert result["fields"]["ai_summary"] == VALID_RESPONSE["ai_summary"]
    assert len(llm.calls) == 2
    # 첫 시도에서 이미 통과한 다른 필드는 그대로 유지된다 (재검증으로 흔들리지 않음)
    assert result["fields"]["one_liner"] == VALID_RESPONSE["one_liner"]


def test_generate_marks_field_failed_after_exhausting_retries():
    bad_response = dict(VALID_RESPONSE, risk_summary="이미 300% 급등해서 매수 적기입니다.")
    llm = FakeLLMClient([bad_response, bad_response, bad_response])

    result = explain.generate_coin_explanation(SAMPLE_CONTEXT, llm, max_content_retries=2)

    assert result["fields"]["risk_summary"] is None
    assert result["field_status"]["risk_summary"]["status"] == "failed_validation"
    assert len(llm.calls) == 3
    # 통과한 다른 필드는 결측되지 않는다
    assert result["fields"]["one_liner"] == VALID_RESPONSE["one_liner"]


def test_generate_handles_llm_unavailable_gracefully():
    from common.llm_client import LLMUnavailableError

    llm = FakeLLMClient([LLMUnavailableError("no api key")])
    result = explain.generate_coin_explanation(SAMPLE_CONTEXT, llm, max_content_retries=2)

    for field in explain.CONTENT_FIELDS:
        assert result["fields"][field] is None
    assert all(s["status"] == "missing" for s in result["field_status"].values())


def test_generate_skips_description_when_no_source_text():
    context = dict(SAMPLE_CONTEXT, description_en=None)
    llm = FakeLLMClient([VALID_RESPONSE])

    result = explain.generate_coin_explanation(context, llm, max_content_retries=2)

    assert result["field_status"]["description_summary"]["status"] == "not_applicable"
    assert result["fields"]["description_summary"] is None


def test_generate_fabricated_number_triggers_retry():
    bad_response = dict(VALID_RESPONSE, leading_evidence_summary="무려 800% 성장했습니다.")
    llm = FakeLLMClient([bad_response, VALID_RESPONSE])

    result = explain.generate_coin_explanation(SAMPLE_CONTEXT, llm, max_content_retries=2)

    assert result["field_status"]["leading_evidence_summary"]["status"] == "ok"
    assert len(llm.calls) == 2


# ---------------------------------------------------------------------------
# explain_top20 오케스트레이션
# ---------------------------------------------------------------------------

def test_explain_top20_builds_per_coin_results():
    ranked_coin = {
        "coin_id": "test-coin", "symbol": "tst", "name": "Test Coin",
        "final_score": 72.18, "base_score": 72.18,
        "confidence": SAMPLE_CONTEXT["confidence"],
        "breakdown": {
            "vpd": SAMPLE_CONTEXT["vpd"], "onchain_growth": SAMPLE_CONTEXT["onchain"],
            "developer": SAMPLE_CONTEXT["developer"], "user_ecosystem": SAMPLE_CONTEXT["user_ecosystem"],
            "catalyst": SAMPLE_CONTEXT["catalyst"], "valuation": SAMPLE_CONTEXT["valuation"],
            "risk": SAMPLE_CONTEXT["risk"],
        },
        "technical": SAMPLE_CONTEXT["technical"], "overheat": SAMPLE_CONTEXT["overheat"],
        "context": {"price_usd": 65000.0, "market_cap_usd": 1_280_000_000_000},
    }
    snapshot = {
        "categories": ["Layer 1 (L1)"], "description_en": "Test Coin is decentralized.",
        "genesis_date": "2013-04-28", "asset_platform_id": None, "name": "Test Coin",
    }
    analyzers = {"onchain_growth": {"metrics": {"stablecoin_inflow": {"current": 1.0}}},
                 "catalyst": {"metrics": {"catalysts": []}}}
    llm = FakeLLMClient([VALID_RESPONSE])

    results = explain.explain_top20([ranked_coin], {"test-coin": analyzers}, {"test-coin": snapshot}, llm)

    assert "test-coin" in results
    entry = results["test-coin"]
    assert entry["fields"]["one_liner"] == VALID_RESPONSE["one_liner"]
    assert entry["overview_facts"]["launch_year"] == 2013
    assert entry["overview_facts"]["chain"] == "Test Coin 자체 메인넷"
    assert entry["catalyst_calendar"]["catalysts"] == []
