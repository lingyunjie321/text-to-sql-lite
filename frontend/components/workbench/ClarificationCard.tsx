"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { StatusBadge } from "./StatusBadge";
import { MetaInfo } from "./MetaInfo";
import type { QueryResponse } from "@/lib/types";

interface ClarificationCardProps {
  response: QueryResponse;
  onSubmit: (supplement: string) => void;
  onSkip: () => void;
}

export function ClarificationCard({
  response,
  onSubmit,
  onSkip,
}: ClarificationCardProps) {
  const [supplement, setSupplement] = useState("");

  const handleSubmit = () => {
    if (!supplement.trim()) return;
    onSubmit(supplement.trim());
    setSupplement("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="animate-fade-in rounded-lg border border-[var(--color-border)] bg-white shadow-sm">
      {/* Status header */}
      <div className="flex items-center justify-between px-4 py-3">
        <StatusBadge status={response.status} />
      </div>

      {/* Clarification question */}
      <div className="border-t border-[var(--color-border)] px-4 py-4">
        <p className="text-sm text-[var(--color-text-primary)]">
          {response.clarification?.question}
        </p>

        {/* Supplement input */}
        <div className="mt-3">
          <Textarea
            value={supplement}
            onChange={(e) => setSupplement(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="请输入补充说明..."
            maxChars={2000}
            showCount={false}
            rows={2}
          />
        </div>

        {/* Action buttons */}
        <div className="mt-3 flex justify-end gap-2">
          <Button variant="ghost" size="md" onClick={onSkip}>
            跳过
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={handleSubmit}
            disabled={!supplement.trim()}
          >
            提交补充
          </Button>
        </div>
      </div>

      {/* Meta info */}
      <MetaInfo response={response} />
    </div>
  );
}
