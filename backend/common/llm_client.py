import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """LLM 호출이 불가능하거나 신뢰할 수 없을 때 발생 (비활성화 / provider 없음 / 예산 초과 / 응답 파싱 실패).

    이 예외를 잡은 호출측은 절대 값을 추정하지 말고 결과를 null로, data_quality에 사유를 남긴다.
    """


class LLMProvider(ABC):
    """LLM 벤더 교체를 위한 추상 인터페이스. 새 provider는 call()만 구현하면 LLMClient가 그대로 재사용한다."""

    @abstractmethod
    def call(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        """원시 텍스트 응답을 반환한다. 실패 시 예외를 던진다 (재시도/래핑은 LLMClient가 담당)."""
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API 기반 provider. SDK는 실제 호출 시점에 지연 import한다."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def call(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        client = self._get_client()
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if hasattr(block, "text"))


class LLMClient:
    """provider를 주입받아 배치 분류/단건 생성 + 재시도 + 호출 예산을 제공하는 상위 레이어.

    Catalyst/News/Risk(Stage2)는 classify_batch를, Reason Generator(Stage4)는 generate_json을 쓴다.
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        max_retries: int = 3,
        enabled: bool = True,
        max_calls_per_run: Optional[int] = None,
    ):
        self.provider = provider
        self.max_retries = max_retries
        self.enabled = enabled
        self.max_calls_per_run = max_calls_per_run
        self.calls_made = 0

    def _ensure_usable(self) -> None:
        if not self.enabled:
            raise LLMUnavailableError("llm disabled in config")
        if self.provider is None:
            raise LLMUnavailableError("no LLM provider configured (missing API key or SDK)")
        if self.max_calls_per_run is not None and self.calls_made >= self.max_calls_per_run:
            raise LLMUnavailableError(f"llm call budget exceeded (max_calls_per_run={self.max_calls_per_run})")

    def classify_batch(self, system_prompt: str, items: list, schema_hint: str) -> Optional[list]:
        """items 각각에 대해 한 번의 배치 요청으로 구조화된 JSON 배열 결과를 받는다.

        응답 길이가 items 길이와 다르면 오귀속(잘못된 인덱스 매칭) 위험이 있으므로
        None을 반환해 호출측이 전체를 결측 처리하도록 한다 — 부분 추정은 하지 않는다.
        """
        if not items:
            return []

        self._ensure_usable()
        user_prompt = (
            f"{schema_hint}\n\n"
            f"다음은 분석할 {len(items)}개 항목이다 (0부터 시작하는 인덱스 순서를 반드시 그대로 유지할 것):\n"
            + json.dumps(items, ensure_ascii=False, indent=2)
        )

        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self.calls_made += 1
                text = self.provider.call(system_prompt, user_prompt, max_tokens=4096)
                parsed = json.loads(_extract_json_array(text))
                if len(parsed) != len(items):
                    logger.warning("llm: response length %d != items length %d", len(parsed), len(items))
                    return None
                return parsed
            except Exception as exc:  # LLM SDK/파싱은 다양한 방식으로 실패할 수 있어 광범위하게 재시도
                last_exc = exc
                logger.warning("llm: batch classify attempt %d/%d failed: %s", attempt, self.max_retries, exc)

        raise LLMUnavailableError(f"llm batch classify failed after {self.max_retries} attempts") from last_exc

    def generate_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 2000) -> dict:
        """단일 프롬프트로 구조화된 JSON 객체 하나를 생성한다 (배열이 아닌 dict 하나)."""
        self._ensure_usable()

        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self.calls_made += 1
                text = self.provider.call(system_prompt, user_prompt, max_tokens=max_tokens)
                return json.loads(_extract_json_object(text))
            except Exception as exc:
                last_exc = exc
                logger.warning("llm: generate_json attempt %d/%d failed: %s", attempt, self.max_retries, exc)

        raise LLMUnavailableError(f"llm generate_json failed after {self.max_retries} attempts") from last_exc


def _extract_json_array(text: str) -> str:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON array found in LLM response")
    return text[start : end + 1]


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in LLM response")
    return text[start : end + 1]


def build_llm_client(config: dict, max_calls_per_run: Optional[int] = None) -> LLMClient:
    """config["llm"]으로 LLMClient를 만든다.

    max_calls_per_run을 명시하면 config 값 대신 이를 사용한다 (스테이지별로 다른 예산을 두기 위함,
    예: Stage2 analyze는 무제한, Stage4 explain은 Top20 크기에 맞춘 상한).
    """
    llm_cfg = config.get("llm", {})
    api_key = os.getenv(llm_cfg.get("api_key_env", "ANTHROPIC_API_KEY"))
    enabled = llm_cfg.get("enabled", True)

    provider = None
    if enabled and api_key:
        try:
            import anthropic  # noqa: F401 — 설치 여부만 확인, 실제 사용은 AnthropicProvider가 지연 import
        except ImportError:
            logger.warning("llm: anthropic SDK가 설치되어 있지 않아 LLM 기능이 비활성화됩니다.")
        else:
            provider = AnthropicProvider(api_key=api_key, model=llm_cfg.get("model", "claude-sonnet-5"))

    budget = max_calls_per_run if max_calls_per_run is not None else llm_cfg.get("max_calls_per_run")
    return LLMClient(
        provider=provider,
        max_retries=llm_cfg.get("max_retries", 3),
        enabled=enabled,
        max_calls_per_run=budget,
    )
