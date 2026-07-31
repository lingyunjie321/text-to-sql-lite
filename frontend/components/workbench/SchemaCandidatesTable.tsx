"use client";

import { Check, Circle } from "lucide-react";
import type { SchemaCandidate } from "@/lib/types";

interface SchemaCandidatesTableProps {
  candidates: SchemaCandidate[];
}

const sourceStyles: Record<
  SchemaCandidate["source"],
  { label: string; bg: string; text: string }
> = {
  bm25: { label: "bm25", bg: "bg-amber-50", text: "text-amber-700" },
  embedding: { label: "embed", bg: "bg-blue-50", text: "text-blue-700" },
  rerank: { label: "rerank", bg: "bg-purple-50", text: "text-purple-700" },
};

export function SchemaCandidatesTable({ candidates }: SchemaCandidatesTableProps) {
  // Sort by score descending
  const sorted = [...candidates].sort((a, b) => b.score - a.score);

  return (
    <>
      {/* Desktop table */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
              <th className="py-2 pr-2 text-left font-medium"></th>
              <th className="py-2 pr-2 text-left font-medium">表名</th>
              <th className="py-2 pr-2 text-left font-medium">命中字段</th>
              <th className="py-2 pr-2 text-center font-medium">来源</th>
              <th className="py-2 pr-2 text-right font-medium">相关性</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((c) => {
              const src = sourceStyles[c.source] ?? sourceStyles.bm25;
              return (
                <tr
                  key={`${c.schema}.${c.table_name}`}
                  className={`border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-bg-subtle)] ${
                    c.selected ? "bg-[var(--color-success-light)]" : ""
                  }`}
                >
                  <td className="py-2 pr-2 text-center">
                    {c.selected ? (
                      <Check className="inline h-4 w-4 text-[var(--color-success)]" />
                    ) : (
                      <Circle className="inline h-3 w-3 text-[var(--color-text-tertiary)]" />
                    )}
                  </td>
                  <td className="py-2 pr-2">
                    <span className="font-mono text-[var(--color-text-primary)]">
                      {c.schema}.{c.table_name}
                    </span>
                  </td>
                  <td className="py-2 pr-2">
                    <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                      {c.fields.join(", ") || "—"}
                    </span>
                  </td>
                  <td className="py-2 pr-2 text-center">
                    <span
                      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${src.bg} ${src.text}`}
                    >
                      {src.label}
                    </span>
                  </td>
                  <td className="py-2 pr-2 text-right">
                    <span
                      className={`tabular-nums text-xs ${
                        c.score > 0.8
                          ? "text-[var(--color-success)]"
                          : "text-[var(--color-text-secondary)]"
                      }`}
                    >
                      {typeof c.score === "number" ? c.score.toFixed(2) : "—"}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="space-y-2 md:hidden">
        {sorted.map((c) => {
          const src = sourceStyles[c.source] ?? sourceStyles.bm25;
          return (
            <div
              key={`${c.schema}.${c.table_name}`}
              className={`rounded-md border p-3 ${
                c.selected
                  ? "border-[var(--color-success)] bg-[var(--color-success-light)]"
                  : "border-[var(--color-border)]"
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  {c.selected ? (
                    <Check className="h-4 w-4 text-[var(--color-success)]" />
                  ) : (
                    <Circle className="h-3 w-3 text-[var(--color-text-tertiary)]" />
                  )}
                  <span className="font-mono text-sm text-[var(--color-text-primary)]">
                    {c.schema}.{c.table_name}
                  </span>
                </div>
                <span
                  className={`tabular-nums text-xs ${
                    c.score > 0.8
                      ? "text-[var(--color-success)]"
                      : "text-[var(--color-text-secondary)]"
                  }`}
                >
                  {typeof c.score === "number" ? c.score.toFixed(2) : "—"}
                </span>
              </div>
              <div className="mt-1 font-mono text-xs text-[var(--color-text-secondary)]">
                命中: {c.fields.join(", ") || "—"}
              </div>
              <div className="mt-1">
                <span
                  className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${src.bg} ${src.text}`}
                >
                  {src.label}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
