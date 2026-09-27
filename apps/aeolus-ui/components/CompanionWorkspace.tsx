"use client";

import { useState, type FormEvent } from "react";
import type { ApiPage, Job, Recording } from "@/lib/api-types";
import type { Identity } from "@/lib/platform";
import { safeCompanionId } from "@/lib/companion";
import { CompanionImport } from "./CompanionImport";
import { CompanionPanel } from "./CompanionPanel";
import { PageControls, RequestError } from "./PlatformCommon";

export function CompanionWorkspace({ identity, recordings, jobs, initialRecordingId, loading, onRecordPage, onSubmitted, onDirtyChange }: {
  identity: Identity;
  recordings: ApiPage<Recording> | null;
  jobs: ApiPage<Job> | null;
  initialRecordingId: string;
  loading: boolean;
  onRecordPage: (offset: number) => void;
  onSubmitted: (job: Job) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [draftId, setDraftId] = useState(initialRecordingId);
  const [recordingId, setRecordingId] = useState(initialRecordingId);
  const [error, setError] = useState<string | null>(null);
  function inspect(value: string) {
    if (!safeCompanionId(value)) { setError("Enter the exact recording ID, using at most 128 letters, digits, dots, underscores or hyphens."); return; }
    setError(null); setDraftId(value); setRecordingId(value);
  }
  function submitLookup(event: FormEvent) { event.preventDefault(); inspect(draftId.trim()); }
  function accepted(job: Job) { inspect(job.recording_id); onSubmitted(job); }
  return <div className="platform-stack companion-workspace">
    <CompanionImport identity={identity} onSubmitted={accepted} onDirtyChange={onDirtyChange} />
    <section className="platform-panel" aria-labelledby="companion-lookup-title">
      <header className="platform-heading"><div><h2 id="companion-lookup-title">Inspect imported evidence</h2><p>Retained companions have a separate read path, including pending or failed replay jobs and recordings with no candidates.</p></div></header>
      <div className="inspection-block">
        <form className="platform-filter" onSubmit={submitLookup}><label htmlFor="companion-recording-id">Exact recording ID</label><input id="companion-recording-id" value={draftId} maxLength={128} onChange={(event) => setDraftId(event.target.value)} required /><button type="submit" className="button secondary">Inspect companions</button></form>
        <RequestError message={error} />
        {identity.role !== "device" ? <>
          <label htmlFor="companion-known-recording">Available recordings in this scope</label>
          <select id="companion-known-recording" value={recordings?.items.some((item) => item.recording_id === recordingId) ? recordingId : ""} disabled={loading} onChange={(event) => { if (event.target.value) inspect(event.target.value); }}><option value="">Choose a known recording</option>{recordings?.items.map((recording) => <option key={recording.recording_id} value={recording.recording_id}>{recording.recording_id} · {recording.provenance}</option>)}</select>
          <PageControls page={recordings} onPage={onRecordPage} loading={loading} />
          {jobs?.items.length ? <details className="data-table-disclosure"><summary>Inspect companions from recent processing jobs</summary><div className="platform-record-list">{jobs.items.map((job) => <button type="button" className="recording-row" key={job.id} onClick={() => inspect(job.recording_id)}><strong className="full-identifier">{job.recording_id}</strong><span>{job.status} · {job.id}</span></button>)}</div></details> : null}
        </> : <p className="platform-note">Device credentials can request only evidence in their API-authorized device scope. Enter a known exact recording ID; this view does not enumerate a fleet.</p>}
      </div>
    </section>
    {recordingId ? <CompanionPanel recordingId={recordingId} key={recordingId} /> : <section className="platform-panel inspection-block"><h2>No recording selected</h2><p>Choose a recording or acknowledge a seven-file import to inspect its retained evidence. No acquisition metadata is inferred from an empty selection.</p></section>}
  </div>;
}
