import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { matchBackendRequest } from "@/lib/backend-contract";
import {
  backendBaseUrl,
  errorResponse,
  hasSameOrigin,
  secureCookie,
  SESSION_COOKIE,
} from "@/lib/server-http";

export const runtime = "nodejs";

type RouteContext = { params: Promise<{ path: string[] }> };
type NodeRequestInit = RequestInit & { duplex?: "half" };

const SAFE_REQUEST_HEADERS = ["accept", "content-type", "range"] as const;
const SAFE_RESPONSE_HEADERS = [
  "accept-ranges",
  "cache-control",
  "content-disposition",
  "content-length",
  "content-range",
  "content-type",
  "etag",
  "last-modified",
  "x-poseidon-document-sha256",
] as const;

function contentTypeAllowed(method: string, path: string, request: Request): boolean {
  const value = request.headers.get("content-type")?.toLowerCase() ?? "";
  if (method === "PUT") return value.startsWith("application/json");
  if (method === "POST" && (path === "/api/v1/recordings" || path.endsWith("/video") || /^\/api\/v1\/acquisition-sessions\/[^/]+\/recordings$/.test(path))) {
    return value.startsWith("multipart/form-data;");
  }
  if (method === "POST" && /^\/api\/v1\/lifecycle\/targets\/[^/]+\/(activate|confirm|rollback|recover)$/.test(path)) return true;
  if (method === "POST" && /^\/api\/v1\/alarms\/[^/]+\/acknowledge$/.test(path)) return true;
  if (method === "POST" && !["/api/v1/demo"].includes(path) && !path.endsWith("/rotate") && !path.endsWith("/revoke")) return value.startsWith("application/json");
  return true;
}

function boundedRequestBody(request: Request, limit: number) {
  let exceeded = false;
  if (!request.body || limit === 0) return { body: null, exceeded: () => exceeded };
  const reader = request.body.getReader();
  let total = 0;
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const result = await reader.read();
        if (result.done) {
          controller.close();
          return;
        }
        total += result.value.byteLength;
        if (total > limit) {
          exceeded = true;
          await reader.cancel("body limit exceeded");
          controller.error(new Error("body limit exceeded"));
          return;
        }
        controller.enqueue(result.value);
      } catch (error) {
        controller.error(error);
      }
    },
    cancel(reason) {
      return reader.cancel(reason);
    },
  });
  return { body, exceeded: () => exceeded };
}

function streamedResponseBody(
  upstream: Response,
  clearDeadline: () => void,
): ReadableStream<Uint8Array> | null {
  if (!upstream.body) {
    clearDeadline();
    return null;
  }
  const reader = upstream.body.getReader();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const result = await reader.read();
        if (result.done) {
          clearDeadline();
          controller.close();
          return;
        }
        controller.enqueue(result.value);
      } catch (error) {
        clearDeadline();
        controller.error(error);
      }
    },
    async cancel(reason) {
      clearDeadline();
      await reader.cancel(reason);
    },
  });
}

async function proxy(request: Request, context: RouteContext) {
  const { path: pathParts } = await context.params;
  const incomingUrl = new URL(request.url);
  const match = matchBackendRequest(request.method, pathParts, incomingUrl.searchParams);
  if (!match) {
    return errorResponse(404, "proxy_path_rejected", "That API route is not available through this application.");
  }
  if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method) && !hasSameOrigin(request)) {
    return errorResponse(403, "origin_rejected", "The API request must come from this application.");
  }

  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE)?.value;
  if (!token && match.path !== "/healthz") {
    return errorResponse(401, "not_authenticated", "Unlock the local workspace to continue.");
  }
  if (!contentTypeAllowed(request.method, match.path, request)) {
    return errorResponse(415, "bad_request", "The request content type does not match this API operation.");
  }

  const declaredLengthHeader = request.headers.get("content-length");
  if (declaredLengthHeader !== null) {
    const declaredLength = Number(declaredLengthHeader);
    if (!Number.isSafeInteger(declaredLength) || declaredLength < 0 || declaredLength > match.bodyLimit) {
      return errorResponse(413, "body_too_large", "The upload exceeds the local proxy limit.");
    }
  }

  let backend: URL;
  try {
    backend = backendBaseUrl();
  } catch {
    return errorResponse(500, "server_configuration", "The local API address is not configured correctly.");
  }
  const upstreamUrl = new URL(match.path, backend);
  upstreamUrl.search = incomingUrl.search;

  const headers = new Headers();
  for (const name of SAFE_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Never erase a retained-delivery claim before the K1 server refusal guard.
  if (match.path === "/api/v1/commands" && request.headers.has("x-poseidon-retained")) {
    headers.set("x-poseidon-retained", request.headers.get("x-poseidon-retained")!);
  }
  if (token) headers.set("authorization", `Bearer ${token}`);

  const bounded = boundedRequestBody(request, match.bodyLimit);
  const abort = new AbortController();
  const abortFromClient = () => abort.abort();
  request.signal.addEventListener("abort", abortFromClient, { once: true });
  const timeout = setTimeout(() => abort.abort(), match.timeoutMs);
  const clearDeadline = () => {
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", abortFromClient);
  };

  try {
    const init: NodeRequestInit = {
      body: bounded.body,
      cache: "no-store",
      headers,
      method: request.method,
      redirect: "manual",
      signal: abort.signal,
    };
    if (bounded.body) init.duplex = "half";
    const upstream = await fetch(upstreamUrl, init);
    const responseHeaders = new Headers();
    for (const name of SAFE_RESPONSE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    responseHeaders.set("x-content-type-options", "nosniff");
    responseHeaders.set("cache-control", "no-store");

    const response = new NextResponse(streamedResponseBody(upstream, clearDeadline), {
      headers: responseHeaders,
      status: upstream.status,
      statusText: upstream.statusText,
    });
    if (upstream.status === 401) {
      response.cookies.set(SESSION_COOKIE, "", {
        httpOnly: true,
        maxAge: 0,
        path: "/",
        sameSite: "strict",
        secure: secureCookie(request),
      });
    }
    return response;
  } catch (error) {
    clearDeadline();
    if (bounded.exceeded()) {
      return errorResponse(413, "body_too_large", "The upload exceeds the local proxy limit.");
    }
    if (error instanceof Error && error.name === "AbortError") {
      return errorResponse(504, "backend_timeout", "The local API request did not finish in time.");
    }
    return errorResponse(503, "backend_unavailable", "The local API is offline or unreachable.");
  }
}

export function GET(request: Request, context: RouteContext) {
  return proxy(request, context);
}

export function POST(request: Request, context: RouteContext) {
  return proxy(request, context);
}

export function PUT(request: Request, context: RouteContext) {
  return proxy(request, context);
}
