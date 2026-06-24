import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { TextToSqlClient } from "./api/client";
import type { QueryRunResponse, RuntimeConfigResponse, RuntimeOptionsResponse, SchemaResponse } from "./api/types";

const schemaResponse: SchemaResponse = {
  tables: {
    orders: {
      description: "订单事实表",
      columns: {
        id: { type: "INTEGER", nullable: false },
        amount: { type: "REAL", nullable: false },
        customer_id: { type: "INTEGER", nullable: false }
      }
    },
    customers: {
      description: "客户维表",
      columns: {
        id: { type: "INTEGER", nullable: false },
        name: { type: "TEXT", nullable: false },
        region_id: { type: "INTEGER", nullable: false }
      }
    },
    regions: {
      description: "地区维表",
      columns: {
        id: { type: "INTEGER", nullable: false },
        name: { type: "TEXT", nullable: false }
      }
    }
  }
};

const successResponse: QueryRunResponse = {
  request_id: "run_1",
  status: "success",
  final_sql: "SELECT id, amount, NULL AS note FROM orders ORDER BY id",
  result: {
    success: true,
    columns: ["id", "amount", "note"],
    rows: [
      { id: 1, amount: 120.5, note: null },
      { id: 2, amount: 88, note: "priority" }
    ],
    duration_ms: 18
  },
  attempts: 0,
  selected_model: "strong",
  routing_reason: "复杂查询使用 strong",
  linked_schema: { tables: ["orders"] },
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
  rag_context: {
    reference_sql: [
      {
        name: "order_amount",
        natural_language: "列出订单金额",
        sql: "SELECT id, amount FROM orders",
        involved_tables: ["orders"],
        score: 1,
        reasons: ["query"]
      }
    ],
    documents: [],
    metrics: [],
    semantic_models: []
  },
  repair_history: [],
  errors: [],
  trace: [
    {
      node_name: "SchemaLinkingNode",
      node_type: "schema_linking",
      start_time: "2026-06-22T10:00:00Z",
      end_time: "2026-06-22T10:00:00.030Z",
      duration_ms: 30,
      status: "success",
      outcome: "schema_linked",
      input_summary: { question: "列出订单金额" },
      output_summary: { tables: ["orders"] },
      error: null
    },
    {
      node_name: "GenerateSQLNode",
      node_type: "sql_generation",
      start_time: "2026-06-22T10:00:00.030Z",
      end_time: "2026-06-22T10:00:01Z",
      duration_ms: 970,
      status: "success",
      outcome: "generated",
      input_summary: { prompt: "hidden" },
      output_summary: { sql: "SELECT id, amount FROM orders" },
      error: null
    }
  ]
};

const repairedResponse: QueryRunResponse = {
  ...successResponse,
  request_id: "run_repaired",
  attempts: 1,
  final_sql: "SELECT r.name AS region, SUM(o.amount) AS total_amount FROM regions r JOIN customers c ON c.region_id = r.id JOIN orders o ON o.customer_id = c.id GROUP BY r.name",
  linked_schema: { tables: ["regions", "customers", "orders"] },
  repair_history: [
    {
      attempt: 1,
      error_type: "unknown_column",
      error: { message: "字段不存在: total_amount" },
      before_sql: "SELECT region_id, SUM(total_amount) FROM orders GROUP BY region_id",
      after_sql: "SELECT r.name AS region, SUM(o.amount) AS total_amount FROM regions r JOIN customers c ON c.region_id = r.id JOIN orders o ON o.customer_id = c.id GROUP BY r.name",
      explanation: "将不存在的 total_amount 字段改为 orders.amount，并补齐地区关联。"
    }
  ],
  trace: [
    ...successResponse.trace,
    {
      node_name: "ReflectErrorNode",
      node_type: "error_reflection",
      start_time: "2026-06-22T10:00:01Z",
      end_time: "2026-06-22T10:00:01.030Z",
      duration_ms: 30,
      status: "success",
      outcome: "reflect_retry",
      input_summary: { attempt: 1 },
      output_summary: { fixable: true },
      error: null
    },
    {
      node_name: "FixSQLNode",
      node_type: "sql_fix",
      start_time: "2026-06-22T10:00:01.030Z",
      end_time: "2026-06-22T10:00:01.120Z",
      duration_ms: 90,
      status: "success",
      outcome: "fix_complete",
      input_summary: { error_type: "unknown_column" },
      output_summary: { sql: "fixed" },
      error: null
    }
  ]
};

const failedResponse: QueryRunResponse = {
  ...successResponse,
  request_id: "run_failed",
  status: "failed",
  final_sql: "SELECT missing_amount FROM missing_orders",
  result: null,
  attempts: 3,
  repair_history: [
    {
      attempt: 3,
      error_type: "unknown_table",
      before_sql: "SELECT missing_amount FROM missing_orders",
      after_sql: "SELECT missing_amount FROM missing_orders",
      explanation: "达到最大修复次数，停止重试。"
    }
  ],
  errors: [
    {
      node_name: "ReflectErrorNode",
      error_type: "attempts_exhausted",
      message: "达到最大修复次数，停止重试"
    }
  ],
  trace: [
    ...successResponse.trace,
    {
      node_name: "ReflectErrorNode",
      node_type: "error_reflection",
      start_time: "2026-06-22T10:00:02Z",
      end_time: "2026-06-22T10:00:02.030Z",
      duration_ms: 30,
      status: "failed",
      outcome: "attempts_exhausted",
      input_summary: { attempt: 3 },
      output_summary: { terminated: true },
      error: { message: "达到最大修复次数" }
    }
  ]
};

function buildClient(responses: QueryRunResponse[] = [successResponse]): TextToSqlClient {
  const queue = [...responses];
  return {
    getSchema: vi.fn<TextToSqlClient["getSchema"]>().mockResolvedValue(schemaResponse),
    getRuntimeOptions: vi.fn<TextToSqlClient["getRuntimeOptions"]>().mockResolvedValue(runtimeOptionsResponse),
    createRuntimeConfig: vi.fn<TextToSqlClient["createRuntimeConfig"]>().mockResolvedValue(runtimeConfigResponse),
    runQuery: vi.fn<TextToSqlClient["runQuery"]>().mockImplementation(() => {
      const next = queue.shift() ?? responses.at(-1) ?? successResponse;
      return Promise.resolve(next);
    }),
    runEditedSql: vi.fn<TextToSqlClient["runEditedSql"]>().mockResolvedValue(successResponse)
  };
}

const runtimeOptionsResponse: RuntimeOptionsResponse = {
  database_presets: [
    {
      id: "demo_sqlite",
      driver: "sqlite",
      display_name: "demo_sqlite",
      target_dialect: "sqlite",
      read_only: true
    }
  ],
  model_presets: {
    light: [
      {
        id: "light",
        provider: "mock",
        model: "mock-light",
        display_name: "mock/mock-light",
        requires_secret: false
      }
    ],
    strong: [
      {
        id: "strong",
        provider: "mock",
        model: "mock-strong",
        display_name: "mock/mock-strong",
        requires_secret: false
      }
    ]
  }
};

const runtimeConfigResponse: RuntimeConfigResponse = {
  runtime_config_id: "rt_frontend",
  expires_at: "2026-06-23T12:00:00Z",
  database: {
    display_name: "demo_sqlite",
    driver: "sqlite",
    target_dialect: "sqlite",
    table_count: 3,
    column_count: 9,
    tables: ["orders", "customers", "regions"]
  },
  models: {
    light: { provider: "mock", model: "mock-light" },
    strong: { provider: "mock", model: "mock-strong" }
  }
};

describe("App", () => {
  it("以用户查询工作台作为首页，并只显示轻量 Schema 提示", async () => {
    render(<App client={buildClient()} />);

    expect(screen.getByText("Text to SQL")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "问数据，拿结果" })).toBeInTheDocument();
    expect(screen.getByLabelText("用自然语言描述你需要的数据")).toHaveFocus();
    expect(await screen.findByText("当前可查询 3 张表")).toBeInTheDocument();
    expect(screen.getByText("orders")).toBeInTheDocument();
    expect(screen.getByText("customers")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开工作台菜单" })).toBeInTheDocument();
    expect(screen.queryByText("Agent Trace")).not.toBeInTheDocument();
  });

  it("提交成功后展示 SQL 状态、结果摘要和结果表", async () => {
    const user = userEvent.setup();
    const client = buildClient([repairedResponse]);
    render(<App client={client} />);

    await user.type(screen.getByLabelText("用自然语言描述你需要的数据"), "按地区统计销售额");
    await user.click(screen.getByRole("button", { name: "生成并验证" }));

    expect(client.runQuery).toHaveBeenCalledWith({
      question: "按地区统计销售额",
      targetDialect: "sqlite"
    });
    expect(await screen.findByText("SQL 已修复并通过验证")).toBeInTheDocument();
    expect(screen.getByText("自动修复 1 次")).toBeInTheDocument();
    expect(screen.getByText("使用表：regions、customers、orders")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/SUM\(o.amount\)/)).toBeInTheDocument();

    const resultRegion = screen.getByRole("region", { name: "查询结果" });
    expect(within(resultRegion).getByText("2 行")).toBeInTheDocument();
    expect(within(resultRegion).getByText("18 ms")).toBeInTheDocument();
    expect(within(resultRegion).getByText("120.5")).toHaveClass("cellNumeric");
    expect(within(resultRegion).getByText("NULL")).toHaveClass("cellNull");
  });

  it("右上角菜单可以打开演示中心，并一键运行内置场景", async () => {
    const user = userEvent.setup();
    const client = buildClient([successResponse]);
    render(<App client={client} />);

    await user.click(screen.getByRole("button", { name: "打开工作台菜单" }));
    await user.click(screen.getByRole("button", { name: "演示中心" }));

    const panel = screen.getByRole("dialog", { name: "演示中心" });
    expect(within(panel).getByText("复杂查询一次成功")).toBeInTheDocument();
    expect(within(panel).getByText("错误字段自动修复")).toBeInTheDocument();
    expect(within(panel).getByText("达到终止条件")).toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: "运行复杂查询一次成功" }));

    expect(client.runQuery).toHaveBeenCalledWith({
      question: "统计每个地区订单金额最高的 3 个客户，返回地区、客户名称、总金额和地区内排名。",
      targetDialect: "sqlite"
    });
    expect(await screen.findByText("SQL 已生成并通过验证")).toBeInTheDocument();
  });

  it("开发者调试页以可视化 Trace 为核心，并把原始 JSON 收在折叠区", async () => {
    const user = userEvent.setup();
    render(<App client={buildClient([repairedResponse])} />);

    await user.type(screen.getByLabelText("用自然语言描述你需要的数据"), "按地区统计销售额");
    await user.click(screen.getByRole("button", { name: "生成并验证" }));
    await screen.findByText("SQL 已修复并通过验证");
    expect(screen.queryByText("Agent Trace")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "打开工作台菜单" }));
    await user.click(screen.getByRole("button", { name: "开发者调试" }));

    const panel = screen.getByRole("dialog", { name: "开发者调试" });
    expect(within(panel).getByText("Agent Trace")).toBeInTheDocument();
    expect(within(panel).getByText("SchemaLinkingNode")).toBeInTheDocument();
    expect(within(panel).getByText("ReflectErrorNode")).toBeInTheDocument();
    expect(within(panel).getByText("fix_complete")).toBeInTheDocument();
    expect(within(panel).getByText(/模型：strong/)).toBeInTheDocument();
    expect(within(panel).getByText("Top-K 示例")).toBeInTheDocument();
    expect(within(panel).queryByText(/"request_id": "run_repaired"/)).not.toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: "查看原始 JSON" }));
    expect(within(panel).getByText(/"request_id": "run_repaired"/)).toBeInTheDocument();
  });

  it("终止路径显示用户错误，并可在历史记录中重新查看", async () => {
    const user = userEvent.setup();
    render(<App client={buildClient([failedResponse])} />);

    await user.type(screen.getByLabelText("用自然语言描述你需要的数据"), "触发一个无法修复的查询");
    await user.click(screen.getByRole("button", { name: "生成并验证" }));

    expect(await screen.findByText("未能生成可执行 SQL")).toBeInTheDocument();
    expect(screen.getByText("达到最大修复次数，停止重试")).toBeInTheDocument();
    expect(screen.getByText("自动修复 3 次")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "打开工作台菜单" }));
    await user.click(screen.getByRole("button", { name: "历史记录" }));

    const panel = screen.getByRole("dialog", { name: "历史记录" });
    expect(within(panel).getByRole("button", { name: /触发一个无法修复的查询/ })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: /触发一个无法修复的查询/ }));

    expect(screen.getByDisplayValue("SELECT missing_amount FROM missing_orders")).toBeInTheDocument();
  });

  it("编辑状态下可以运行修改后的 SQL 并刷新结果", async () => {
    const user = userEvent.setup();
    const editedResponse: QueryRunResponse = {
      ...successResponse,
      request_id: "run_edited",
      final_sql: "SELECT id FROM orders ORDER BY id",
      result: {
        success: true,
        columns: ["id"],
        rows: [{ id: 7 }],
        duration_ms: 9
      }
    };
    const client = buildClient([successResponse]);
    vi.mocked(client.runEditedSql).mockResolvedValueOnce(editedResponse);
    render(<App client={client} />);

    await user.type(screen.getByLabelText("用自然语言描述你需要的数据"), "列出订单金额");
    await user.click(screen.getByRole("button", { name: "生成并验证" }));
    await screen.findByText("SQL 已生成并通过验证");

    await user.click(screen.getByRole("button", { name: "编辑 SQL" }));
    await user.clear(screen.getByLabelText("SQL 编辑器"));
    await user.type(screen.getByLabelText("SQL 编辑器"), "SELECT id FROM orders ORDER BY id");
    await user.click(screen.getByRole("button", { name: "运行修改后的 SQL" }));

    expect(client.runEditedSql).toHaveBeenCalledWith({
      sql: "SELECT id FROM orders ORDER BY id",
      targetDialect: "sqlite"
    });
    expect(await screen.findByText("9 ms")).toBeInTheDocument();
    expect(screen.getByText("7")).toHaveClass("cellNumeric");
  });

  it("创建运行配置后，Schema、查询和手动 SQL 都使用 runtimeConfigId", async () => {
    const user = userEvent.setup();
    const client = buildClient([successResponse]);
    const runtimeSchema: SchemaResponse = {
      tables: {
        runtime_orders: {
          columns: {
            id: { type: "INTEGER", nullable: false }
          }
        }
      }
    };
    vi.mocked(client.getSchema).mockResolvedValueOnce(schemaResponse).mockResolvedValueOnce(runtimeSchema);

    render(<App client={client} />);

    await user.click(screen.getByRole("button", { name: "打开工作台菜单" }));
    await user.click(screen.getByRole("button", { name: "运行配置" }));
    const panel = screen.getByRole("dialog", { name: "运行配置" });
    await screen.findByText("demo_sqlite");
    await user.click(within(panel).getByRole("button", { name: "保存运行配置" }));

    expect(client.createRuntimeConfig).toHaveBeenCalledWith({
      database: { mode: "preset", preset_id: "demo_sqlite" },
      models: {
        light: { mode: "preset", preset_id: "light" },
        strong: { mode: "preset", preset_id: "strong" }
      }
    });
    expect(client.getSchema).toHaveBeenLastCalledWith("rt_frontend");
    expect(await screen.findByText("runtime_orders")).toBeInTheDocument();

    await user.type(screen.getByLabelText("用自然语言描述你需要的数据"), "列出运行时订单");
    await user.click(screen.getByRole("button", { name: "生成并验证" }));

    expect(client.runQuery).toHaveBeenCalledWith({
      question: "列出运行时订单",
      targetDialect: "sqlite",
      runtimeConfigId: "rt_frontend"
    });

    await screen.findByText("SQL 已生成并通过验证");
    await user.click(screen.getByRole("button", { name: "编辑 SQL" }));
    await user.click(screen.getByRole("button", { name: "运行修改后的 SQL" }));

    expect(client.runEditedSql).toHaveBeenCalledWith({
      sql: "SELECT id, amount, NULL AS note FROM orders ORDER BY id",
      targetDialect: "sqlite",
      runtimeConfigId: "rt_frontend"
    });
  });
});
