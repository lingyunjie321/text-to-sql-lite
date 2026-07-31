"use client";

import { Send } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";

interface InputDockProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  isLoading: boolean;
  maxChars?: number;
}

export function InputDock({
  value,
  onChange,
  onSubmit,
  isLoading,
  maxChars = 2000,
}: InputDockProps) {
  const trimmed = value.trim();
  const canSubmit = trimmed.length > 0 && trimmed.length <= maxChars && !isLoading;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSubmit) onSubmit();
    }
  };

  return (
    <div className="fixed bottom-14 left-0 right-0 border-t border-[var(--color-border)] bg-white px-4 py-3 md:static md:bottom-auto md:border-0 md:bg-transparent md:px-0 md:py-0">
      <div className="mx-auto flex max-w-[1200px] items-end gap-2">
        <div className="flex-1">
          <Textarea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入你的问题..."
            maxChars={maxChars}
            disabled={isLoading}
          />
        </div>
        <Button
          onClick={onSubmit}
          disabled={!canSubmit}
          loading={isLoading}
          className="h-12 w-12 flex-shrink-0 p-0"
          aria-label="提交查询"
        >
          {!isLoading && <Send className="h-5 w-5" />}
        </Button>
      </div>
      <p className="mx-auto mt-1.5 hidden max-w-[1200px] text-xs text-[var(--color-text-tertiary)] md:block">
        按 Enter 提交 · Shift+Enter 换行
      </p>
    </div>
  );
}
