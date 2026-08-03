import { describe, expect, it, vi } from "vitest";
import { forwardBackendJson } from "./backend-json";

const backendUrl = "http://127.0.0.1:8000";

function incomingRequest(body?: string): Request {
  return new Request("http://localhost/api/v1/local/models", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer browser-supplied-value",
    },
    body,
  });
}

describe("forwardBackendJson", () => {
  it("injects configured auth without accepting browser headers", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json({ id: "model-1" }),
    );

    await forwardBackendJson(
      "/api/v1/local/models",
      incomingRequest('{"name":"Local model"}'),
      {
        method: "POST",
        backendUrl,
        apiKey: "server-key",
        fetchImpl,
      },
    );

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/local/models",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer server-key",
        },
        body: '{"name":"Local model"}',
      }),
    );
  });

  it("returns a stable error for a non-json upstream response", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response("not JSON", { status: 502 }),
    );

    const response = await forwardBackendJson(
      "/api/v1/local/models",
      incomingRequest('{"name":"Local model"}'),
      { method: "POST", backendUrl, fetchImpl },
    );

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({
      detail: {
        code: "UPSTREAM_RESPONSE_INVALID",
        message: "后端响应格式无效。",
      },
    });
  });

  it("reports a missing backend URL without making a request", async () => {
    const fetchImpl = vi.fn<typeof fetch>();

    const response = await forwardBackendJson(
      "/api/v1/local/models",
      incomingRequest('{"name":"Local model"}'),
      { method: "POST", backendUrl: undefined, fetchImpl },
    );

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      detail: { code: "BACKEND_NOT_CONFIGURED", message: "后端服务地址未配置。" },
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects invalid browser JSON before forwarding", async () => {
    const fetchImpl = vi.fn<typeof fetch>();

    const response = await forwardBackendJson(
      "/api/v1/local/models",
      incomingRequest("{"),
      { method: "POST", backendUrl, fetchImpl },
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      detail: { code: "INVALID_JSON_BODY", message: "请求体不是合法的 JSON。" },
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("preserves a successful empty DELETE response", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    const response = await forwardBackendJson(
      "/api/v1/local/models/model-1",
      new Request("http://localhost/api/v1/local/models/model-1", {
        method: "DELETE",
        body: '{"ignored":true}',
      }),
      { method: "DELETE", backendUrl, fetchImpl },
    );

    expect(response.status).toBe(204);
    await expect(response.text()).resolves.toBe("");
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/local/models/model-1",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(fetchImpl.mock.calls[0]?.[1]?.body).toBeUndefined();
  });

  it("preserves an upstream JSON status", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json({ detail: "invalid profile" }, { status: 422 }),
    );

    const response = await forwardBackendJson(
      "/api/v1/local/models",
      incomingRequest('{"name":"Local model"}'),
      { method: "POST", backendUrl, fetchImpl },
    );

    expect(response.status).toBe(422);
    await expect(response.json()).resolves.toEqual({ detail: "invalid profile" });
  });

  it("does not disclose thrown fetch errors", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockRejectedValue(
      new Error("private upstream hostname"),
    );

    const response = await forwardBackendJson(
      "/api/v1/local/models",
      incomingRequest('{"name":"Local model"}'),
      { method: "POST", backendUrl, fetchImpl },
    );

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({
      detail: { code: "BACKEND_UNREACHABLE", message: "后端服务暂时不可用。" },
    });
  });
});
