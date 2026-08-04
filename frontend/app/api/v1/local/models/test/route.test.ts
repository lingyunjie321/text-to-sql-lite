import { afterEach, describe, expect, it, vi } from "vitest";

import * as modelTestRoute from "./route";

type Method = "POST" | "GET" | "PUT" | "DELETE";
type RouteHandler = (request: Request) => Promise<Response>;

const backendUrl = "http://127.0.0.1:8000";
const profileBody = {
  id: "test",
  name: "Test profile",
  provider_type: "openai_compatible",
  base_url: "http://localhost:11434/v1",
  model_name: "qwen2.5-coder",
};
const connectionBody = {
  provider_type: "openai_compatible",
  base_url: "http://localhost:11434/v1",
  model_name: "qwen2.5-coder",
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("model test static route method matrix", () => {
  it.each([
    ["POST", connectionBody, 200],
    ["GET", undefined, 200],
    ["PUT", profileBody, 200],
    ["DELETE", undefined, 204],
  ] as const)(
    "uses %s for the connection test or Profile ID test item operation",
    async (method, body, expectedStatus) => {
      vi.stubEnv("TEXT_TO_SQL_API_URL", backendUrl);
      const fetchMock = vi.fn<typeof fetch>().mockImplementation(
        async (_input, init) => {
          if (init?.method === "DELETE") {
            return new Response(null, { status: 204 });
          }
          return Response.json(
            init?.method === "POST"
              ? {
                  generation: "connected",
                  embedding: "not_configured",
                  embedding_error: null,
                }
              : profileBody,
          );
        },
      );
      vi.stubGlobal("fetch", fetchMock);

      const handler = (modelTestRoute as unknown as Record<Method, unknown>)[
        method
      ];
      expect(typeof handler).toBe("function");
      const response = await (handler as RouteHandler)(
        new Request("http://localhost/api/v1/local/models/test", {
          method,
          headers: body
            ? { "Content-Type": "application/json" }
            : undefined,
          body: body ? JSON.stringify(body) : undefined,
        }),
      );

      expect(response.status).toBe(expectedStatus);
      expect(fetchMock).toHaveBeenCalledWith(
        `${backendUrl}/api/v1/local/models/test`,
        expect.objectContaining({
          method,
          ...(body ? { body: JSON.stringify(body) } : {}),
        }),
      );
      if (body === undefined) {
        expect(fetchMock.mock.calls[0]?.[1]?.body).toBeUndefined();
      }
    },
  );
});
