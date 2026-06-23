from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from text_to_sql_demo.exceptions import ConfigurationError


class PromptTemplate(BaseModel):
    """可配置 prompt 模板，按 system/user 两段渲染。"""

    system: str
    user: str


class PromptTemplateRenderer:
    """加载 YAML prompt 模板，并用轻量占位符渲染上下文。"""

    def __init__(self, template: PromptTemplate) -> None:
        self.template = template

    @classmethod
    def from_path(cls, path: str | Path) -> PromptTemplateRenderer:
        """从文件系统读取 prompt 模板。"""
        template_path = resolve_prompt_template_path(path)
        with template_path.open("r", encoding="utf-8") as file:
            raw_template = yaml.safe_load(file) or {}
        return cls(PromptTemplate.model_validate(raw_template))

    def render(self, context: dict[str, Any]) -> PromptTemplate:
        """渲染 system/user 两段 prompt。"""
        rendered_context = {
            key: _stringify_prompt_value(value)
            for key, value in context.items()
        }
        return PromptTemplate(
            system=_render_text(self.template.system, rendered_context),
            user=_render_text(self.template.user, rendered_context),
        )


def resolve_prompt_template_path(path: str | Path) -> Path:
    """解析模板路径，支持直接路径或 configs/prompts 下的短文件名。"""
    raw_path = Path(path)
    candidates = [
        raw_path,
        Path.cwd() / raw_path,
        Path.cwd() / "configs" / "prompts" / raw_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ConfigurationError(f"prompt 模板不存在: {path}")


def _render_text(template: str, context: dict[str, str]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", value)
    return rendered


def _stringify_prompt_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, int | float | bool):
        return str(value)
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()
