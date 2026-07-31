"use client";

import { useState, useCallback } from "react";
import { Zap, Activity, Flame, LifeBuoy, RotateCcw, Save, Plug } from "lucide-react";
import { ToggleSwitch } from "./ToggleSwitch";
import { PasswordInput } from "./PasswordInput";
import { Button } from "@/components/ui/Button";
import type { StoredModelConfig, ModelEndpoint, ModelTier } from "@/lib/types";
import { getDefaultModelConfig, getModelConfig, setModelConfig } from "@/lib/model-config";

interface ModelConfigSectionProps {
  onToast: (message: string, type?: "success" | "info" | "error") => void;
}

const tierConfig: Record<
  ModelTier,
  {
    label: string;
    description: string;
    Icon: typeof Zap;
    iconColor: string;
  }
> = {
  simple: {
    label: "轻量模型 (Simple)",
    description: "适用于简单查询，快速响应",
    Icon: Zap,
    iconColor: "text-[var(--color-success)]",
  },
  standard: {
    label: "标准模型 (Standard)",
    description: "适用于常规查询，平衡速度与质量",
    Icon: Activity,
    iconColor: "text-[var(--color-info)]",
  },
  complex: {
    label: "高强度模型 (Complex)",
    description: "适用于复杂查询，最强推理能力",
    Icon: Flame,
    iconColor: "text-orange-600",
  },
  fallback: {
    label: "Fallback 模型（可选）",
    description: "主模型不可用时自动降级使用",
    Icon: LifeBuoy,
    iconColor: "text-[var(--color-text-tertiary)]",
  },
};

const tierOrder: ModelTier[] = ["simple", "standard", "complex", "fallback"];

function ModelCard({
  tier,
  endpoint,
  onChange,
  onTest,
}: {
  tier: ModelTier;
  endpoint: ModelEndpoint;
  onChange: (endpoint: ModelEndpoint) => void;
  onTest: () => void;
}) {
  const cfg = tierConfig[tier];
  const { Icon } = cfg;
  const disabled = !endpoint.enabled;

  return (
    <div
      className={`rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm transition-opacity duration-200 ${
        disabled ? "opacity-60" : ""
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className={`h-5 w-5 ${cfg.iconColor}`} />
          <span className="text-base font-semibold text-[var(--color-text-primary)]">
            {cfg.label}
          </span>
        </div>
        <ToggleSwitch
          checked={endpoint.enabled}
          onChange={(checked) => onChange({ ...endpoint, enabled: checked })}
          ariaLabel={`启用${cfg.label}`}
        />
      </div>
      <p className="mt-1 text-sm text-[var(--color-text-tertiary)]">
        {cfg.description}
      </p>

      {/* Divider */}
      <div className="my-4 border-t border-[var(--color-border)]" />

      {/* Fields */}
      <div className="space-y-3">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
            Base URL
          </label>
          <input
            type="url"
            value={endpoint.base_url}
            onChange={(e) => onChange({ ...endpoint, base_url: e.target.value })}
            placeholder="https://api.openai.com/v1"
            disabled={disabled}
            className="h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 disabled:cursor-not-allowed disabled:bg-[var(--color-bg-muted)]"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
            API Key
          </label>
          <PasswordInput
            value={endpoint.api_key}
            onChange={(api_key) => onChange({ ...endpoint, api_key })}
            disabled={disabled}
          />
        </div>
        <div>
          <label className="mb-1.5 block text-sm font-medium text-[var(--color-text-secondary)]">
            Model Name
          </label>
          <input
            type="text"
            value={endpoint.model_name}
            onChange={(e) => onChange({ ...endpoint, model_name: e.target.value })}
            placeholder="gpt-4o-mini"
            disabled={disabled}
            className="h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 disabled:cursor-not-allowed disabled:bg-[var(--color-bg-muted)]"
          />
        </div>
      </div>

      {/* Test button */}
      <div className="mt-4 flex justify-end">
        <Button
          variant="secondary"
          size="sm"
          onClick={onTest}
          disabled={disabled}
        >
          <Plug className="h-3.5 w-3.5" />
          测试连接
        </Button>
      </div>
    </div>
  );
}

export function ModelConfigSection({ onToast }: ModelConfigSectionProps) {
  const [config, setConfig] = useState<StoredModelConfig>(() => getModelConfig());

  const handleEndpointChange = useCallback(
    (tier: ModelTier, endpoint: ModelEndpoint) => {
      setConfig((prev) => ({
        ...prev,
        models: {
          ...prev.models,
          [tier]: endpoint,
        },
      }));
    },
    [],
  );

  const handleTest = useCallback(() => {
    onToast("此功能需要后端支持，暂不可用", "info");
  }, [onToast]);

  const validateConfig = (cfg: StoredModelConfig): string | null => {
    for (const tier of tierOrder) {
      const ep = cfg.models[tier];
      if (!ep.enabled) continue;
      if (!ep.base_url.trim()) return `${tierConfig[tier].label}: Base URL 不能为空`;
      try {
        new URL(ep.base_url);
      } catch {
        return `${tierConfig[tier].label}: Base URL 格式不合法`;
      }
      if (!ep.api_key.trim()) return `${tierConfig[tier].label}: API Key 不能为空`;
      if (!ep.model_name.trim()) return `${tierConfig[tier].label}: Model Name 不能为空`;
    }
    return null;
  };

  const handleSave = useCallback(() => {
    const error = validateConfig(config);
    if (error) {
      onToast(error, "error");
      return;
    }
    setModelConfig(config);
    onToast("配置已保存", "success");
  }, [config, onToast]);

  const handleReset = useCallback(() => {
    setConfig(getDefaultModelConfig());
    onToast("已重置为默认值，请点击保存以生效", "info");
  }, [onToast]);

  return (
    <div>
      <h2 className="text-xl font-semibold text-[var(--color-text-primary)]">
        模型配置
      </h2>
      <p className="mt-1 text-sm text-[var(--color-text-tertiary)]">
        配置 Text-to-SQL Agent 使用的 LLM 模型
      </p>

      <div className="mt-6 space-y-4">
        {tierOrder.map((tier) => (
          <ModelCard
            key={tier}
            tier={tier}
            endpoint={config.models[tier]}
            onChange={(ep) => handleEndpointChange(tier, ep)}
            onTest={handleTest}
          />
        ))}
      </div>

      {/* Action buttons */}
      <div className="mt-6 flex justify-end gap-3">
        <Button variant="secondary" onClick={handleReset}>
          <RotateCcw className="h-4 w-4" />
          重置默认
        </Button>
        <Button onClick={handleSave}>
          <Save className="h-4 w-4" />
          保存配置
        </Button>
      </div>
    </div>
  );
}
