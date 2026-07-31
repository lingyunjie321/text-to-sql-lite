import { afterEach, describe, expect, it, vi } from "vitest";
import { checkBackendHealth } from "./health";

function mockFetchJson(body: unknown, ok = true) {
  return vi.fn().mockResolvedValue({
    ok,
    json: () => Promise.resolve(body),
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("checkBackendHealth", () => {
  it("reports healthy when the BFF responds with status=healthy", async () => {
    vi.stubGlobal("fetch", mockFetchJson({ status: "healthy" }));
    await expect(checkBackendHealth()).resolves.toEqual({
      healthy: true,
      message: "后端服务正常",
    });
  });

  it("reports unhealthy for any other status payload", async () => {
    vi.stubGlobal("fetch", mockFetchJson({ status: "unhealthy" }));
    const result = await checkBackendHealth();
    expect(result.healthy).toBe(false);
    expect(result.message).toBe("后端服务异常");
  });

  it("reports unhealthy when the payload is not an object", async () => {
    vi.stubGlobal("fetch", mockFetchJson(null));
    const result = await checkBackendHealth();
    expect(result.healthy).toBe(false);
  });

  it("reports unreachable when fetch rejects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("connection refused")),
    );
    await expect(checkBackendHealth()).resolves.toEqual({
      healthy: false,
      message: "无法连接到后端",
    });
  });

  it("reports unreachable when the response is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.reject(new SyntaxError("Unexpected token")),
      }),
    );
    const result = await checkBackendHealth();
    expect(result).toEqual({ healthy: false, message: "无法连接到后端" });
  });

  it("calls the BFF health endpoint", async () => {
    const fetchMock = mockFetchJson({ status: "healthy" });
    vi.stubGlobal("fetch", fetchMock);
    await checkBackendHealth();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/health", { method: "GET" });
  });
});
