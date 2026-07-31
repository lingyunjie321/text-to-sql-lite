"use client";

import { useState } from "react";
import { Download, AlertTriangle, ChevronLeft, ChevronRight } from "lucide-react";
import type { QueryResponse } from "@/lib/types";

interface ResultTableProps {
  columns: QueryResponse["columns"];
  rows: QueryResponse["rows"];
  truncated?: boolean;
}

const PAGE_SIZE = 50;

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    // Format currency-like numbers
    if (Number.isFinite(value)) {
      const abs = Math.abs(value);
      if (abs > 100 || Number.isInteger(value)) {
        return value.toLocaleString("en-US");
      }
      return value.toFixed(2);
    }
  }
  if (typeof value === "string") return value;
  if (Array.isArray(value) || typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function isNumericColumn(rows: unknown[][], colIndex: number): boolean {
  let numericCount = 0;
  let totalCount = 0;
  for (const row of rows.slice(0, 20)) {
    const val = row[colIndex];
    if (val !== null && val !== undefined) {
      totalCount++;
      if (typeof val === "number") numericCount++;
    }
  }
  return totalCount > 0 && numericCount / totalCount > 0.5;
}

export function ResultTable({ columns, rows, truncated }: ResultTableProps) {
  const [page, setPage] = useState(0);

  if (!columns || columns.length === 0) {
    return (
      <div className="py-12 text-center">
        <p className="text-sm text-[var(--color-text-secondary)]">
          查询成功，但没有返回列信息
        </p>
      </div>
    );
  }

  if (!rows || rows.length === 0) {
    return (
      <div className="py-12 text-center">
        <p className="text-sm text-[var(--color-text-secondary)]">
          查询成功，但没有匹配的数据
        </p>
        <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">
          试试调整查询条件
        </p>
      </div>
    );
  }

  const totalPages = Math.ceil(rows.length / PAGE_SIZE);
  const pageRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const handleExportCsv = () => {
    const header = columns.map((c) => c.name).join(",");
    const body = rows
      .map((row) =>
        row
          .map((cell) => {
            const formatted = formatCellValue(cell);
            // Escape CSV
            if (
              formatted.includes(",") ||
              formatted.includes('"') ||
              formatted.includes("\n")
            ) {
              return `"${formatted.replace(/"/g, '""')}"`;
            }
            return formatted;
          })
          .join(","),
      )
      .join("\n");
    const csv = `${header}\n${body}`;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `query-result-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      {/* Truncation warning */}
      {truncated && (
        <div className="mb-2 flex items-center gap-1.5 rounded-md bg-[var(--color-warning-light)] px-3 py-2 text-xs text-[var(--color-warning)]">
          <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
          <span>实际结果超过 1000 行，已截断展示前 1000 行</span>
        </div>
      )}

      {/* Export button */}
      <div className="mb-2 flex justify-end">
        <button
          onClick={handleExportCsv}
          className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium text-[var(--color-text-secondary)] transition-colors duration-150 hover:bg-[var(--color-bg-subtle)]"
        >
          <Download className="h-3.5 w-3.5" />
          导出 CSV
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-md border border-[var(--color-border)]">
        <table className="min-w-full">
          <thead className="sticky top-0 bg-[var(--color-bg-muted)]">
            <tr>
              {columns.map((col, i) => (
                <th
                  key={i}
                  className="border-b border-[var(--color-border)] px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-secondary)]"
                >
                  {col.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, ri) => (
              <tr
                key={ri}
                className="border-b border-[var(--color-border)] transition-colors duration-100 last:border-b-0 hover:bg-[var(--color-bg-subtle)]"
              >
                {row.map((cell, ci) => {
                  const numeric = isNumericColumn(rows, ci);
                  return (
                    <td
                      key={ci}
                      className={`px-4 py-3 text-sm text-[var(--color-text-primary)] ${numeric ? "text-right tabular-nums" : "text-left"}`}
                    >
                      {formatCellValue(cell)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-[var(--color-text-tertiary)]">
            共 {rows.length} 行
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(Math.max(0, page - 1))}
              disabled={page === 0}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md text-sm text-[var(--color-text-secondary)] transition-colors duration-150 hover:bg-[var(--color-bg-subtle)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="text-sm text-[var(--color-text-secondary)]">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() =>
                setPage(Math.min(totalPages - 1, page + 1))
              }
              disabled={page === totalPages - 1}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md text-sm text-[var(--color-text-secondary)] transition-colors duration-150 hover:bg-[var(--color-bg-subtle)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
