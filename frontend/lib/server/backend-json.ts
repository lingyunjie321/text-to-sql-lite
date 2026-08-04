type ForwardMethod = "GET" | "POST" | "PUT" | "DELETE";

type ForwardBackendJsonOptions = {
  method: ForwardMethod;
  backendUrl?: string;
  apiKey?: string;
  fetchImpl?: typeof fetch;
};

const MODEL_API_PATH = "/api/v1/local/models";
const DATASOURCE_API_PATH = "/api/v1/local/datasources";
const PROFILE_ID_PATTERN = /^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/;

function errorResponse(status: number, code: string, message: string): Response {
  return Response.json({ detail: { code, message } }, { status });
}

function normalizeProfilePath(path: string): string | null {
  const apiPath = path.startsWith(`${DATASOURCE_API_PATH}/`) || path === DATASOURCE_API_PATH
    ? DATASOURCE_API_PATH
    : MODEL_API_PATH;
  if (path === apiPath || path === `${apiPath}/test`) {
    return path;
  }

  const metadataSuffix = apiPath === DATASOURCE_API_PATH ? "/metadata" : "";
  const itemPath = metadataSuffix && path.endsWith(metadataSuffix)
    ? path.slice(0, -metadataSuffix.length)
    : path;
  const profileIdSegment = itemPath.slice(`${apiPath}/`.length);
  if (
    !itemPath.startsWith(`${apiPath}/`) ||
    profileIdSegment.includes("/") ||
    path.includes("?") ||
    path.includes("#")
  ) {
    return null;
  }

  try {
    const profileId = decodeURIComponent(profileIdSegment);
    if (!PROFILE_ID_PATTERN.test(profileId)) return null;
    return `${apiPath}/${encodeURIComponent(profileId)}${
      path.endsWith(metadataSuffix) && metadataSuffix ? metadataSuffix : ""
    }`;
  } catch {
    return null;
  }
}

function backendEndpoint(backendUrl: string, path: string): string {
  return `${backendUrl.replace(/\/$/, "")}${path}`;
}

export async function forwardBackendJson(
  path: string,
  request: Request,
  options: ForwardBackendJsonOptions,
): Promise<Response> {
  const normalizedPath = normalizeProfilePath(path);
  if (normalizedPath === null) {
    return errorResponse(500, "INVALID_BACKEND_PATH", "后端请求路径无效。");
  }

  if (!options.backendUrl) {
    return errorResponse(503, "BACKEND_NOT_CONFIGURED", "后端服务地址未配置。");
  }

  let body: string | undefined;
  if (options.method === "POST" || options.method === "PUT") {
    try {
      body = JSON.stringify(await request.json());
    } catch {
      return errorResponse(400, "INVALID_JSON_BODY", "请求体不是合法的 JSON。");
    }
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (options.apiKey) {
    headers.Authorization = `Bearer ${options.apiKey}`;
  }

  try {
    const upstream = await (options.fetchImpl ?? fetch)(
      backendEndpoint(options.backendUrl, normalizedPath),
      {
        method: options.method,
        headers,
        ...(body === undefined ? {} : { body }),
        ...(options.method === "GET" ? { cache: "no-store" } : {}),
      },
    );

    if (upstream.status === 204) {
      return new Response(null, { status: 204 });
    }

    let data: unknown;
    try {
      data = await upstream.json();
    } catch {
      return errorResponse(
        upstream.status,
        "UPSTREAM_RESPONSE_INVALID",
        "后端响应格式无效。",
      );
    }

    return Response.json(data, { status: upstream.status });
  } catch {
    return errorResponse(502, "BACKEND_UNREACHABLE", "后端服务暂时不可用。");
  }
}
