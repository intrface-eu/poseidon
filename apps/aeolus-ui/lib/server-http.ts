import { NextResponse } from "next/server";

export const SESSION_COOKIE = "poseidon_session";
export const SESSION_MAX_AGE_SECONDS = 8 * 60 * 60;

export type ErrorCode =
  | "bad_request"
  | "body_too_large"
  | "backend_timeout"
  | "backend_unavailable"
  | "invalid_access_key"
  | "method_not_allowed"
  | "not_authenticated"
  | "origin_rejected"
  | "proxy_path_rejected"
  | "server_configuration";

export function errorResponse(status: number, code: ErrorCode, message: string) {
  return NextResponse.json({ error: { code, message } }, { status });
}

function publicLoopbackOrigin(request: Request): string | null {
  const host = request.headers.get("host");
  if (!host) return null;
  const match = /^(?:localhost|127\.0\.0\.1)(?::([1-9]\d{0,4}))?$/i.exec(host)
    ?? /^\[::1\](?::([1-9]\d{0,4}))?$/i.exec(host);
  if (!match) return null;
  const port = match[1];
  if (port && Number(port) > 65_535) return null;
  try {
    const protocol = new URL(request.url).protocol;
    if (protocol !== "http:" && protocol !== "https:") return null;
    return new URL(`${protocol}//${host.toLowerCase()}`).origin;
  } catch {
    return null;
  }
}

export function hasSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const expected = publicLoopbackOrigin(request);
  if (!origin || !expected) return false;
  try {
    const supplied = new URL(origin);
    if (supplied.username || supplied.password || supplied.pathname !== "/" || supplied.search || supplied.hash) {
      return false;
    }
    return supplied.origin === expected;
  } catch {
    return false;
  }
}

export function backendBaseUrl(): URL {
  const configured = process.env.POSEIDON_API_URL ?? "http://127.0.0.1:8080";
  const url = new URL(configured);
  if (!/^https?:$/.test(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error("POSEIDON_API_URL must be an HTTP(S) origin without credentials");
  }
  url.pathname = url.pathname.replace(/\/+$/, "");
  return url;
}

export function secureCookie(request: Request): boolean {
  return new URL(request.url).protocol === "https:";
}
