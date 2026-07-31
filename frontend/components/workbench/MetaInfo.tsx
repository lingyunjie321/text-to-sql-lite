"use client";

import { useState } from "react";
import { ChevronRight, Copy, Check } from "lucide-react";
import type { QueryResponse } from "@/lib/types";

interface MetaInfoProps {
  response: QueryResponse;
}

export function MetaInfo({ response }: MetaInfoProps) {
  const [expanded, setExpanded] = useState(false);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const handleCopy = async (field: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 2000);
    } catch {
      // ignore
    }
  };

  const items = [
    { label: "Request ID", value: response.request_id, copyable: true },
    { label: "Trace ID", value: response.trace_id, copyable: true },
    { label: "尝试次数", value: String(response.attempts ?? 0) },
    { label: "修复次数", value: String(response.repair_count ?? 0) },
    {
      label: "返回行数",
      value: String(response.returned_row_count ?? 0),
    },
    { label: "是否截断", value: response.truncated ? "是" : "否" },
  ];

  if (response.error) {
    items.push(
      {
        label: "错误类型",
        value: response.error.error_type,
      },
      { label: "错误代码", value: response.error.code },
    );
  }

  return (
    <div className="border-t border-[var(--color-border)]">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-1.5 px-4 py-3 text-sm text-[var(--color-text-secondary)] transition-colors duration-150 hover:bg-[var(--color-bg-subtle)]"
      >
        <ChevronRight
          className={`h-4 w-4 transition-transform duration-150 ${expanded ? "rotate-90" : ""}`}
        />
        详细信息
      </button>
      {expanded && (
        <div className="border-t border-[var(--color-border)] bg-[var(--color-bg-subtle)] p-4">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
            {items.map((item) => (
              <div
                key={item.label}
                className="flex items-center justify-between gap-2 text-xs"
              >
                <dt className="font-medium text-[var(--color-text-tertiary)]">
                  {item.label}
                </dt>
                <dd className="flex items-center gap-1 font-mono text-[var(--color-text-secondary)]">
                  <span className="truncate">{item.value}</span>
                  {item.copyable && (
                    <button
                      onClick={() => handleCopy(item.label, item.value)}
                      className="flex-shrink-0 text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]"
                    >
                      {copiedField === item.label ? (
                        <Check className="h-3 w-3 text-[var(--color-success)]" />
                      ) : (
                        <Copy className="h-3 w-3" />
                      )}
                    </button>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}
