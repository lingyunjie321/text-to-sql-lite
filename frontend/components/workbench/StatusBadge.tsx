import {
  CheckCircle,
  HelpCircle,
  XCircle,
  ShieldX,
  Clock,
  WifiOff,
  AlertTriangle,
  ServerCrash,
} from "lucide-react";
import type { FinalStatus } from "@/lib/types";

interface StatusBadgeProps {
  status: FinalStatus;
  subtitle?: string;
}

const statusConfig: Record<
  FinalStatus,
  {
    label: string;
    bgClass: string;
    textClass: string;
    Icon: React.ComponentType<{ className?: string }>;
  }
> = {
  SUCCEEDED_FIRST_PASS: {
    label: "查询成功",
    bgClass: "bg-[var(--color-success-light)]",
    textClass: "text-[var(--color-success)]",
    Icon: CheckCircle,
  },
  SUCCEEDED_REPAIRED: {
    label: "经修复后成功",
    bgClass: "bg-[var(--color-info-light)]",
    textClass: "text-[var(--color-info)]",
    Icon: CheckCircle,
  },
  CLARIFICATION_REQUIRED: {
    label: "需要补充信息",
    bgClass: "bg-[var(--color-warning-light)]",
    textClass: "text-[var(--color-warning)]",
    Icon: HelpCircle,
  },
  REJECTED_SECURITY: {
    label: "安全拒绝",
    bgClass: "bg-[var(--color-error-light)]",
    textClass: "text-[var(--color-error)]",
    Icon: ShieldX,
  },
  FAILED_DUPLICATE_LOOP: {
    label: "查询失败",
    bgClass: "bg-[var(--color-error-light)]",
    textClass: "text-[var(--color-error)]",
    Icon: XCircle,
  },
  FAILED_TIMEOUT: {
    label: "查询超时",
    bgClass: "bg-[var(--color-error-light)]",
    textClass: "text-[var(--color-error)]",
    Icon: Clock,
  },
  FAILED_CONNECTION: {
    label: "连接错误",
    bgClass: "bg-[var(--color-error-light)]",
    textClass: "text-[var(--color-error)]",
    Icon: WifiOff,
  },
  FAILED_RESOURCE_RISK: {
    label: "资源风险",
    bgClass: "bg-orange-50",
    textClass: "text-orange-700",
    Icon: AlertTriangle,
  },
  FAILED_REPAIR_EXHAUSTED: {
    label: "修复失败",
    bgClass: "bg-[var(--color-error-light)]",
    textClass: "text-[var(--color-error)]",
    Icon: XCircle,
  },
  FAILED_INTERNAL: {
    label: "系统错误",
    bgClass: "bg-[var(--color-error-light)]",
    textClass: "text-[var(--color-error)]",
    Icon: ServerCrash,
  },
};

export function StatusBadge({ status, subtitle }: StatusBadgeProps) {
  const config = statusConfig[status];
  const Icon = config.Icon;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span
        className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium ${config.bgClass} ${config.textClass}`}
      >
        <Icon className="h-3.5 w-3.5" />
        {config.label}
      </span>
      {subtitle && (
        <span className="text-xs text-[var(--color-text-tertiary)]">
          {subtitle}
        </span>
      )}
    </div>
  );
}

export function getStatusSubtitle(
  status: FinalStatus,
  response: {
    repair_count?: number;
    returned_row_count?: number;
  },
): string {
  switch (status) {
    case "SUCCEEDED_FIRST_PASS":
      return response.returned_row_count !== undefined
        ? `一次通过 · 返回 ${response.returned_row_count} 行`
        : "一次通过";
    case "SUCCEEDED_REPAIRED":
      return `经 ${response.repair_count || 0} 次修复 · 返回 ${response.returned_row_count || 0} 行`;
    default:
      return "";
  }
}
