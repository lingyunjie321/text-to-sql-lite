from text_to_sql_demo.llm.client import LLMClient, LLMResponse


class RoutingLLMClient:
    """按模型别名分发请求的 LLM client。

    该类不绑定具体 provider，只负责把请求交给配置好的别名 client。
    """

    def __init__(self, *, clients_by_alias: dict[str, LLMClient]) -> None:
        self.clients_by_alias = dict(clients_by_alias)

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
        """使用 model_alias 对应的底层 client 生成文本。"""

        client = self.clients_by_alias[model_alias]
        return client.complete(
            model_alias=model_alias,
            model_name=model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
