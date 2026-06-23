import json
from urllib import request

from text_to_sql_demo.llm.client import LLMResponse


class OpenAICompatibleLLMClient:
    """OpenAI-compatible Chat Completions provider adapter.

    该类只在被显式实例化和调用时访问外部服务；测试默认使用 MockLLMClient。
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1/chat/completions",
        timeout_seconds: int = 30,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

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
        payload: dict[str, object] = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        http_request = request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))

        text = raw["choices"][0]["message"]["content"]
        return LLMResponse(
            text=text,
            model_alias=model_alias,
            provider_name="openai_compatible",
            raw_id=raw.get("id"),
            usage=raw.get("usage"),
        )
