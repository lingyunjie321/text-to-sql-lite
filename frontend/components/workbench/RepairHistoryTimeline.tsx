"use client";

import { useState } from "react";
import { Copy, Check, CheckCircle, XCircle } from "lucide-react";
import type { RepairHistoryEntry } from "@/lib/types";

interface RepairHistoryTimelineProps {
  history: RepairHistoryEntry[];
  finalSuccess: boolean;
}

const errorTypeStyles: Record<string, { bg: string; text: string }> = {
  SYNTAX_ERROR: { bg: "bg-amber-50", text: "text-amber-700" },
  DIALECT_ERROR: { bg: "bg-amber-50", text: "text-amber-700" },
  SCHEMA_ERROR: { bg: "bg-orange-50", text: "text-orange-700" },
  BUSINESS_KNOWLEDGE_MISSING: { bg: "bg-blue-50", text: "text-blue-700" },
  AMBIGUOUS_SEMANTICS: { bg: "bg-blue-50", text: "text-blue-700" },
  CONNECTION_ERROR: { bg: "bg-red-50", text: "text-red-700" },
  TIMEOUT: { bg: "bg-red-50", text: "text-red-700" },
  DUPLICATE_SQL: { bg: "bg-gray-100", text: "text-gray-600" },
  UNKNOWN: { bg: "bg-gray-100", text: "text-gray-600" },
};

function getErrorStyle(errorType: string) {
  return errorTypeStyles[errorType] ?? errorTypeStyles.UNKNOWN;
}

function TimelineEntry({
  entry,
  isLast,
  finalSuccess,
}: {
  entry: RepairHistoryEntry;
  isLast: boolean;
  finalSuccess: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const errStyle = getErrorStyle(entry.error_type);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(entry.fingerprint);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  return (
    <div className="relative flex gap-3 pb-4 last:pb-0">
      {/* Node + connector */}
      <div className="flex flex-col items-center">
        <div className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-[var(--color-warning)]" />
        {!isLast && (
          <div className="mt-1 w-0.5 flex-1 bg-[var(--color-border)]" />
        )}
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-[var(--color-text-primary)]">
          第 {entry.attempt} 次尝试
        </div>
        <div className="mt-1.5 space-y-1.5 rounded-md border border-[var(--color-border)] bg-white p-3">
          <div className="flex items-center gap-2">
            <span className="w-16 shrink-0 text-xs font-medium text-[var(--color-text-tertiary)]">
              错误类型
            </span>
            <span
              className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium font-mono ${errStyle.bg} ${errStyle.text}`}
            >
              {entry.error_type}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-16 shrink-0 text-xs font-medium text-[var(--color-text-tertiary)]">
              修复策略
            </span>
            <span className="text-sm text-[var(--color-text-secondary)]">
              {entry.fix_strategy}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-16 shrink-0 text-xs font-medium text-[var(--color-text-tertiary)]">
              SQL 指纹
            </span>
            <span className="flex-1 truncate font-mono text-sm text-[var(--color-text-secondary)]">
              {entry.fingerprint}
            </span>
            <button
              onClick={handleCopy}
              className="shrink-0 text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]"
              aria-label="复制指纹"
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-[var(--color-success)]" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
        </div>
        {isLast && (
          <div
            className={`mt-2 flex items-center gap-1.5 text-sm font-medium ${
              finalSuccess
                ? "text-[var(--color-success)]"
                : "text-[var(--color-error)]"
            }`}
          >
            {finalSuccess ? (
              <>
                <CheckCircle className="h-4 w-4" />
                最终成功
              </>
            ) : (
              <>
                <XCircle className="h-4 w-4" />
                未能修复
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function RepairHistoryTimeline({
  history,
  finalSuccess,
}: RepairHistoryTimelineProps) {
  const sorted = [...history].sort((a, b) => a.attempt - b.attempt);

  return (
    <div>
      {sorted.map((entry, idx) => (
        <TimelineEntry
          key={`${entry.attempt}-${idx}`}
          entry={entry}
          isLast={idx === sorted.length - 1}
          finalSuccess={finalSuccess}
        />
      ))}
    </div>
  );
}
