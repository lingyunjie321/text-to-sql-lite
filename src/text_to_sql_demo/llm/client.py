from typing import Any, Protocol

from pydantic import BaseModel


class LLMRequest(BaseModel):
    """Provider 无关的 LLM 请求。"""

    model_alias: str
    model_name: str
    system_prompt: str
    user_prompt: str
    temperature: float = 0.0
    max_tokens: int | None = None


class LLMResponse(BaseModel):
    """Provider 无关的 LLM 响应。"""

    text: str
    model_alias: str
    provider_name: str
    raw_id: str | None = None
    usage: dict[str, Any] | None = None


class LLMClient(Protocol):
    """所有 LLM provider adapter 必须实现的接口。"""

    def complete(
        self,
        *,
        model_alias: str,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """根据 prompt 生成文本。"""


class MockLLMClient:
    """测试用确定性 LLM client。"""

    def __init__(
        self,
        *,
        responses: dict[str, str | list[str]] | None = None,
        sequence: list[str] | None = None,
        default_response: str = "SELECT 1;",
    ) -> None:
        self.responses = responses or {}
        self.sequence = list(sequence or [])
        self.default_response = default_response
        self.requests: list[LLMRequest] = []
        self._sequence_index = 0
        self._alias_indexes: dict[str, int] = {}

    def complete(
        self,
        *,
        model_alias: str,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        request = LLMRequest(
            model_alias=model_alias,
            model_name=model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.requests.append(request)
        response_text = self._next_text(model_alias)
        return LLMResponse(
            text=response_text,
            model_alias=model_alias,
            provider_name="mock",
        )

    def _next_text(self, model_alias: str) -> str:
        if self.sequence:
            index = min(self._sequence_index, len(self.sequence) - 1)
            self._sequence_index += 1
            return self.sequence[index]

        configured_response = self.responses.get(model_alias, self.default_response)
        if isinstance(configured_response, list):
            index = min(self._alias_indexes.get(model_alias, 0), len(configured_response) - 1)
            self._alias_indexes[model_alias] = index + 1
            return configured_response[index]
        return configured_response
