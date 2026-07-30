from app.generation import (
    LLMProvider,
    ModelRoutingRuntime,
    build_single_provider_routing_runtime,
)

TEST_MODEL_CONFIG_SHA256 = "9" * 64


def single_provider_test_routing(
    provider: LLMProvider,
    *,
    max_input_tokens: int = 32_768,
    max_output_tokens: int = 2_048,
    timeout_seconds: float = 30,
) -> ModelRoutingRuntime:
    return build_single_provider_routing_runtime(
        provider=provider,
        model_config_sha256_value=(
            TEST_MODEL_CONFIG_SHA256
        ),
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        data_boundary_id="test-boundary-v1",
        provider_key="test-provider",
    )
