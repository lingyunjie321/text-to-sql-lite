"use client";

import { useState } from "react";
import { Ruler, TrendingUp, BookOpen, Lightbulb, ChevronDown } from "lucide-react";
import type { SemanticReference } from "@/lib/types";

interface SemanticReferencesGroupProps {
  references: SemanticReference[];
}

const typeConfig: Record<
  SemanticReference["type"],
  { label: string; bg: string; text: string; Icon: typeof Ruler }
> = {
  caliber: { label: "口径", bg: "bg-indigo-50", text: "text-indigo-700", Icon: Ruler },
  metric: { label: "指标", bg: "bg-emerald-50", text: "text-emerald-700", Icon: TrendingUp },
  glossary: { label: "术语", bg: "bg-amber-50", text: "text-amber-700", Icon: BookOpen },
  few_shot: { label: "示例", bg: "bg-purple-50", text: "text-purple-700", Icon: Lightbulb },
};

const typeOrder: SemanticReference["type"][] = ["caliber", "metric", "glossary", "few_shot"];

function ReferenceItem({ reference }: { reference: SemanticReference }) {
  const [expanded, setExpanded] = useState(false);
  const cfg = typeConfig[reference.type] ?? typeConfig.glossary;
  const { Icon } = cfg;

  return (
    <div className="border-b border-[var(--color-border)] px-3 py-2.5 last:border-0">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <span
            className={`inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ${cfg.bg} ${cfg.text}`}
          >
            <Icon className="h-3.5 w-3.5" />
            {cfg.label}
          </span>
          <span className="text-sm font-medium text-[var(--color-text-primary)]">
            {reference.title}
          </span>
        </div>
        <span
          className={`shrink-0 tabular-nums text-xs ${
            reference.score > 0.8
              ? "text-[var(--color-success)]"
              : "text-[var(--color-text-tertiary)]"
          }`}
        >
          {typeof reference.score === "number" ? reference.score.toFixed(2) : "—"}
        </span>
      </div>
      <div className="mt-1 pl-1">
        <p
          className={`text-sm leading-relaxed text-[var(--color-text-secondary)] ${
            expanded ? "" : "line-clamp-2"
          }`}
        >
          {reference.content}
        </p>
        {reference.content.length > 80 && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-1 inline-flex items-center gap-0.5 text-xs text-[var(--color-primary)] hover:underline"
          >
            {expanded ? "收起" : "展开"}
            <ChevronDown
              className={`h-3 w-3 transition-transform duration-150 ${expanded ? "rotate-180" : ""}`}
            />
          </button>
        )}
      </div>
    </div>
  );
}

export function SemanticReferencesGroup({ references }: SemanticReferencesGroupProps) {
  const sorted = [...references].sort((a, b) => b.score - a.score);

  // If <= 3 items, flat list
  if (sorted.length <= 3) {
    return (
      <div className="divide-y divide-[var(--color-border)]">
        {sorted.map((item, idx) => (
          <ReferenceItem key={`${item.type}-${idx}`} reference={item} />
        ))}
      </div>
    );
  }

  // Group by type
  const grouped = typeOrder
    .map((type) => ({
      type,
      items: sorted.filter((r) => r.type === type),
    }))
    .filter((g) => g.items.length > 0);

  return (
    <div className="space-y-3">
      {grouped.map((group) => {
        const cfg = typeConfig[group.type] ?? typeConfig.glossary;
        return (
          <div key={group.type}>
            <div className="mb-1.5 text-xs font-medium text-[var(--color-text-tertiary)]">
              {cfg.label}（{group.items.length} 条）
            </div>
            <div className="divide-y divide-[var(--color-border)] rounded-md border border-[var(--color-border)]">
              {group.items.map((item, idx) => (
                <ReferenceItem key={`${group.type}-${idx}`} reference={item} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
