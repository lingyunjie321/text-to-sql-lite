"use client";

import { useState, useCallback, useEffect } from "react";
import { Info, Trash2, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { clearDbConfig } from "@/lib/datasource-config";
import { checkBackendHealth } from "@/lib/health";
import {
  clearSelectedModelProfileId,
  removeLegacyModelConfig,
} from "@/lib/profile-selection";

interface AboutSectionProps {
  onToast: (message: string, type?: "success" | "info" | "error") => void;
  onConfigCleared: () => void;
}

export function clearBrowserPreferences(): void {
  clearSelectedModelProfileId();
  removeLegacyModelConfig();
  clearDbConfig();
}

export function AboutSection({ onToast, onConfigCleared }: AboutSectionProps) {
  const [confirming, setConfirming] = useState(false);
  const [healthStatus, setHealthStatus] = useState<{
    healthy: boolean | null;
    message: string;
  }>({ healthy: null, message: "检测中..." });

  useEffect(() => {
    let cancelled = false;
    checkBackendHealth().then((result) => {
      if (!cancelled) {
        setHealthStatus(result);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleClear = useCallback(() => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    clearBrowserPreferences();
    setConfirming(false);
    onToast("浏览器偏好已清除", "success");
    onConfigCleared();
  }, [confirming, onToast, onConfigCleared]);

  return (
    <div>
      <h2 className="text-xl font-semibold text-[var(--color-text-primary)]">
        关于
      </h2>

      {/* App info */}
      <div className="mt-6">
        <label className="mb-2 block text-sm font-medium text-[var(--color-text-secondary)]">
          应用信息
        </label>
        <div className="rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
          <dl className="space-y-2 text-sm">
            <div className="flex gap-2">
              <dt className="w-20 shrink-0 font-medium text-[var(--color-text-tertiary)]">
                应用名称
              </dt>
              <dd className="text-[var(--color-text-secondary)]">
                Text-to-SQL Agent
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-20 shrink-0 font-medium text-[var(--color-text-tertiary)]">
                版本
              </dt>
              <dd className="text-[var(--color-text-secondary)]">v1.0.0</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-20 shrink-0 font-medium text-[var(--color-text-tertiary)]">
                技术栈
              </dt>
              <dd className="text-[var(--color-text-secondary)]">
                Next.js 16 + React 19 + Tailwind CSS 4
              </dd>
            </div>
          </dl>
        </div>
      </div>

      {/* Config storage */}
      <div className="mt-6">
        <label className="mb-2 block text-sm font-medium text-[var(--color-text-secondary)]">
          配置存储
        </label>
        <div className="rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
          <div className="flex items-start gap-2">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-info)]" />
            <div className="text-sm text-[var(--color-text-secondary)]">
              <p>
                模型 Profile 保存在本地后端，API Key 仅保存在当前后端进程内存。
              </p>
              <div className="mt-2 space-y-0.5 text-xs text-[var(--color-text-tertiary)]">
                <p>浏览器仅保存当前模型 Profile ID 和旧数据库演示配置。</p>
                <p>清除浏览器偏好不会删除后端模型 Profile。</p>
              </div>
            </div>
          </div>
          <div className="mt-4">
            {confirming ? (
              <div className="flex items-center gap-3">
                <span className="text-sm text-[var(--color-error)]">
                  确定要清除浏览器偏好吗？后端模型 Profile 会保留。
                </span>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={handleClear}
                >
                  确认清除
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirming(false)}
                >
                  取消
                </Button>
              </div>
            ) : (
              <Button variant="danger" size="sm" onClick={handleClear}>
                <Trash2 className="h-3.5 w-3.5" />
                清除浏览器偏好
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Security warning */}
      <div className="mt-6">
        <label className="mb-2 block text-sm font-medium text-[var(--color-text-secondary)]">
          安全提示
        </label>
        <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            模型 API Key 不保存在浏览器。旧数据库演示配置可能包含数据库密码，
            仍存在 XSS 窃取风险，仅用于当前兼容路径。
          </p>
        </div>
      </div>

      {/* Backend health indicator (Phase 4d) */}
      <div className="mt-6">
        <label className="mb-2 block text-sm font-medium text-[var(--color-text-secondary)]">
          后端状态
        </label>
        <div className="rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
          <div className="flex items-center gap-3">
            <span
              className={`inline-block h-3 w-3 rounded-full ${
                healthStatus.healthy === null
                  ? "bg-gray-400"
                  : healthStatus.healthy
                    ? "bg-green-500"
                    : "bg-red-500"
              }`}
            />
            <span className="text-sm text-[var(--color-text-secondary)]">
              {healthStatus.message}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
