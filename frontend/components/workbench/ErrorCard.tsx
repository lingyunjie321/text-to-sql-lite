"use client";

import { Button } from "@/components/ui/Button";
import { StatusBadge } from "./StatusBadge";
import { MetaInfo } from "./MetaInfo";
import type { FinalStatus, QueryResponse } from "@/lib/types";

interface ErrorCardProps {
  response: QueryResponse;
  onRetry: () => void;
  onModifyQuestion: () => void;
}

interface ErrorDisplay {
  title: string;
  message: string;
  retryable: boolean;
}

function getErrorDisplay(response: QueryResponse): ErrorDisplay {
  const errorCode = response.error?.code;
  const status = response.status;

  // Handle FAILED_INTERNAL with specific error codes (mainly BFF proxy errors)
  if (status === "FAILED_INTERNAL" && errorCode) {
    switch (errorCode) {
      case "BACKEND_NOT_CONFIGURED":
        return {
          title: "后端服务未配置",
          message:
            "线上环境尚未配置后端 Text-to-SQL API 地址（TEXT_TO_SQL_API_URL）。当前为前端演示模式，仅 UI 可正常浏览，API 调用会被拦截。请联系管理员在 EdgeOne Makers 控制台配置环境变量。",
          retryable: false,
        };
      case "BACKEND_UNREACHABLE":
        return {
          title: "无法连接到后端服务",
          message:
            "后端 API 地址已配置，但服务暂时不可达。请稍后重试，或联系管理员检查后端服务运行状态。",
          retryable: true,
        };
      case "RESPONSE_PARSE_ERROR":
        return {
          title: "后端响应格式异常",
          message:
            "无法解析后端返回的数据。请稍后重试，如问题持续请联系管理员。",
          retryable: true,
        };
    }
  }

  switch (status) {
    case "REJECTED_SECURITY":
      return {
        title: "该查询因安全策略被拒绝",
        message:
          "请尝试调整问题的范围或表述。某些敏感操作或数据范围可能受到限制。",
        retryable: false,
      };
    case "FAILED_TIMEOUT":
      return {
        title: "查询超时",
        message:
          "数据库可能正在处理大量数据。请尝试缩小查询范围后重试，例如增加时间范围限制或减少关联表。",
        retryable: true,
      };
    case "FAILED_CONNECTION":
      return {
        title: "无法连接到数据库",
        message: "数据库连接出现问题，请稍后重试。",
        retryable: true,
      };
    case "FAILED_RESOURCE_RISK":
      return {
        title: "查询可能消耗过多资源",
        message:
          "请尝试缩小范围，例如增加时间范围限制、减少关联表或限制返回行数。",
        retryable: false,
      };
    case "FAILED_DUPLICATE_LOOP":
      return {
        title: "系统多次生成了相同的 SQL 但未能成功执行",
        message: "请尝试换一种方式描述你的问题。",
        retryable: false,
      };
    case "FAILED_REPAIR_EXHAUSTED":
      return {
        title: "系统尝试修复 SQL 但未能成功",
        message:
          "请尝试更清晰地描述你的问题，例如明确指定要查询的表和字段、提供更具体的时间范围或条件。",
        retryable: false,
      };
    case "FAILED_INTERNAL":
      return {
        title: "系统遇到内部错误",
        message: "请稍后重试。如果问题持续，请联系管理员。",
        retryable: true,
      };
    default:
      return {
        title: "查询失败",
        message: "发生未知错误，请稍后重试。",
        retryable: true,
      };
  }
}

export function ErrorCard({
  response,
  onRetry,
  onModifyQuestion,
}: ErrorCardProps) {
  const display = getErrorDisplay(response);

  return (
    <div className="animate-fade-in rounded-lg border border-[var(--color-border)] bg-white shadow-sm">
      {/* Status header */}
      <div className="flex items-center justify-between px-4 py-3">
        <StatusBadge status={response.status} />
      </div>

      {/* Error message */}
      <div className="border-t border-[var(--color-border)] px-4 py-4">
        <p className="text-sm font-medium text-[var(--color-text-primary)]">
          {display.title}
        </p>
        <p className="mt-1.5 text-sm text-[var(--color-text-secondary)]">
          {display.message}
        </p>

        {/* Action buttons */}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" size="md" onClick={onModifyQuestion}>
            修改问题
          </Button>
          {display.retryable && (
            <Button variant="primary" size="md" onClick={onRetry}>
              重试
            </Button>
          )}
        </div>
      </div>

      {/* Meta info */}
      <MetaInfo response={response} />
    </div>
  );
}
