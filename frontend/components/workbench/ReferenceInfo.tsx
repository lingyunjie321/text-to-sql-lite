"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { SchemaCandidatesTable } from "./SchemaCandidatesTable";
import { SemanticReferencesGroup } from "./SemanticReferencesGroup";
import { ComplexityRoutePanel } from "./ComplexityRoutePanel";
import { RepairHistoryTimeline } from "./RepairHistoryTimeline";
import type { QueryResponse } from "@/lib/types";

interface ReferenceInfoProps {
  response: QueryResponse;
}

interface SubSectionProps {
  title: string;
  count?: string;
  defaultOpen: boolean;
  children: React.ReactNode;
}

function SubSection({ title, count, defaultOpen, children }: SubSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between py-1.5"
      >
        <span className="flex items-center gap-1.5">
          <ChevronRight
            className={`h-3.5 w-3.5 text-[var(--color-text-tertiary)] transition-transform duration-150 ${open ? "rotate-90" : ""}`}
          />
          <span className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-tertiary)]">
            {title}
          </span>
        </span>
        <span className="flex items-center gap-2">
          {count && (
            <span className="text-xs text-[var(--color-text-tertiary)]">
              {count}
            </span>
          )}
        </span>
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  );
}

export function ReferenceInfo({ response }: ReferenceInfoProps) {
  const [mainOpen, setMainOpen] = useState(true);

  const hasSchema = !!response.schema_candidates?.length;
  const hasSemantic = !!response.semantic_references?.length;
  const hasComplexity = !!response.complexity_route;
  const hasRepair = !!response.repair_history?.length;

  const sectionCount = [hasSchema, hasSemantic, hasComplexity, hasRepair].filter(
    Boolean,
  ).length;

  if (sectionCount === 0) return null;

  return (
    <div className="border-t border-[var(--color-border)]">
      {/* Main collapsible header */}
      <button
        onClick={() => setMainOpen(!mainOpen)}
        className="flex w-full items-center justify-between px-4 py-3 transition-colors duration-150 hover:bg-[var(--color-bg-subtle)]"
      >
        <span className="flex items-center gap-1.5 text-sm text-[var(--color-text-secondary)]">
          <ChevronRight
            className={`h-4 w-4 transition-transform duration-150 ${mainOpen ? "rotate-90" : ""}`}
          />
          参考信息
        </span>
        <span className="text-xs text-[var(--color-text-tertiary)]">
          {sectionCount} 项
        </span>
      </button>

      {mainOpen && (
        <div className="space-y-4 border-t border-[var(--color-border)] bg-[var(--color-bg-subtle)] p-4">
          {hasSchema && (
            <SubSection
              title="候选表"
              count={`${response.schema_candidates!.length} 张表`}
              defaultOpen={true}
            >
              <div className="rounded-md border border-[var(--color-border)] bg-white p-3">
                <SchemaCandidatesTable candidates={response.schema_candidates!} />
              </div>
            </SubSection>
          )}

          {hasSemantic && (
            <SubSection
              title="语义参考"
              count={`${response.semantic_references!.length} 条`}
              defaultOpen={true}
            >
              <div className="rounded-md border border-[var(--color-border)] bg-white">
                <SemanticReferencesGroup references={response.semantic_references!} />
              </div>
            </SubSection>
          )}

          {hasComplexity && (
            <SubSection title="复杂度路由" defaultOpen={true}>
              <ComplexityRoutePanel route={response.complexity_route!} />
            </SubSection>
          )}

          {hasRepair && (
            <SubSection
              title="修复历史"
              count={`${response.repair_history!.length} 次修复`}
              defaultOpen={true}
            >
              <div className="rounded-md border border-[var(--color-border)] bg-white p-3">
                <RepairHistoryTimeline
                  history={response.repair_history!}
                  finalSuccess={response.status === "SUCCEEDED_REPAIRED"}
                />
              </div>
            </SubSection>
          )}
        </div>
      )}
    </div>
  );
}
