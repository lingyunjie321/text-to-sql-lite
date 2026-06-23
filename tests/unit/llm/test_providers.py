import json
from urllib.request import Request

import pytest

from text_to_sql_demo.llm.providers import OpenAICompatibleLLMClient


class FakeResponse:
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "id": "chatcmpl-test",
                "choices": [{"message": {"content": "SELECT 1;"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            }
        ).encode("utf-8")


def test_openai_compatible_client_sends_chat_completion_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: int) -> FakeResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8") if request.data else "{}")
        return FakeResponse()

    monkeypatch.setattr("text_to_sql_demo.llm.providers.request.urlopen", fake_urlopen)
    client = OpenAICompatibleLLMClient(
        api_key="test-secret-key",
        base_url="https://example.test/v1/chat/completions",
        timeout_seconds=12,
    )

    response = client.complete(
        model_alias="light",
        model_name="demo-model",
        system_prompt="system",
        user_prompt="user",
        temperature=0.2,
        max_tokens=128,
    )

    assert response.text == "SELECT 1;"
    assert response.model_alias == "light"
    assert response.provider_name == "openai_compatible"
    assert response.raw_id == "chatcmpl-test"
    assert response.usage == {"prompt_tokens": 10, "completion_tokens": 3}
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["timeout"] == 12
    assert captured["headers"] == {
        "Authorization": "Bearer test-secret-key",
        "Content-type": "application/json",
    }
    assert captured["body"] == {
        "model": "demo-model",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ],
        "temperature": 0.2,
        "max_tokens": 128,
    }
