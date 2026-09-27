"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { ApiPage, Job } from "@/lib/api-types";
import { ApiError, apiRequest } from "@/lib/client-api";
import { canAdmin, PLATFORM_API, type AcquisitionSession, type Identity } from "@/lib/platform";
import {
  COMPANION_UPLOAD_ROLES, COMPANION_FILE_LABELS, COMPANION_PART_LIMITS,
  COMPANION_MAX_BYTES, COMPANION_MAX_REQUEST_BYTES, COMPANION_MAX_ADMISSIONS,
  COMPANION_MAX_QUEUE_SLOTS, COMPANION_MAX_RETAINED_BYTES,
  companionFormData, companionProblem, validateCompanionSelection, type CompanionUploadRole,
} from "@/lib/companion";
import { Ledger, PageControls, RequestError, useResource } from "./PlatformCommon";

export function CompanionImport({ identity, onSubmitted, onDirtyChange }: {
  identity: Identity;
  onSubmitted: (job: Job) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const admin = canAdmin(identity);
  const [offset, setOffset] = useState(0);
  const [sessionId, setSessionId] = useState("");
  const [version, setVersion] = useState(0);
  const sessions = useResource<ApiPage<AcquisitionSession>>(admin ? `${PLATFORM_API}/acquisition-sessions?limit=25&offset=${offset}` : null, version);
  const session = useResource<AcquisitionSession>(admin && sessionId ? `${PLATFORM_API}/acquisition-sessions/${encodeURIComponent(sessionId)}` : null, version);
  const [files, setFiles] = useState<Partial<Record<CompanionUploadRole, File>>>({});
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [authorizationLost, setAuthorizationLost] = useState(false);
  const [problem, setProblem] = useState<ReturnType<typeof companionProblem> | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const request = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; request.current?.abort(); onDirtyChange(false); };
  }, [onDirtyChange]);
  const blocked = !admin || busy || authorizationLost;

  function chooseFile(role: CompanionUploadRole, file: File | undefined) {
    setFiles((current) => {
      const next = { ...current };
      if (file) next[role] = file; else delete next[role];
      return next;
    });
    setDirty(true); setProblem(null); setMessage(null);
  }
  function clear() {
    formRef.current?.reset(); setFiles({}); setDirty(false); setMessage(null); if (!authorizationLost) setProblem(null);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (blocked || !session.data || session.data.id !== sessionId) return;
    const invalid = validateCompanionSelection(files, sessionId);
    if (invalid) { setProblem(companionProblem(new ApiError(400, "file_selection", invalid))); return; }
    // Only fixed file roles are appended. Context comes from the URL, never a scalar part.
    const body = companionFormData(files);
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setProblem(null); setMessage(null);
    try {
      const job = await apiRequest<Job>(`${PLATFORM_API}/acquisition-sessions/${encodeURIComponent(sessionId)}/recordings`, { method: "POST", body, signal: controller.signal });
      if (!job || typeof job.id !== "string" || typeof job.recording_id !== "string" || !["queued", "running", "succeeded", "failed"].includes(job.status)) throw new ApiError(502, "invalid_job_response", "The API did not return the expected job acknowledgement.");
      if (!mounted.current) return;
      setDirty(false);
      setMessage(`Request acknowledged. Job ${job.id} reports ${job.status}. Exact qualified retries may return the original job; stored provenance is not replaced.`);
      onSubmitted(job);
    } catch (caught) {
      if (mounted.current) { const next = companionProblem(caught); setProblem(next); if (next.authLost) setAuthorizationLost(true); }
    } finally {
      if (mounted.current) setBusy(false);
      if (request.current === controller) request.current = null;
    }
  }

  return <section className="platform-panel companion-import" aria-labelledby="companion-import-title">
    <header className="platform-heading"><div><h2 id="companion-import-title">Import one selected export</h2><p>Seven original files from one committed segment export. This is separate from the legacy two-file importer and never falls back to it.</p></div></header>
    <div className="inspection-block">
      <p className="platform-note">An existing platform session supplies authorization scope. It does not replace the source capture-session ID or override imported clock, epoch or origin declarations.</p>
      {!admin ? <div className="inline-message warning"><strong>Admin upload only.</strong><span>Your {identity.role} identity can inspect evidence within its API scope, but cannot submit this import.</span></div> : null}
      <div className="companion-session-picker">
        <label htmlFor="companion-platform-session">Existing platform session</label>
        <select id="companion-platform-session" value={sessionId} disabled={blocked || sessions.loading} onChange={(event) => { setSessionId(event.target.value); setProblem(null); setMessage(null); if (Object.keys(files).length) setDirty(true); }}>
          <option value="">{admin ? "Select an authorized manual context" : "Admin role required to select upload context"}</option>
          {sessionId && !sessions.data?.items.some((item) => item.id === sessionId) ? <option value={sessionId}>{sessionId}</option> : null}
          {sessions.data?.items.map((item) => <option key={item.id} value={item.id}>{item.id} · site {item.site_id}</option>)}
        </select>
      </div>
      <RequestError message={sessions.error ?? session.error} retry={() => setVersion((value) => value + 1)} />
      {admin && sessions.data?.items.length === 0 ? <p className="platform-note">No authorized sessions on this page. Declare the required manual context under Acquisition sessions first; this form does not create or enroll a device.</p> : null}
      <PageControls page={sessions.data} onPage={setOffset} loading={busy || sessions.loading} />
      {session.data ? <Ledger rows={[["Manual platform context ID", session.data.id], ["Authorized site", session.data.site_id], ["Declared context device", session.data.device_id ?? "Not bound"], ["Declared context source", session.data.provenance.source_id], ["Declared source kind", session.data.provenance.source_kind]]} /> : null}
      <form className="platform-form companion-import-form" onSubmit={submit} ref={formRef}>
        <fieldset disabled={blocked}>
          {COMPANION_UPLOAD_ROLES.map((role) => <div className="field-group" key={role}>
            <label htmlFor={`companion-file-${role}`}>{COMPANION_FILE_LABELS[role]} ({role})</label>
            <input id={`companion-file-${role}`} name={role} type="file" required accept={role === "wav" ? "audio/wav,.wav" : "application/json,.json"} aria-describedby={`companion-limit-${role}`} onChange={(event) => chooseFile(role, event.target.files?.[0])} />
            <small id={`companion-limit-${role}`}>At most {COMPANION_PART_LIMITS[role]} bytes. Keep the original export basename.</small>
          </div>)}
        </fieldset>
        <div className="form-actions"><span>{dirty ? "Unsubmitted file selection" : "Files stay selected after acknowledgement for an exact retry."}</span><div className="conflict-actions"><button type="button" className="button secondary" onClick={clear} disabled={busy}>Clear file selection</button><button type="submit" className="button primary" disabled={blocked || !session.data || session.loading}>{busy ? "Submitting selected export…" : "Import selected export"}</button></div></div>
      </form>
      {problem ? <div className={`inline-message ${problem.status === 409 ? "warning" : "error"} companion-problem`} role="alert"><strong>{problem.title}.</strong><span>{problem.detail}</span><span>Files have not been changed or truncated. No legacy fallback was attempted.</span>{problem.authLost ? <span>Lock and unlock the workspace with an authorized credential before another submission.</span> : <span>Review the target context and all seven original files before retrying. A lost acknowledgement may require checking the retained record or job.</span>}</div> : null}
      {message ? <p className="companion-acknowledgement full-identifier" role="status">{message}</p> : null}
      <details className="data-table-disclosure"><summary>Local limits and verification boundary</summary><div className="inspection-block"><Ledger rows={[["Selected exports per request", "1"], ["Multipart parts", "7 files; 0 scalar fields"], ["Five companion files combined (bytes)", COMPANION_MAX_BYTES], ["Actual request cap (bytes)", COMPANION_MAX_REQUEST_BYTES], ["Concurrent route admissions", COMPANION_MAX_ADMISSIONS], ["Shared queued/running/preparing slots", COMPANION_MAX_QUEUE_SLOTS], ["Retained + reserved companion logical bytes", COMPANION_MAX_RETAINED_BYTES]]} /><p className="platform-note">These are local software limits, not disk/RSS guarantees or physical acquisition settings. No metadata truncation, batch/archive intake, silent backfill or automatic eviction. The Acquisition reader checks delivered structure and consistency; it does not attest omitted source bytes, clock accuracy, calibration, origin or permissions.</p></div></details>
    </div>
  </section>;
}
