import { afterEach, describe, expect, it, vi } from "vitest";

import { createTextToSqlClient } from "./client";

describe("createTextToSqlClient", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("runQuery 默认不发送 debug=true", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          request_id: "run_1",
          status: "success",
          attempts: 0,
          retrieved_examples: [],
          rag_context: {
            reference_sql: [],
            documents: [],
            metrics: [],
            semantic_models: []
          },
          repair_history: [],
          errors: [],
          trace: []
        }),
        { status: 200 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    await createTextToSqlClient().runQuery({
      question: "列出订单金额",
      targetDialect: "sqlite"
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.debug).not.toBe(true);
  });
});
