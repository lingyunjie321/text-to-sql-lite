"use client";

import { Zap, Activity, Flame } from "lucide-react";
import type { ComplexityRoute } from "@/lib/types";

interface ComplexityRoutePanelProps {
  route: ComplexityRoute;
}

const levelConfig: Record<
  ComplexityRoute["level"],
  { label: string; bg: string; text: string; Icon: typeof Zap }
> = {
  simple: {
    label: "简单",
    bg: "bg-[var(--color-success-light)]",
    text: "text-[var(--color-success)]",
    Icon: Zap,
  },
  standard: {
    label: "标准",
    bg: "bg-blue-50",
    text: "text-blue-700",
    Icon: Activity,
  },
  complex: {
    label: "复杂",
    bg: "bg-orange-50",
    text: "text-orange-700",
    Icon: Flame,
  },
};

export function ComplexityRoutePanel({ route }: ComplexityRoutePanelProps) {
  const cfg = levelConfig[route.level] ?? levelConfig.standard;
  const { Icon } = cfg;

  return (
    <div className="rounded-md border border-[var(--color-border)] bg-white p-3">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium ${cfg.bg} ${cfg.text}`}
        >
          <Icon className="h-3.5 w-3.5" />
          {cfg.label}
        </span>
        <span className="text-sm text-[var(--color-text-secondary)]">
          Top-K:{" "}
          <span className="font-mono font-medium text-[var(--color-text-primary)]">
            {route.top_k}
          </span>
        </span>
        <span className="text-sm text-[var(--color-text-secondary)]">
          模型:{" "}
          <span className="font-mono text-[var(--color-text-primary)]">
            {route.model_used || "—"}
          </span>
        </span>
      </div>
      {route.reason && (
        <p className="mt-2 text-sm leading-relaxed text-[var(--color-text-secondary)]">
          {route.reason}
        </p>
      )}
    </div>
  );
}
