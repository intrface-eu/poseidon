import { NextResponse } from "next/server";
import { isIdentity } from "@/lib/platform";
import {
  backendBaseUrl,
  errorResponse,
  hasSameOrigin,
  secureCookie,
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/server-http";

export const runtime = "nodejs";
const MAX_SESSION_BODY_BYTES = 4 * 1024;

function clearSession(response: NextResponse, request: Request) {
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    maxAge: 0,
    path: "/",
    sameSite: "strict",
    secure: secureCookie(request),
  });
}

class SessionBodyTooLarge extends Error {}

async function readSessionBody(request: Request): Promise<{ token?: unknown }> {
  if (!request.body) return {};
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const result = await reader.read();
    if (result.done) break;
    total += result.value.byteLength;
    if (total > MAX_SESSION_BODY_BYTES) {
      await reader.cancel("body limit exceeded");
      throw new SessionBodyTooLarge();
    }
    chunks.push(result.value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as { token?: unknown };
}

export async function POST(request: Request) {
  if (!hasSameOrigin(request)) {
    return errorResponse(403, "origin_rejected", "The session request must come from this application.");
  }
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    return errorResponse(415, "bad_request", "The session request must use JSON.");
  }
  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (!Number.isSafeInteger(declaredLength) || declaredLength < 0 || declaredLength > MAX_SESSION_BODY_BYTES) {
    return errorResponse(413, "body_too_large", "The access-key request is too large.");
  }

  let token: unknown;
  try {
    ({ token } = await readSessionBody(request));
  } catch (error) {
    if (error instanceof SessionBodyTooLarge) {
      return errorResponse(413, "body_too_large", "The access-key request is too large.");
    }
    return errorResponse(400, "bad_request", "Enter the local workspace access key.");
  }
  if (typeof token !== "string" || token.length < 1 || token.length > 4096) {
    return errorResponse(400, "bad_request", "Enter the local workspace access key.");
  }

  let backend: URL;
  try {
    backend = backendBaseUrl();
  } catch {
    return errorResponse(500, "server_configuration", "The local API address is not configured correctly.");
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    const statusUrl = new URL("/api/v1/identity", backend);
    const upstream = await fetch(statusUrl, {
      cache: "no-store",
      headers: {
        accept: "application/json",
        authorization: `Bearer ${token}`,
      },
      signal: controller.signal,
    });
    if (upstream.status === 401 || upstream.status === 403) {
      return errorResponse(401, "invalid_access_key", "The local workspace rejected that access key.");
    }
    if (!upstream.ok) {
      return errorResponse(503, "backend_unavailable", "The local API could not validate this session.");
    }

    if (!isIdentity(await upstream.json())) {
      return errorResponse(503, "backend_unavailable", "The API returned an invalid identity. No session was created.");
    }
    const response = NextResponse.json({ authenticated: true }, { status: 200, headers: { "cache-control": "no-store" } });
    response.cookies.set(SESSION_COOKIE, token, {
      httpOnly: true,
      maxAge: SESSION_MAX_AGE_SECONDS,
      path: "/",
      sameSite: "strict",
      secure: secureCookie(request),
    });
    return response;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return errorResponse(504, "backend_timeout", "The local API did not answer in time.");
    }
    return errorResponse(503, "backend_unavailable", "The local API is offline or unreachable.");
  } finally {
    clearTimeout(timeout);
  }
}

export async function DELETE(request: Request) {
  if (!hasSameOrigin(request)) {
    return errorResponse(403, "origin_rejected", "The session request must come from this application.");
  }
  const response = NextResponse.json({ authenticated: false }, { status: 200 });
  clearSession(response, request);
  return response;
}
