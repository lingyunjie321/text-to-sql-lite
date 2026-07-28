import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from app.config import LLMSettings
from app.generation import (
    LLMMessage,
    LLMProviderError,
    OpenAICompatibleLLMProvider,
)


class RecordingHandler(BaseHTTPRequestHandler):
    request_path = ""
    request_headers: dict[str, str] = {}
    request_payload: dict[str, object] = {}

    def do_POST(self) -> None:
        content_length = int(self.headers["Content-Length"])
        type(self).request_path = self.path
        type(self).request_headers = dict(self.headers.items())
        type(self).request_payload = json.loads(
            self.rfile.read(content_length)
        )
        response = json.dumps(
            {
                "model": "local-compatible-model",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "sql": "SELECT 1",
                                    "clarification_reason": None,
                                }
                            ),
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                },
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args: object) -> None:
        return None


class RedirectingHandler(BaseHTTPRequestHandler):
    redirected_request_headers: dict[str, str] | None = None

    def do_POST(self) -> None:
        self.send_response(302)
        self.send_header("Location", "/capture")
        self.end_headers()

    def do_GET(self) -> None:
        type(self).redirected_request_headers = dict(
            self.headers.items()
        )
        response = json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps({"sql": "SELECT 1"})
                        }
                    }
                ]
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args: object) -> None:
        return None


@pytest.mark.integration
def test_provider_uses_real_openai_compatible_http_protocol() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = LLMSettings(
            base_url=(
                f"http://127.0.0.1:{server.server_port}/v1"
            ),
            api_key="local-integration-secret",
            model="local-compatible-model",
        )
        provider = OpenAICompatibleLLMProvider(settings)

        result = provider.generate(
            (
                LLMMessage(role="system", content="system"),
                LLMMessage(role="user", content="user"),
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.output.sql == "SELECT 1"
    assert result.input_tokens == 7
    assert result.output_tokens == 3
    assert RecordingHandler.request_path == "/v1/chat/completions"
    assert RecordingHandler.request_headers["Authorization"] == (
        "Bearer local-integration-secret"
    )
    assert RecordingHandler.request_payload["model"] == (
        "local-compatible-model"
    )
    assert RecordingHandler.request_payload["temperature"] == 0
    assert RecordingHandler.request_payload["response_format"] == {
        "type": "json_object"
    }


@pytest.mark.integration
def test_provider_rejects_redirects_without_forwarding_authorization() -> None:
    RedirectingHandler.redirected_request_headers = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectingHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = LLMSettings(
            base_url=(
                f"http://127.0.0.1:{server.server_port}/v1"
            ),
            api_key="local-integration-secret",
            model="local-compatible-model",
        )
        provider = OpenAICompatibleLLMProvider(settings)

        with pytest.raises(LLMProviderError) as captured:
            provider.generate(
                (
                    LLMMessage(role="system", content="system"),
                    LLMMessage(role="user", content="user"),
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert captured.value.details.code == "LLM_HTTP_ERROR"
    assert RedirectingHandler.redirected_request_headers is None
