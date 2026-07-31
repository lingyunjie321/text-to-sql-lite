"use client";

import { useState } from "react";
import { ChevronRight, Copy, Check } from "lucide-react";

interface SqlCollapseProps {
  sql: string;
}

// Simple SQL syntax highlighting
function highlightSql(sql: string): string {
  const keywords =
    /\b(SELECT|FROM|WHERE|JOIN|INNER|LEFT|RIGHT|OUTER|ON|GROUP|BY|ORDER|HAVING|LIMIT|OFFSET|AS|AND|OR|NOT|IN|EXISTS|BETWEEN|LIKE|IS|NULL|DISTINCT|UNION|ALL|INSERT|UPDATE|DELETE|SET|VALUES|INTO|CASE|WHEN|THEN|ELSE|END|COUNT|SUM|AVG|MIN|MAX|ASC|DESC|WITH|RECURSIVE)\b/gi;
  const strings = /'[^']*'/g;
  const numbers = /\b\d+\b/g;

  // Escape HTML first
  let escaped = sql
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Apply highlighting in order (strings first to avoid keyword matches inside strings)
  escaped = escaped.replace(strings, '<span class="sql-string">$&</span>');
  escaped = escaped.replace(keywords, '<span class="sql-keyword">$&</span>');
  escaped = escaped.replace(numbers, '<span class="sql-number">$&</span>');

  return escaped;
}

export function SqlCollapse({ sql }: SqlCollapseProps) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback: ignore
    }
  };

  return (
    <div className="border-t border-[var(--color-border)]">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-4 py-3 text-sm text-[var(--color-text-secondary)] transition-colors duration-150 hover:bg-[var(--color-bg-subtle)]"
      >
        <span className="flex items-center gap-1.5">
          <ChevronRight
            className={`h-4 w-4 transition-transform duration-150 ${expanded ? "rotate-90" : ""}`}
          />
          查看 SQL
        </span>
      </button>
      {expanded && (
        <div className="border-t border-[var(--color-border)] bg-[var(--color-bg-subtle)] p-4">
          <div className="mb-2 flex justify-end">
            <button
              onClick={handleCopy}
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium text-[var(--color-text-secondary)] transition-colors duration-150 hover:bg-[var(--color-bg-muted)]"
            >
              {copied ? (
                <>
                  <Check className="h-3.5 w-3.5 text-[var(--color-success)]" />
                  已复制
                </>
              ) : (
                <>
                  <Copy className="h-3.5 w-3.5" />
                  复制
                </>
              )}
            </button>
          </div>
          <pre
            className="sql-code overflow-x-auto rounded-md bg-white p-3 text-[var(--color-text-primary)]"
            dangerouslySetInnerHTML={{ __html: highlightSql(sql) }}
          />
        </div>
      )}
    </div>
  );
}
