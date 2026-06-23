import { describe, expect, it } from "vitest";

import { adaptQueryRun } from "./queryRunAdapter";
import type { QueryRunResponse } from "../api/types";

const successResponse: QueryRunResponse = {
  request_id: "run_1",
  status: "success",
  final_sql: "SELECT id, amount FROM orders ORDER BY id",
  result: {
    success: true,
    columns: ["id", "amount", "note"],
    rows: [
      { id: 1, amount: 120.5, note: null },
      { id: 2, amount: 88, note: "priority" }
    ],
    duration_ms: 14
  },
  attempts: 0,
  selected_model: "strong",
  routing_reason: "复杂查询使用 strong",
  linked_schema: { tables: ["orders", "customers"] },
  retrieved_examples: [
    {
      natural_language: "列出订单金额",
      sql: "SELECT id, amount FROM orders",
      dialect: "sqlite",
      involved_tables: ["orders"],
      score: 0.93,
      reasons: ["字段匹配"]
    }
  ],
  repair_history: [],
  errors: [],
  trace: [
    {
      node_name: "GenerateSQLNode",
      node_type: "sql_generation",
      start_time: "2026-06-22T10:00:00Z",
      end_time: "2026-06-22T10:00:01Z",
      duration_ms: 1000,
      status: "success",
      outcome: "generated",
      input_summary: { prompt: "hidden" },
      output_summary: { sql: "SELECT id, amount FROM orders" },
      error: null
    }
  ]
};

describe("adaptQueryRun", () => {
  it("把成功响应转换为面向用户的 SQL 与结果状态", () => {
    const view = adaptQueryRun(successResponse, "sqlite");

    expect(view.sqlStatus).toBe("generated_valid");
    expect(view.statusText).toBe("SQL 已生成并通过验证");
    expect(view.sql).toBe("SELECT id, amount FROM orders ORDER BY id");
    expect(view.result?.rowCount).toBe(2);
    expect(view.result?.executionMs).toBe(14);
    expect(view.result?.columns).toEqual(["id", "amount", "note"]);
    expect(view.details.usedTables).toEqual(["orders", "customers"]);
    expect(view.developerInfo.model).toBe("strong");
  });

  it("把修复成功响应转换为轻量修复提示和可展开详情", () => {
    const repaired = adaptQueryRun(
      {
        ...successResponse,
        attempts: 1,
        final_sql: "SELECT orders.id, orders.amount FROM orders ORDER BY orders.id",
        repair_history: [
          {
            error: { message: "字段不存在: order.total" },
            before_sql: "SELECT order.total FROM orders",
            after_sql: "SELECT orders.amount FROM orders",
            explanation: "将不存在的 total 字段改为 amount 字段"
          }
        ]
      },
      "sqlite"
    );

    expect(repaired.sqlStatus).toBe("repaired_valid");
    expect(repaired.statusText).toBe("SQL 已修复并通过验证");
    expect(repaired.repairNotice?.summary).toBe("系统已自动修复 1 处字段引用问题");
    expect(repaired.repairNotice?.error).toContain("字段不存在");
    expect(repaired.repairNotice?.afterSql).toContain("orders.amount");
    expect(repaired.details.repairCount).toBe(1);
  });

  it("失败时保留 SQL 并把原始错误收进开发者信息", () => {
    const failed = adaptQueryRun(
      {
        ...successResponse,
        status: "failed",
        final_sql: "SELECT total FROM orders",
        result: null,
        attempts: 3,
        errors: [
          {
            node_name: "ValidateSQLNode",
            error_type: "unknown_column",
            message: "字段不存在: total"
          }
        ]
      },
      "sqlite"
    );

    expect(failed.sqlStatus).toBe("failed");
    expect(failed.statusText).toBe("未能生成可执行 SQL");
    expect(failed.sql).toBe("SELECT total FROM orders");
    expect(failed.userError?.message).toBe("字段不存在: total");
    expect(failed.developerInfo.errors[0]?.node_name).toBe("ValidateSQLNode");
  });
});
