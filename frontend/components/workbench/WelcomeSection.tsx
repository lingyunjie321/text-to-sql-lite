"use client";

import { Database } from "lucide-react";
import { SAMPLE_QUESTIONS } from "@/lib/samples";

interface WelcomeSectionProps {
  onSampleClick: (question: string) => void;
}

export function WelcomeSection({ onSampleClick }: WelcomeSectionProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      {/* Logo */}
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--color-primary-light)]">
        <Database className="h-8 w-8 text-[var(--color-primary)]" />
      </div>

      {/* Title */}
      <h1 className="text-2xl font-bold text-[var(--color-text-primary)] sm:text-3xl">
        用自然语言查询你的数据
      </h1>
      <p className="mt-2 text-sm text-[var(--color-text-secondary)] sm:text-base">
        连接 Pagila 示例数据库，支持 13 张业务表
      </p>

      {/* Sample questions */}
      <div className="mt-8 w-full max-w-2xl">
        <p className="mb-3 text-left text-sm font-medium text-[var(--color-text-secondary)]">
          试试这些问题：
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {SAMPLE_QUESTIONS.map((sample, i) => (
            <button
              key={i}
              onClick={() => onSampleClick(sample.text)}
              className="rounded-full border border-[var(--color-border)] bg-white px-4 py-2.5 text-left text-sm text-[var(--color-text-secondary)] transition-colors duration-150 hover:border-[var(--color-border-strong)] hover:bg-[var(--color-bg-subtle)] hover:text-[var(--color-text-primary)]"
            >
              {sample.text}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
