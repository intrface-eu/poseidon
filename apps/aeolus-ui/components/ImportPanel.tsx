"use client";

import { FormEvent, useRef, useState } from "react";
import type { Job } from "@/lib/api-types";
import { ApiError, apiRequest } from "@/lib/client-api";

const MAX_WAV_BYTES = 64 * 1024 * 1024;
const MAX_MANIFEST_BYTES = 16 * 1024;

export function ImportPanel({
  empty,
  onSubmitted,
  allowed = true,
}: {
  empty: boolean;
  allowed?: boolean;
  onSubmitted: (job: Job) => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [submitting, setSubmitting] = useState<"demo" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(empty);

  async function loadDemo() {
    if (!allowed) return;
    setSubmitting("demo");
    setError(null);
    try {
      const job = await apiRequest<Job>("/api/backend/api/v1/demo", { method: "POST" });
      onSubmitted(job);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The synthetic demo could not be submitted.");
    } finally {
      setSubmitting(null);
    }
  }

  async function importFiles(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!allowed) return;
    const form = new FormData(event.currentTarget);
    const wav = form.get("wav");
    const manifest = form.get("manifest");
    if (!(wav instanceof File) || wav.size === 0 || !(manifest instanceof File) || manifest.size === 0) {
      setError("Choose one WAV file and its recording manifest.");
      return;
    }
    if (wav.size > MAX_WAV_BYTES) {
      setError("The WAV exceeds the 64 MiB development limit.");
      return;
    }
    if (manifest.size > MAX_MANIFEST_BYTES) {
      setError("The manifest exceeds the 16 KiB development limit.");
      return;
    }

    setSubmitting("import");
    setError(null);
    try {
      const job = await apiRequest<Job>("/api/backend/api/v1/recordings", {
        body: form,
        method: "POST",
      });
      formRef.current?.reset();
      setExpanded(false);
      onSubmitted(job);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The recording could not be submitted.");
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <section className={`intake-panel ${empty ? "empty-intake" : ""}`} aria-labelledby="intake-title">
      <div className="intake-heading">
        <div>
          <h2 id="intake-title">{empty ? "Start with traceable evidence" : "Add evidence"}</h2>
          <p>
            {empty
              ? "This workspace has no recordings. Use the marked synthetic fixture or import a WAV with its exact manifest."
              : "Submit another declared recording or reload the deterministic synthetic fixture."}
          </p>
        </div>
        <div className="intake-actions">
          <button className="button primary" type="button" onClick={loadDemo} disabled={!allowed || submitting !== null}>
            {submitting === "demo" ? "Submitting demo…" : "Load synthetic demo"}
          </button>
          <button className="button secondary" type="button" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded} disabled={!allowed}>
            {expanded ? "Close import" : "Import WAV + manifest"}
          </button>
        </div>
      </div>

      {expanded ? (
        <form className="file-intake" onSubmit={importFiles} ref={formRef}>
          <div className="field-group">
            <label htmlFor="wav-file">WAV recording</label>
            <input id="wav-file" name="wav" type="file" accept="audio/wav,.wav" required disabled={!allowed || submitting !== null} />
            <small>PCM16 WAV, up to 64 MiB and 30 minutes.</small>
          </div>
          <div className="field-group">
            <label htmlFor="manifest-file">Recording manifest</label>
            <input id="manifest-file" name="manifest" type="file" accept="application/json,.json" required disabled={!allowed || submitting !== null} />
            <small>Version 1 JSON manifest, up to 16 KiB.</small>
          </div>
          <button className="button primary" type="submit" disabled={!allowed || submitting !== null}>
            {submitting === "import" ? "Uploading evidence…" : "Submit recording"}
          </button>
        </form>
      ) : null}

      {error ? (
        <div className="inline-message error" role="alert">
          <strong>Evidence not submitted.</strong>
          <span>{error}</span>
        </div>
      ) : null}
      {!allowed ? <p className="platform-note">Unbound WAV import and demo loading require the local development key. Scoped credentials can inspect only evidence bound to their sites.</p> : null}
      <p className="synthetic-rule">
        <span className="tag synthetic">Synthetic</span>
        The fixture remains marked in recordings, events, and review context.
      </p>
    </section>
  );
}
