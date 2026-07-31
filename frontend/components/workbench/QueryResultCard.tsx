"use client";

import { useState } from "react";
import { Table2, BarChart3, LineChart as LineChartIcon } from "lucide-react";
import { StatusBadge, getStatusSubtitle } from "./StatusBadge";
import { ResultTable } from "./ResultTable";
import { ResultChart, getRecommendedChartType } from "./ResultChart";
import { SqlCollapse } from "./SqlCollapse";
import { MetaInfo } from "./MetaInfo";
import { ReferenceInfo } from "./ReferenceInfo";
import { Tabs } from "@/components/ui/Tabs";
import type { QueryResponse } from "@/lib/types";

interface QueryResultCardProps {
  response: QueryResponse;
}

export function QueryResultCard({ response }: QueryResultCardProps) {
  const recommended = getRecommendedChartType(
    response.columns,
    response.rows,
  );

  // Default tab: 0=table, 1=bar, 2=line
  // If recommended is "line", default to line (tab 2)
  // If recommended is "bar", default to bar (tab 1)
  // If recommended is "disabled", default to table (tab 0)
  const defaultTab =
    recommended === "line" ? 2 : recommended === "bar" ? 1 : 0;
  const [activeTab, setActiveTab] = useState(defaultTab);

  const chartDisabled = recommended === "disabled";
  const subtitle = getStatusSubtitle(response.status, response);

  // Check if there are any reference info extension fields to display
  const isSuccess =
    response.status === "SUCCEEDED_FIRST_PASS" ||
    response.status === "SUCCEEDED_REPAIRED";
  const hasReferenceInfo =
    isSuccess &&
    (!!response.schema_candidates?.length ||
      !!response.semantic_references?.length ||
      !!response.complexity_route ||
      !!response.repair_history?.length);

  const tabs = [
    {
      label: "表格",
      icon: <Table2 className="h-4 w-4" />,
      disabled: false,
    },
    {
      label: "柱状图",
      icon: <BarChart3 className="h-4 w-4" />,
      disabled: chartDisabled,
      disabledReason: "当前结果不适合图表展示",
    },
    {
      label: "折线图",
      icon: <LineChartIcon className="h-4 w-4" />,
      disabled: chartDisabled,
      disabledReason: "当前结果不适合图表展示",
    },
  ];

  return (
    <div className="animate-fade-in rounded-lg border border-[var(--color-border)] bg-white shadow-sm">
      {/* Status header */}
      <div className="flex items-center justify-between px-4 py-3">
        <StatusBadge status={response.status} subtitle={subtitle} />
      </div>

      {/* Result viewer */}
      <div className="border-t border-[var(--color-border)] px-4 py-4">
        <Tabs
          tabs={tabs}
          activeIndex={activeTab}
          onChange={setActiveTab}
        />

        <div className="mt-4">
          {activeTab === 0 && (
            <ResultTable
              columns={response.columns}
              rows={response.rows}
              truncated={response.truncated}
            />
          )}
          {activeTab === 1 && !chartDisabled && (
            <ResultChart
              columns={response.columns}
              rows={response.rows}
              chartType="bar"
            />
          )}
          {activeTab === 2 && !chartDisabled && (
            <ResultChart
              columns={response.columns}
              rows={response.rows}
              chartType="line"
            />
          )}
        </div>
      </div>

      {/* Reference info (enhanced) */}
      {hasReferenceInfo && <ReferenceInfo response={response} />}

      {/* SQL collapse */}
      {response.sql && <SqlCollapse sql={response.sql} />}

      {/* Meta info */}
      <MetaInfo response={response} />
    </div>
  );
}
