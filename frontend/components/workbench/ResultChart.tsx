"use client";

import { useCallback, useSyncExternalStore } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import type { QueryResponse } from "@/lib/types";

interface ResultChartProps {
  columns: QueryResponse["columns"];
  rows: QueryResponse["rows"];
  chartType: "bar" | "line";
}

function useIsDesktop() {
  const subscribe = useCallback((notify: () => void) => {
    const mq = window.matchMedia("(min-width: 768px)");
    mq.addEventListener("change", notify);
    return () => mq.removeEventListener("change", notify);
  }, []);
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia("(min-width: 768px)").matches,
    () => false,
  );
}

// Detect if a column contains date/time values
function isDateColumn(rows: unknown[][], colIndex: number): boolean {
  let dateCount = 0;
  let totalCount = 0;
  for (const row of rows.slice(0, 10)) {
    const val = row[colIndex];
    if (val !== null && val !== undefined && typeof val === "string") {
      totalCount++;
      // Check for common date patterns
      if (
        /^\d{4}-\d{2}-\d{2}/.test(val) ||
        /^\d{4}\/\d{2}\/\d{2}/.test(val) ||
        /^\d{1,2}\/\d{1,2}\/\d{4}/.test(val) ||
        /^\d{4}年/.test(val) ||
        /^\d{4}-\d{2}$/.test(val) || // YYYY-MM
        /^\d{4}Q[1-4]$/.test(val) // YYYY-QN
      ) {
        dateCount++;
      }
    }
  }
  return totalCount > 0 && dateCount / totalCount > 0.5;
}

export function ResultChart({
  columns,
  rows,
  chartType,
}: ResultChartProps) {
  const isDesktop = useIsDesktop();
  const height = isDesktop ? 400 : 300;

  if (!columns || columns.length < 2 || !rows || rows.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-sm text-[var(--color-text-tertiary)]">
        当前结果不适合图表展示
      </div>
    );
  }

  // Transform data for Recharts
  const xKey = columns[0].name;
  const yKey = columns[1].name;

  const data = rows.map((row) => ({
    [xKey]: String(row[0] ?? ""),
    [yKey]: typeof row[1] === "number" ? row[1] : Number(row[1]) || 0,
  }));

  const commonProps = {
    data,
    margin: { top: 20, right: 30, left: 20, bottom: 60 },
  };

  const axisProps = {
    tick: {
      fill: "var(--color-text-secondary)",
      fontSize: 12,
    },
  };

  const tooltipStyle = {
    backgroundColor: "white",
    border: "1px solid var(--color-border)",
    borderRadius: "8px",
    fontSize: "13px",
  };

  if (chartType === "line") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart {...commonProps}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--color-border)"
          />
          <XAxis
            dataKey={xKey}
            {...axisProps}
            angle={-30}
            textAnchor="end"
            height={60}
          />
          <YAxis {...axisProps} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelStyle={{ color: "var(--color-text-primary)" }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            type="monotone"
            dataKey={yKey}
            stroke="var(--color-primary)"
            strokeWidth={2}
            dot={{ r: 4, fill: "var(--color-primary)" }}
            activeDot={{ r: 6 }}
          />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // Bar chart (default)
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart {...commonProps}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
        <XAxis
          dataKey={xKey}
          {...axisProps}
          angle={-30}
          textAnchor="end"
          height={60}
        />
        <YAxis {...axisProps} />
        <Tooltip
          contentStyle={tooltipStyle}
          labelStyle={{ color: "var(--color-text-primary)" }}
          cursor={{ fill: "var(--color-bg-subtle)" }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar
          dataKey={yKey}
          fill="var(--color-primary)"
          radius={[4, 4, 0, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

// Helper to determine recommended chart type
export function getRecommendedChartType(
  columns: QueryResponse["columns"],
  rows: QueryResponse["rows"],
): "bar" | "line" | "disabled" {
  if (!columns || columns.length !== 2 || !rows || rows.length === 0) {
    return "disabled";
  }
  if (isDateColumn(rows, 0)) {
    return "line";
  }
  return "bar";
}
