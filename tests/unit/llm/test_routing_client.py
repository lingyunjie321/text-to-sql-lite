import pytest

from text_to_sql_demo.llm import MockLLMClient, RoutingLLMClient


def test_routing_client_dispatches_light_and_strong_to_separate_clients() -> None:
    light_client = MockLLMClient(responses={"light": "SELECT 1;"})
    strong_client = MockLLMClient(responses={"strong": "SELECT COUNT(*) FROM orders;"})
    client = RoutingLLMClient(
        clients_by_alias={
            "light": light_client,
            "strong": strong_client,
        }
    )

    light_response = client.complete(
        model_alias="light",
        model_name="light-model",
        system_prompt="light system",
        user_prompt="light user",
        temperature=0.1,
        max_tokens=128,
    )
    strong_response = client.complete(
        model_alias="strong",
        model_name="strong-model",
        system_prompt="strong system",
        user_prompt="strong user",
        temperature=0.2,
        max_tokens=256,
    )

    assert light_response.text == "SELECT 1;"
    assert strong_response.text == "SELECT COUNT(*) FROM orders;"
    assert len(light_client.requests) == 1
    assert len(strong_client.requests) == 1
    assert light_client.requests[0].model_alias == "light"
    assert light_client.requests[0].model_name == "light-model"
    assert light_client.requests[0].system_prompt == "light system"
    assert light_client.requests[0].user_prompt == "light user"
    assert light_client.requests[0].temperature == 0.1
    assert light_client.requests[0].max_tokens == 128
    assert strong_client.requests[0].model_alias == "strong"
    assert strong_client.requests[0].model_name == "strong-model"
    assert strong_client.requests[0].system_prompt == "strong system"
    assert strong_client.requests[0].user_prompt == "strong user"
    assert strong_client.requests[0].temperature == 0.2
    assert strong_client.requests[0].max_tokens == 256


def test_routing_client_unknown_alias_raises_key_error_containing_alias() -> None:
    client = RoutingLLMClient(clients_by_alias={"light": MockLLMClient()})

    with pytest.raises(KeyError) as exc_info:
        client.complete(
            model_alias="strong",
            model_name="strong-model",
            system_prompt="system",
            user_prompt="user",
        )

    assert "strong" in str(exc_info.value)
