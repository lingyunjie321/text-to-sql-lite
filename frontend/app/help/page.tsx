"use client";

import { useRouter } from "next/navigation";
import { BookOpen, Lightbulb, Database, ArrowRight } from "lucide-react";
import { HELP_SECTIONS, PAGILA_TABLES } from "@/lib/samples";

export default function HelpPage() {
  const router = useRouter();

  const handleSampleClick = (question: string) => {
    router.push(`/?q=${encodeURIComponent(question)}`);
  };

  return (
    <div className="mx-auto w-full max-w-[800px] px-4 py-6 md:px-6">
      <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
        使用帮助
      </h1>

      {/* How to use */}
      <section className="mt-6 rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
        <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--color-text-primary)]">
          <BookOpen className="h-5 w-5 text-[var(--color-primary)]" />
          如何使用
        </h2>
        <ol className="mt-3 space-y-2 text-sm text-[var(--color-text-secondary)]">
          <li className="flex gap-2">
            <span className="font-medium text-[var(--color-primary)]">1.</span>
            在底部输入框用自然语言描述你想查询的数据
          </li>
          <li className="flex gap-2">
            <span className="font-medium text-[var(--color-primary)]">2.</span>
            按 Enter 或点击提交按钮
          </li>
          <li className="flex gap-2">
            <span className="font-medium text-[var(--color-primary)]">3.</span>
            系统会自动生成 SQL 并执行查询
          </li>
          <li className="flex gap-2">
            <span className="font-medium text-[var(--color-primary)]">4.</span>
            查看结果表格，可切换图表视图
          </li>
          <li className="flex gap-2">
            <span className="font-medium text-[var(--color-primary)]">5.</span>
            如需查看 SQL，点击「查看 SQL」展开
          </li>
          <li className="flex gap-2">
            <span className="font-medium text-[var(--color-primary)]">6.</span>
            如果系统需要澄清，请补充信息后重新提交
          </li>
        </ol>
      </section>

      {/* Sample questions */}
      <section className="mt-4 rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
        <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--color-text-primary)]">
          <Lightbulb className="h-5 w-5 text-[var(--color-primary)]" />
          示例问题
        </h2>
        <div className="mt-4 space-y-5">
          {HELP_SECTIONS.map((section) => (
            <div key={section.title}>
              <h3 className="text-sm font-medium text-[var(--color-text-secondary)]">
                {section.title}
              </h3>
              <div className="mt-2 space-y-2">
                {section.questions.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => handleSampleClick(q.text)}
                    className="group flex w-full items-center justify-between rounded-md border border-[var(--color-border)] bg-white px-4 py-2.5 text-left text-sm text-[var(--color-text-secondary)] transition-colors duration-150 hover:border-[var(--color-border-strong)] hover:bg-[var(--color-bg-subtle)] hover:text-[var(--color-text-primary)]"
                  >
                    <span>{q.text}</span>
                    <ArrowRight className="h-4 w-4 flex-shrink-0 text-[var(--color-text-tertiary)] opacity-0 transition-opacity duration-150 group-hover:opacity-100" />
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Data scope */}
      <section className="mt-4 rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
        <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--color-text-primary)]">
          <Database className="h-5 w-5 text-[var(--color-primary)]" />
          数据范围
        </h2>
        <p className="mt-3 text-sm text-[var(--color-text-secondary)]">
          当前连接 Pagila 示例数据库，包含以下 13 张表：
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {PAGILA_TABLES.map((table) => (
            <span
              key={table}
              className="rounded-md bg-[var(--color-bg-muted)] px-2.5 py-1 font-mono text-xs text-[var(--color-text-secondary)]"
            >
              {table}
            </span>
          ))}
        </div>
        <p className="mt-3 text-sm text-[var(--color-text-secondary)]">
          这些表覆盖了 DVD 租赁业务的完整流程：影片管理、库存、客户、租赁、付款等。
        </p>
      </section>
    </div>
  );
}
