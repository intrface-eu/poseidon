"use client";

import { useEffect, useState, type FormEvent } from "react";
import type { ApiPage, Recording, Waveform } from "@/lib/api-types";
import { ApiError, apiRequest, jsonRequest } from "@/lib/client-api";
import { canReview, PLATFORM_API, validateObservation, type Identity, type Observation, type ObservationInput, type ObservationLabel } from "@/lib/platform";
import { Ledger, PageControls, RequestError, errorMessage, useResource } from "./PlatformCommon";
import { WaveformChart } from "./WaveformChart";

const labels: Record<ObservationLabel, string> = { feeding_observed: "Feeding observed", no_feeding_observed: "No feeding observed", uncertain: "Uncertain", not_visible: "Not visible" };
const fromRow = (row: Observation): ObservationInput => ({ id: row.id, start_s: row.start_s, end_s: row.end_s, label: row.label, notes: row.notes, observer: row.observer, expected_revision: row.revision, ...(row.review_context ? { review_context: row.review_context } : {}) });

export function ObservationPanel({ recording, identity, onDirtyChange }: { recording: Recording; identity: Identity; onDirtyChange: (dirty: boolean) => void }) {
  const base = `${PLATFORM_API}/recordings/${encodeURIComponent(recording.recording_id)}/observations`;
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const list = useResource<ApiPage<Observation>>(`${base}?limit=25&offset=${offset}`, version);
  const waveform = useResource<Waveform>(`${PLATFORM_API}/recordings/${encodeURIComponent(recording.recording_id)}/waveform?points=512`, version);
  const [selected, setSelected] = useState<Observation | null>(null);
  const [draft, setDraft] = useState<ObservationInput | null>(null);
  const [baseline, setBaseline] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Observation | null>(null);
  const [conflictPending, setConflictPending] = useState(false);
  const [historyOffset, setHistoryOffset] = useState(0);
  const history = useResource<ApiPage<Observation>>(selected ? `${base}/${encodeURIComponent(selected.id)}/history?limit=10&offset=${historyOffset}` : null, version);
  const dirty = draft !== null && JSON.stringify(draft) !== baseline;
  const writable = canReview(identity);
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  function open(row: Observation | null) {
    if (dirty && !window.confirm("Discard the unsaved independent observation draft?")) return;
    const next = row ? fromRow(row) : { id: `obs-${crypto.randomUUID()}`, start_s: 0, end_s: recording.duration_s, label: "uncertain" as const, notes: "", observer: "", expected_revision: 0 };
    setSelected(row); setDraft(next); setBaseline(row ? JSON.stringify(next) : ""); setHistoryOffset(0); setConflict(null); setConflictPending(false); setError(null); setSaved(null);
  }
  async function loadConflict(id: string) {
    try {
      const first = await apiRequest<ApiPage<Observation>>(`${base}/${encodeURIComponent(id)}/history?limit=1&offset=0`);
      const latest = first.total > 1 ? await apiRequest<ApiPage<Observation>>(`${base}/${encodeURIComponent(id)}/history?limit=1&offset=${first.total - 1}`) : first;
      if (!latest.items[0]) throw new Error("empty history");
      setConflict(latest.items[0]); setSelected(latest.items[0]); setConflictPending(false);
      setError("A newer revision exists. Compare it with your preserved draft before choosing a resolution.");
    } catch {
      setConflictPending(true); setError("Revision conflict. Your draft is preserved, but the latest record could not be loaded. Retry the comparison; no overwrite is available yet.");
    }
  }
  async function save(expectedRevision: number) {
    if (!draft || !writable) return;
    const input = { ...draft, expected_revision: expectedRevision, ...(draft.review_context ? { review_context: { ...draft.review_context, evidence_refs: draft.review_context.evidence_refs.map((value) => value.trim()).filter(Boolean) } } : {}) };
    const validation = validateObservation(input, recording.duration_s);
    if (validation) { setError(validation); return; }
    setSaving(true); setError(null); setSaved(null);
    try {
      const row = await apiRequest<Observation>(expectedRevision === 0 ? base : `${base}/${encodeURIComponent(draft.id)}`, jsonRequest(expectedRevision === 0 ? "POST" : "PUT", input));
      const next = fromRow(row);
      setDraft(next); setBaseline(JSON.stringify(next)); setSelected(row); setConflict(null); setConflictPending(false); setVersion((value) => value + 1); setSaved(`Observation saved at revision ${row.revision}.`);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) { setConflictPending(true); await loadConflict(draft.id); }
      else setError(errorMessage(caught));
    } finally { setSaving(false); }
  }
  function submit(event: FormEvent) { event.preventDefault(); if (draft && !conflict && !conflictPending) void save(draft.expected_revision); }
  function update<K extends keyof ObservationInput>(key: K, value: ObservationInput[K]) { setDraft((current) => current ? { ...current, [key]: value } : current); }

  return <section className="platform-panel observations-panel" aria-labelledby="observations-title">
    <header className="platform-heading"><div><h2 id="observations-title">Independent observation intervals</h2><p>Record what a human observed anywhere in this recording, including intervals with no detector candidate.</p></div><button type="button" className="button primary" disabled={!writable || saving} onClick={() => open(null)}>New observation</button></header>
    <div className="inspection-block">
      <Ledger rows={[["Recording ID", recording.recording_id], ["Source SHA-256", recording.wav_sha256], ["Source", <span key="source" className={`tag ${recording.provenance}`}>{recording.provenance}</span>], ["Duration (s)", recording.duration_s], ["Authenticated actor", identity.subject], ["Auth mode", identity.auth_mode]]} />
      <p className="platform-note">Observer names are declared. The API records the authenticated actor and immutable source separately. These are human reports, not detector conclusions or proven ground truth.</p>
      {!writable ? <p className="boundary-note">Your {identity.role} role can read observations but cannot save them.</p> : null}
      <RequestError message={list.error} retry={() => setVersion((value) => value + 1)} />
      {list.loading ? <p role="status">Loading observation intervals…</p> : null}
      {list.data?.items.length === 0 ? <p className="list-empty">No independent observations on this recording. Absence of an observation does not mean absence of feeding.</p> : null}
      <div className="platform-record-list">{list.data?.items.map((row) => <button key={row.id} type="button" className={`recording-row ${selected?.id === row.id ? "selected" : ""}`} onClick={() => open(row)} disabled={saving}><strong>{row.start_s}–{row.end_s} s · {labels[row.label]} · revision {row.revision}</strong><span className="full-identifier">{row.id}</span><span>Declared observer: {row.observer} · Actor: {row.actor_subject}</span></button>)}</div>
      <PageControls page={list.data} onPage={setOffset} loading={list.loading} />
    </div>
    <div className="inspection-block">
      {waveform.data ? <WaveformChart waveform={waveform.data} interval={draft && Number.isFinite(draft.start_s) && Number.isFinite(draft.end_s) ? { start_s: draft.start_s, end_s: draft.end_s, label: "Observation draft" } : undefined} /> : <RequestError message={waveform.error} retry={() => setVersion((value) => value + 1)} />}
    </div>
    {draft ? <div className="inspection-block">
      <h3>{selected ? "Revise independent observation" : "New independent observation"}</h3>
      <p className="full-identifier">{draft.id}</p>
      <form className="platform-form" onSubmit={submit}>
        <fieldset disabled={saving || !writable}>
          <label>Start (seconds)<input type="number" step="any" min="0" max={recording.duration_s} required value={Number.isNaN(draft.start_s) ? "" : draft.start_s} onChange={(event) => update("start_s", event.target.valueAsNumber)} /></label>
          <label>End (seconds)<input type="number" step="any" min="0" max={recording.duration_s} required value={Number.isNaN(draft.end_s) ? "" : draft.end_s} onChange={(event) => update("end_s", event.target.valueAsNumber)} /></label>
          <label>Interval label<select value={draft.label} onChange={(event) => update("label", event.target.value as ObservationLabel)}>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>Declared observer<input value={draft.observer} required maxLength={80} onChange={(event) => update("observer", event.target.value)} /></label>
          <label className="full">Observation notes<textarea aria-label="Observation notes" value={draft.notes} maxLength={2000} required={draft.label === "feeding_observed"} onChange={(event) => update("notes", event.target.value)} /></label>
          <label className="full"><span><input type="checkbox" checked={Boolean(draft.review_context)} onChange={(event) => update("review_context", event.target.checked ? { protocol_id: null, evidence_refs: [], visibility: "unknown", sync_uncertainty_s: null, reviewed_coverage: false } : undefined)} /> Include independent review context</span></label>
          {draft.review_context ? <>
            <label>Review protocol ID (optional)<input value={draft.review_context.protocol_id ?? ""} maxLength={128} onChange={(event) => update("review_context", { ...draft.review_context!, protocol_id: event.target.value || null })} /></label>
            <label>Visibility<select value={draft.review_context.visibility} onChange={(event) => update("review_context", { ...draft.review_context!, visibility: event.target.value as "clear" | "limited" | "not_visible" | "unknown" })}><option value="unknown">Unknown</option><option value="clear">Clear</option><option value="limited">Limited</option><option value="not_visible">Not visible</option></select></label>
            <label>Evidence reference IDs (comma-separated)<input value={draft.review_context.evidence_refs.join(",")} onChange={(event) => update("review_context", { ...draft.review_context!, evidence_refs: event.target.value.split(",") })} /></label>
            <label>Sync uncertainty (seconds; empty is unknown)<input type="number" min="0" step="any" value={draft.review_context.sync_uncertainty_s ?? ""} onChange={(event) => update("review_context", { ...draft.review_context!, sync_uncertainty_s: event.target.value === "" ? null : event.target.valueAsNumber })} /></label>
            <label className="full"><span><input type="checkbox" checked={draft.review_context.reviewed_coverage} onChange={(event) => update("review_context", { ...draft.review_context!, reviewed_coverage: event.target.checked })} /> I independently reviewed this interval as coverage</span></label>
          </> : null}
          <p className="platform-note full">Missing context is unknown, not scoreable exposure. Reviewed coverage alone does not meet an evaluation protocol or establish usable ground truth.</p>
        </fieldset>
        {conflict || conflictPending ? <div className="inline-message warning full" role="alert"><strong>Revision conflict. Draft preserved.</strong><span>{error}</span>{conflict ? <><div className="conflict-comparison"><section className="conflict-version"><h4>Latest server observation</h4><ObservationRecord row={conflict} /></section><section className="conflict-version"><h4>Your preserved interval</h4><Ledger rows={[["Interval (s)", `${draft.start_s}–${draft.end_s}`], ["Label", draft.label], ["Observer", draft.observer], ["Notes", draft.notes], ["Review context", draft.review_context ? JSON.stringify(draft.review_context, null, 2) : "Unknown"]]} /></section></div><div className="conflict-actions"><button className="button secondary" type="button" disabled={saving} onClick={() => { const next = fromRow(conflict); setDraft(next); setBaseline(JSON.stringify(next)); setConflict(null); setError(null); }}>Replace draft with server observation</button><button className="button primary" type="button" disabled={saving || !writable} onClick={() => void save(conflict.revision)}>Save my draft over revision {conflict.revision}</button></div><p>Saving appends a revision only if the displayed server revision is still current.</p></> : <button type="button" className="button secondary" disabled={saving} onClick={() => void loadConflict(draft.id)}>Reload conflict comparison</button>}</div> : <RequestError message={error} />}
        <div className="form-actions full"><span>{dirty ? "Unsaved independent observation" : `Revision ${draft.expected_revision}`}</span><button type="submit" className="button primary" disabled={saving || !writable || !dirty || Boolean(conflict) || conflictPending}>{saving ? "Saving observation…" : "Save observation"}</button></div>
        {saved ? <p role="status">{saved}</p> : null}
      </form>
    </div> : null}
    {selected ? <div className="inspection-block"><h3>Observation revision history</h3><p className="platform-note">Append-only server records, oldest first. Source identity stays attached to every revision.</p><RequestError message={history.error} retry={() => setVersion((value) => value + 1)} />{history.loading ? <p role="status">Loading history…</p> : null}{history.data?.items.map((row) => <details className="data-table-disclosure" key={row.revision}><summary>Revision {row.revision} · {row.updated_at} · actor {row.actor_subject}</summary><ObservationRecord row={row} /></details>)}<PageControls page={history.data} onPage={setHistoryOffset} /></div> : null}
  </section>;
}
function ObservationRecord({ row }: { row: Observation }) {
  return <Ledger rows={[["Observation ID", row.id], ["Recording ID", row.recording_id], ["Revision", row.revision], ["Interval (s)", `${row.start_s}–${row.end_s}`], ["Label", row.label], ["Observer", row.observer], ["Actor", row.actor_subject], ["Auth mode", row.auth_mode], ["Created", row.created_at], ["Updated", row.updated_at], ["Source", row.provenance.source_kind], ["SHA-256", row.provenance.recording_sha256], ["Review context", row.review_context ? JSON.stringify(row.review_context, null, 2) : "Unknown; not scoreable exposure"], ["Notes", <span key="notes" className="conflict-notes">{row.notes || "No notes"}</span>]]} />;
}
