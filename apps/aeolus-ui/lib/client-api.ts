import type { ApiErrorPayload } from "./api-types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("accept")) headers.set("accept", "application/json");
  const response = await fetch(path, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    headers,
  });

  const contentType = response.headers.get("content-type") ?? "";
  let payload: unknown = null;
  if (contentType.includes("application/json")) {
    payload = await response.json().catch(() => null);
  } else if (response.status !== 204) {
    payload = await response.text().catch(() => null);
  }

  if (!response.ok) {
    const body = payload as ApiErrorPayload | null;
    const message = body?.error?.message ?? `Request failed with status ${response.status}.`;
    const code = body?.error?.code ?? "request_failed";
    throw new ApiError(response.status, code, message);
  }
  return payload as T;
}

export function jsonRequest(method: "POST" | "PUT" | "DELETE", body?: unknown): RequestInit {
  return {
    body: body === undefined ? undefined : JSON.stringify(body),
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    method,
  };
}
