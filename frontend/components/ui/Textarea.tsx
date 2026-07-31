"use client";

import { useRef, useEffect } from "react";

interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  maxChars?: number;
  showCount?: boolean;
}

export function Textarea({
  maxChars = 2000,
  showCount = true,
  className = "",
  value,
  onChange,
  ...props
}: TextareaProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Auto-resize
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 192)}px`;
  }, [value]);

  const charCount = typeof value === "string" ? value.length : 0;
  const isOverLimit = charCount > maxChars;

  return (
    <div className="relative w-full">
      <textarea
        ref={ref}
        value={value}
        onChange={onChange}
        rows={1}
        className={`w-full resize-none rounded-md border border-[var(--color-border-strong)] bg-white p-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 disabled:cursor-not-allowed disabled:bg-[var(--color-bg-muted)] disabled:text-[var(--color-text-tertiary)] ${isOverLimit ? "border-[var(--color-error)]" : ""} ${className}`}
        style={{ minHeight: "48px" }}
        {...props}
      />
      {showCount && (
        <span
          className={`pointer-events-none absolute bottom-2 right-3 text-xs ${isOverLimit ? "text-[var(--color-error)]" : "text-[var(--color-text-tertiary)]"}`}
        >
          {charCount}/{maxChars}
        </span>
      )}
    </div>
  );
}
