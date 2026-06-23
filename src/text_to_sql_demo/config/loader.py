from pathlib import Path
from typing import Any

import yaml

from text_to_sql_demo.config.models import WorkflowConfig


def load_workflow_config(path: str | Path) -> WorkflowConfig:
    """加载并校验 workflow YAML 文件。"""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"未找到 workflow 配置文件: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        raw_config: dict[str, Any] = yaml.safe_load(file) or {}

    return WorkflowConfig.model_validate(raw_config)
