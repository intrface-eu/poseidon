import { describe, expect, test } from "bun:test";
import { hasSameOrigin, secureCookie } from "./server-http";

function mutation(url: string, host: string, origin?: string) {
  const headers = new Headers({ host });
  if (origin) headers.set("origin", origin);
  return new Request(url, { method: "POST", headers });
}

describe("mutation origin checks", () => {
  test("uses the validated public Host when Next normalizes request.url", () => {
    const request = mutation(
      "http://localhost:3100/api/session",
      "127.0.0.1:3100",
      "http://127.0.0.1:3100",
    );
    expect(hasSameOrigin(request)).toBe(true);
  });

  test("accepts each loopback spelling only at its matching origin and port", () => {
    expect(hasSameOrigin(mutation("http://localhost:3100/api/session", "localhost:3100", "http://localhost:3100"))).toBe(true);
    expect(hasSameOrigin(mutation("http://localhost:3100/api/session", "[::1]:3100", "http://[::1]:3100"))).toBe(true);
    expect(hasSameOrigin(mutation("http://localhost:3100/api/session", "127.0.0.1:3100", "http://localhost:3100"))).toBe(false);
    expect(hasSameOrigin(mutation("http://localhost:3100/api/session", "127.0.0.1:3100", "http://127.0.0.1:3101"))).toBe(false);
  });

  test("rejects missing, malformed, external, and path-bearing origins", () => {
    expect(hasSameOrigin(mutation("http://localhost:3100/api/session", "127.0.0.1:3100"))).toBe(false);
    expect(hasSameOrigin(mutation("http://localhost:3100/api/session", "127.0.0.1:3100", "null"))).toBe(false);
    expect(hasSameOrigin(mutation("http://localhost:3100/api/session", "example.com:3100", "http://example.com:3100"))).toBe(false);
    expect(hasSameOrigin(mutation("http://localhost:3100/api/session", "localhost.evil:3100", "http://localhost.evil:3100"))).toBe(false);
    expect(hasSameOrigin(mutation("http://localhost:3100/api/session", "127.0.0.1:3100", "http://127.0.0.1:3100/path"))).toBe(false);
    expect(hasSameOrigin(mutation("http://localhost:3100/api/session", "127.0.0.1:99999", "http://127.0.0.1:99999"))).toBe(false);
  });

  test("does not trust a client-supplied forwarded protocol for cookie security", () => {
    const httpRequest = mutation("http://localhost:3100/api/session", "localhost:3100", "http://localhost:3100");
    httpRequest.headers.set("x-forwarded-proto", "https");
    expect(secureCookie(httpRequest)).toBe(false);
    expect(secureCookie(mutation("https://localhost/api/session", "localhost", "https://localhost"))).toBe(true);
  });
});
