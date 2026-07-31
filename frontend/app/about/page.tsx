import { Info, Code, Database } from "lucide-react";

export default function AboutPage() {
  return (
    <div className="mx-auto w-full max-w-[800px] px-4 py-6 md:px-6">
      <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
        关于 Text-to-SQL Agent
      </h1>

      {/* Project intro */}
      <section className="mt-6 rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
        <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--color-text-primary)]">
          <Info className="h-5 w-5 text-[var(--color-primary)]" />
          项目简介
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-[var(--color-text-secondary)]">
          Text-to-SQL Agent
          是一个将自然语言转化为 SQL
          查询的智能助手。用户用自然语言提问，系统自动生成
          SQL、执行查询并返回结果，支持自动修复和澄清交互。
        </p>
      </section>

      {/* Tech stack */}
      <section className="mt-4 rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
        <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--color-text-primary)]">
          <Code className="h-5 w-5 text-[var(--color-primary)]" />
          技术栈
        </h2>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex gap-2">
            <dt className="w-20 flex-shrink-0 font-medium text-[var(--color-text-tertiary)]">
              前端
            </dt>
            <dd className="text-[var(--color-text-secondary)]">
              Next.js 16 + React + Tailwind CSS + Recharts
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 flex-shrink-0 font-medium text-[var(--color-text-tertiary)]">
              后端
            </dt>
            <dd className="text-[var(--color-text-secondary)]">
              FastAPI + LangGraph + PostgreSQL
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 flex-shrink-0 font-medium text-[var(--color-text-tertiary)]">
              AI
            </dt>
            <dd className="text-[var(--color-text-secondary)]">
              OpenAI Compatible LLM
            </dd>
          </div>
        </dl>
      </section>

      {/* Data source */}
      <section className="mt-4 rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm">
        <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--color-text-primary)]">
          <Database className="h-5 w-5 text-[var(--color-primary)]" />
          数据源
        </h2>
        <p className="mt-3 text-sm text-[var(--color-text-secondary)]">
          Pagila — PostgreSQL 示例数据库（DVD 租赁业务）
        </p>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          13 张业务表，覆盖影片、客户、租赁、付款等核心实体。
        </p>
      </section>
    </div>
  );
}
