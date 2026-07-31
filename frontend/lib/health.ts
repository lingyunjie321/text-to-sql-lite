export async function checkBackendHealth(): Promise<{
  healthy: boolean;
  message: string;
}> {
  try {
    const res = await fetch("/api/v1/health", { method: "GET" });
    const data = await res.json();
    return {
      healthy: data?.status === "healthy",
      message:
        data?.status === "healthy" ? "后端服务正常" : "后端服务异常",
    };
  } catch {
    return { healthy: false, message: "无法连接到后端" };
  }
}
