"use client";

import { FormEvent, useState } from "react";
import { ApiError, apiRequest, jsonRequest } from "@/lib/client-api";

export function AccessGate({
  message,
  onAuthenticated,
}: {
  message?: string;
  onAuthenticated: () => void;
}) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(message ?? null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await apiRequest<{ authenticated: true }>("/api/session", jsonRequest("POST", { token }));
      setToken("");
      onAuthenticated();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The local API could not validate this access key.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="access-shell">
      <section className="access-panel" aria-labelledby="access-title">
        <div className="access-brand" aria-hidden="true">
          <span className="brand-mark">A</span>
          <span>AEOLUS</span>
        </div>
        <h1 id="access-title">Unlock the local monitor</h1>
        <p>
          Use this workspace’s development key or a scoped user/device token. The session uses an HttpOnly cookie, not local storage. The API validates the identity and scope.
        </p>
        <form onSubmit={submit} className="access-form">
          <label htmlFor="access-key">Local access key</label>
          <input
            id="access-key"
            name="access-key"
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            required
            disabled={submitting}
          />
          {error ? (
            <div className="inline-message error" role="alert">
              <strong>Access not granted.</strong>
              <span>{error}</span>
            </div>
          ) : null}
          <button className="button primary" type="submit" disabled={submitting || token.length === 0}>
            {submitting ? "Checking access…" : "Unlock workspace"}
          </button>
        </form>
        <div className="boundary-note">
          <strong>Monitor only</strong>
          <span>No acoustic output or field-hardware control exists in this app.</span>
        </div>
      </section>
    </main>
  );
}

export function OfflineGate({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <main className="access-shell">
      <section className="access-panel" aria-labelledby="offline-title">
        <div className="access-brand" aria-hidden="true">
          <span className="brand-mark">A</span>
          <span>AEOLUS</span>
        </div>
        <h1 id="offline-title">Local API unavailable</h1>
        <p>{message}</p>
        <div className="inline-message warning" role="status">
          <strong>Your browser is ready.</strong>
          <span>Start or recover the loopback API, then retry. No workspace data has been replaced.</span>
        </div>
        <button className="button primary" type="button" onClick={onRetry}>
          Retry connection
        </button>
      </section>
    </main>
  );
}

export function LoadingGate() {
  return (
    <main className="access-shell" aria-busy="true">
      <section className="access-panel loading-panel" aria-label="Checking local session">
        <div className="access-brand" aria-hidden="true">
          <span className="brand-mark">A</span>
          <span>AEOLUS</span>
        </div>
        <div className="skeleton line wide" />
        <div className="skeleton line" />
        <div className="skeleton field" />
      </section>
    </main>
  );
}
