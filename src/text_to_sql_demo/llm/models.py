from pydantic import BaseModel, Field


class ModelProfile(BaseModel):
    """通过逻辑 alias 引用的模型配置。"""

    alias: str
    provider: str
    model_name: str
    temperature: float = 0.0
    max_tokens: int | None = Field(default=None, gt=0)
