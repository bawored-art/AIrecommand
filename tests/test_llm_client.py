import pytest

from common.llm_client import LLMClient, LLMProvider, LLMUnavailableError


class FakeProvider(LLMProvider):
    """queue에 넣어둔 응답(또는 예외)을 순서대로 반환하는 테스트용 provider."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call(self, system_prompt, user_prompt, max_tokens):
        self.calls.append((system_prompt, user_prompt, max_tokens))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_classify_batch_empty_items_returns_empty_list_without_provider():
    client = LLMClient(provider=None, enabled=True)
    assert client.classify_batch("sys", [], "hint") == []


def test_classify_batch_raises_when_disabled():
    client = LLMClient(provider=FakeProvider(["[]"]), enabled=False)
    with pytest.raises(LLMUnavailableError):
        client.classify_batch("sys", [{"a": 1}], "hint")


def test_classify_batch_raises_when_no_provider():
    client = LLMClient(provider=None, enabled=True)
    with pytest.raises(LLMUnavailableError):
        client.classify_batch("sys", [{"a": 1}], "hint")


def test_classify_batch_parses_matching_length_response():
    client = LLMClient(provider=FakeProvider(['[{"label": "positive"}]']), max_retries=1)

    result = client.classify_batch("sys", [{"headline": "..."}], "hint")

    assert result == [{"label": "positive"}]


def test_classify_batch_returns_none_on_length_mismatch():
    client = LLMClient(provider=FakeProvider(['[{"label": "positive"}, {"label": "negative"}]']), max_retries=1)

    result = client.classify_batch("sys", [{"headline": "..."}], "hint")

    assert result is None


def test_classify_batch_retries_on_transient_failure_then_succeeds():
    provider = FakeProvider([RuntimeError("network blip"), '[{"label": "positive"}]'])
    client = LLMClient(provider=provider, max_retries=2)

    result = client.classify_batch("sys", [{"headline": "..."}], "hint")

    assert result == [{"label": "positive"}]
    assert len(provider.calls) == 2


def test_generate_json_returns_parsed_object():
    client = LLMClient(provider=FakeProvider(['{"summary": "ok"}']), max_retries=1)

    result = client.generate_json("sys", "user prompt")

    assert result == {"summary": "ok"}


def test_generate_json_raises_after_exhausting_retries():
    provider = FakeProvider([RuntimeError("boom"), RuntimeError("boom again")])
    client = LLMClient(provider=provider, max_retries=2)

    with pytest.raises(LLMUnavailableError):
        client.generate_json("sys", "user prompt")


def test_call_budget_exhausted_raises_before_calling_provider():
    provider = FakeProvider(['{"a": 1}', '{"a": 2}'])
    client = LLMClient(provider=provider, max_retries=1, max_calls_per_run=1)

    assert client.generate_json("sys", "u1") == {"a": 1}
    with pytest.raises(LLMUnavailableError):
        client.generate_json("sys", "u2")
    assert len(provider.calls) == 1
