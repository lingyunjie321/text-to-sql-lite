import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import time

import pytest


class RecordingEmbeddingHandler(BaseHTTPRequestHandler):
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
                "model": "embedding-v1",
                "data": [
                    {"index": 1, "embedding": [0, 1, 0]},
                    {"index": 0, "embedding": [1, 0, 0]},
                ],
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args: object) -> None:
        return None


class RedirectingEmbeddingHandler(BaseHTTPRequestHandler):
    redirected_headers: dict[str, str] | None = None

    def do_POST(self) -> None:
        self.send_response(302)
        self.send_header("Location", "/capture")
        self.end_headers()

    def do_GET(self) -> None:
        type(self).redirected_headers = dict(self.headers.items())
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return None


class SlowQueryEmbeddingHandler(BaseHTTPRequestHandler):
    request_count = 0

    def do_POST(self) -> None:
        content_length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(content_length))
        type(self).request_count += 1
        if type(self).request_count == 2:
            time.sleep(0.1)
        response = json.dumps(
            {
                "model": "embedding-v1",
                "data": [
                    {"index": index, "embedding": [1, 0, 0]}
                    for index, _ in enumerate(payload["input"])
                ],
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        try:
            self.wfile.write(response)
        except BrokenPipeError:
            pass

    def log_message(self, *args: object) -> None:
        return None


@pytest.mark.integration
def test_embedding_provider_uses_real_loopback_protocol() -> None:
    from app.config import EmbeddingSettings
    from app.schema_linking.embedding import (
        OpenAICompatibleEmbeddingProvider,
    )

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        RecordingEmbeddingHandler,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = OpenAICompatibleEmbeddingProvider(
            EmbeddingSettings(
                base_url=(
                    f"http://127.0.0.1:{server.server_port}/v1"
                ),
                api_key="local-integration-secret",
                model="embedding-v1",
                dimension=3,
            )
        )

        result = provider.embed(("film", "actor"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result == (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
    )
    assert RecordingEmbeddingHandler.request_path == "/v1/embeddings"
    assert RecordingEmbeddingHandler.request_headers[
        "Authorization"
    ] == "Bearer local-integration-secret"
    assert RecordingEmbeddingHandler.request_payload == {
        "model": "embedding-v1",
        "input": ["film", "actor"],
    }


@pytest.mark.integration
def test_embedding_provider_supports_no_auth_loopback() -> None:
    from app.config import EmbeddingSettings
    from app.schema_linking.embedding import (
        OpenAICompatibleEmbeddingProvider,
    )

    RecordingEmbeddingHandler.request_headers = {}
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        RecordingEmbeddingHandler,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = OpenAICompatibleEmbeddingProvider(
            EmbeddingSettings(
                base_url=(
                    f"http://127.0.0.1:{server.server_port}/v1"
                ),
                api_key=None,
                model="embedding-v1",
                dimension=3,
            )
        )

        result = provider.embed(("film", "actor"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result == ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert "Authorization" not in RecordingEmbeddingHandler.request_headers


@pytest.mark.integration
def test_loopback_embedding_timeout_degrades_to_same_schema_bm25() -> None:
    from app.config import EmbeddingSettings
    from app.connectors.metadata import TableMetadata, build_schema_snapshot
    from app.schema_linking import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
        link_schema,
    )
    from app.schema_linking.embedding import (
        OpenAICompatibleEmbeddingProvider,
    )

    SlowQueryEmbeddingHandler.request_count = 0
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        SlowQueryEmbeddingHandler,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        delegate = OpenAICompatibleEmbeddingProvider(
            EmbeddingSettings(
                base_url=(
                    f"http://127.0.0.1:{server.server_port}/v1"
                ),
                api_key=None,
                model="embedding-v1",
                dimension=3,
            )
        )

        class ShortTimeoutProvider:
            model_id = delegate.model_id
            dimension = delegate.dimension
            provider_config_sha256 = delegate.provider_config_sha256

            def embed(self, texts, *, timeout_seconds=None):  # type: ignore[no-untyped-def]
                del timeout_seconds
                return delegate.embed(texts, timeout_seconds=0.02)

        snapshot = build_schema_snapshot(
            tables=(
                TableMetadata(
                    schema_name="public",
                    table_name="film",
                    relation_kind="table",
                    comment="Available films",
                    columns=(),
                ),
                TableMetadata(
                    schema_name="public",
                    table_name="actor",
                    relation_kind="table",
                    comment="Film actors",
                    columns=(),
                ),
            ),
            primary_keys=(),
            foreign_keys=(),
            unique_constraints=(),
            unique_indexes=(),
        )
        result = link_schema(
            "film",
            datasource_id="local-pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.actor", "public.film"),
            snapshot=snapshot,
            top_k=5,
            retrieval_runtime=RetrievalRuntime(
                provider=ShortTimeoutProvider(),
                registry=EmbeddingIndexRegistry(),
                semantic_version="semantic-v1",
            ),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.schema_version == snapshot.schema_version
    assert result.retrieval_pool is not None
    assert result.retrieval_pool.mode == "bm25_only"
    assert result.retrieval_pool.embedding_degradation == "timeout"
    assert {
        table.object_id for table in result.candidate_tables
    }.issubset({"public.actor", "public.film"})


@pytest.mark.integration
def test_embedding_provider_rejects_redirect_without_forwarding_key() -> None:
    from app.config import EmbeddingSettings
    from app.schema_linking.embedding import (
        EmbeddingProviderError,
        OpenAICompatibleEmbeddingProvider,
    )

    RedirectingEmbeddingHandler.redirected_headers = None
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        RedirectingEmbeddingHandler,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = OpenAICompatibleEmbeddingProvider(
            EmbeddingSettings(
                base_url=(
                    f"http://127.0.0.1:{server.server_port}/v1"
                ),
                api_key="local-integration-secret",
                model="embedding-v1",
                dimension=3,
            )
        )

        with pytest.raises(EmbeddingProviderError) as captured:
            provider.embed(("film",))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert captured.value.details.code == "EMBEDDING_HTTP_ERROR"
    assert RedirectingEmbeddingHandler.redirected_headers is None
