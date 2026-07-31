"use client";

import { useState, useCallback } from "react";
import { Info, Trash2, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { clearModelConfig } from "@/lib/model-config";
import { clearDbConfig } from "@/lib/datasource-config";

interface AboutSectionProps {
  onToast: (message: string, type?: "success" | "info" | "error") => void;
  onConfigCleared: () => void;
}

export function AboutSection({ onToast, onConfigCleared }: AboutSectionProps) {
  const [confirming, setConfirming] = useState(false);

  const handleClear = useCallback(() => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    clearModelConfig();
    clearDbConfig();
    setConfirming(false);
    onToast("所有配置已清除", "success");
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
                当前配置存储在浏览器 localStorage 中，仅适用于演示。清除浏览器数据会导致配置丢失。
              </p>
              <div className="mt-2 space-y-0.5 text-xs text-[var(--color-text-tertiary)]">
                <p>存储位置：</p>
                <p>• 模型配置：localStorage[&quot;text-to-sql-model-config&quot;]</p>
                <p>• 数据库配置：localStorage[&quot;text-to-sql-db-config&quot;]</p>
              </div>
            </div>
          </div>
          <div className="mt-4">
            {confirming ? (
              <div className="flex items-center gap-3">
                <span className="text-sm text-[var(--color-error)]">
                  确定要清除所有配置吗？此操作不可撤销。
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
                清除所有配置
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
            API Key 和数据库密码存储在 localStorage 中，存在 XSS
            窃取风险。生产环境请使用后端加密存储。
          </p>
        </div>
      </div>
    </div>
  );
}
