"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, apiRequest } from "@/lib/client-api";
import { PLATFORM_API } from "@/lib/platform";
import {
  companionDownloadBlob, companionProblem, evidenceText, isCompanionEnvelope,
  type AcquisitionCompanion, type CompanionDocument, type CompanionRetained,
} from "@/lib/companion";
import { Ledger } from "./PlatformCommon";

export function CompanionPanel({ recordingId }: { recordingId: string }) {
  const [value, setValue] = useState<AcquisitionCompanion | null>(null);
  const [problem, setProblem] = useState<ReturnType<typeof companionProblem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    let active = true;
    const current = ++generation.current;
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setProblem(null);
    apiRequest<unknown>(`${PLATFORM_API}/recordings/${encodeURIComponent(recordingId)}/acquisition-companion`, { signal: controller.signal })
      .then((result) => {
        if (!active || current !== generation.current) return;
        if (!isCompanionEnvelope(result, recordingId)) throw new ApiError(502, "invalid_companion_response", "The API returned an unsupported companion response. No source claims were inferred.");
        setValue(result);
      })
      .catch((caught) => {
        if (active && current === generation.current && !controller.signal.aborted) { setValue(null); setProblem(companionProblem(caught)); }
      })
      .finally(() => { if (active && current === generation.current) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [recordingId, version]);
  useEffect(() => {
    if (loading || problem || value?.state !== "retained" || !["queued", "running"].includes(value.job.status)) return;
    const timer = setTimeout(() => setVersion((current) => current + 1), 1200);
    return () => clearTimeout(timer);
  }, [loading, problem, value]);
  function reload() { generation.current += 1; setVersion((current) => current + 1); }
  function downloadFailed(caught: unknown) {
    generation.current += 1; request.current?.abort(); setValue(null); setLoading(false); setProblem(companionProblem(caught));
  }
  return <section className="platform-panel companion-panel" aria-labelledby="companion-retained-title" aria-busy={loading}>
    <header className="platform-heading"><div><h2 id="companion-retained-title">Retained acquisition companions</h2><p className="full-identifier">{recordingId}</p></div><button type="button" className="button secondary" onClick={reload} disabled={loading}>Refresh retained evidence</button></header>
    {problem ? <div className="inspection-block"><div className="inline-message error" role="alert"><strong>{problem.title}.</strong><span>{problem.detail}</span><span>{problem.authLost ? "No retained evidence is shown for this failed authorization check. A record may be absent or outside your scope." : "The request did not complete. Retry without changing the source package or its declarations."}</span></div></div> : null}
    {loading && !value ? <div className="inspection-block" role="status">Loading scoped companion metadata…</div> : null}
    {value?.state === "absent" ? <div className="inspection-block"><h3>Legacy record: companions not retained</h3><p>No acquisition companion documents were retained for this recording. Their timing, channel identities and acquisition coverage are unknown here, not proof of a complete or failed capture.</p><p className="platform-note">This read does not backfill or rescope legacy evidence. The original recording and candidate formats remain unchanged.</p></div> : null}
    {value?.state === "retained" ? <RetainedCompanionView value={value} onDownloadError={downloadFailed} /> : null}
  </section>;
}

export function RetainedCompanionView({ value, onDownloadError }: { value: CompanionRetained; onDownloadError: (caught: unknown) => void }) {
  const binding = value.binding;
  const source = binding.source;
  const clock = source.clock;
  const time = binding.time;
  const epoch = time.epoch_declaration;
  const receipt = binding.original_receipt.record;
  const readerChecks = value.validation.verification;
  return <>
    <div className="inspection-block">
      <div className="inline-message warning companion-coverage" role="note"><strong>Stored segments only; trailing capture extent is not attested.</strong><span>Acquisition completeness remains unverified. Delivered-file structure and consistency do not verify the original input, omitted session bytes, physical channels, calibration, clock, epoch, origin or permissions.</span><span>Unsigned hashes do not authenticate an exporter or its declarations. The authenticated importer is recorded separately below.</span></div>
      <div className="companion-processing" role="status"><strong>Replay processing: {value.job.status}</strong><span className="full-identifier">{value.job.id}</span>{value.job.status === "queued" || value.job.status === "running" ? <p>Companions are retained while replay is pending. This is not yet an available recording or a complete capture claim.</p> : value.job.status === "failed" ? <p>Replay failed. Retained companions remain inspectable; failure does not erase them or establish capture completeness. No candidate availability is claimed.</p> : <p>Replay completed. It did not verify acquisition completeness, timing, calibration or biological meaning.</p>}</div>
      <h3>Separate session identities and importer</h3>
      <Ledger rows={[
        ["Recording ID", value.recording_id], ["Manual platform context ID", value.platform_session_id], ["Source capture-session ID", value.capture_session_id], ["Source ID", value.source_id], ["Selected segment index", evidenceText(value.selected_index)],
        ["Authenticated importer", value.actor_subject], ["Importer auth mode", value.auth_mode], ["Imported at (UTC)", value.imported_at],
        ["Mapped site", binding.mapping.site_id], ["Mapped zone", binding.mapping.zone_id], ["Mapped device", binding.mapping.device_id],
        ["Source header SHA-256", value.source_header_sha256], ["Source final SHA-256", value.source_final_sha256], ["Selected WAV SHA-256", value.wav_sha256], ["Manifest SHA-256", value.manifest_sha256],
      ]} />
      <p className="platform-note">The manual platform context is a scope binding, not the source session. Its summary clock fields do not override imported declarations. These hashes bind selected delivered files, not unavailable original data.</p>
    </div>
    <div className="inspection-block companion-channels">
      <h3>Declared channel order</h3><p className="platform-note">Order is retained as declared. Consistent WAV cardinality does not attest physical channel assignment. The existing waveform combines channel extrema and remains in nominal segment seconds.</p>
      <div className="table-scroll"><table className="platform-table"><caption>Ordered channels from the retained source declaration</caption><thead><tr><th scope="col">Position (zero-based)</th><th scope="col">Channel ID</th><th scope="col">Declared role</th></tr></thead><tbody>{source.channels.map((channel, index) => <tr key={`${index}-${channel.channel_id}`}><th scope="row">{index}</th><td className="full-identifier">{channel.channel_id}</td><td>{channel.role}</td></tr>)}</tbody></table></div>
      <Ledger rows={[["Source media", source.media], ["Nominal sample rate (Hz)", evidenceText(source.sample_rate_hz)], ["Declared source origin (s)", evidenceText(source.source_origin_s)], ["Source provenance", source.provenance], ["Source origin statement", source.origin], ["Original input SHA-256", source.input_sha256 ?? "Not supplied; original input bytes are not verified"], ["Copy operation", binding.copy_operation], ["Bytes transformed", evidenceText(binding.bytes_transformed)]]} />
    </div>
    <div className="inspection-block companion-timing">
      <h3>Declared nominal and reference timing</h3><p className="platform-note">Reported values below are not recalculated in the UI. UTC strings derive from an unverified declared epoch. Do not add nominal waveform offsets to manufacture candidate UTC or verified synchronization.</p>
      <Ledger rows={[
        ["Derived declared start (UTC)", time.started_at], ["Nominal WAV end (UTC)", time.nominal_wav_ended_at], ["Reference end (UTC)", time.reference_ended_at], ["Nominal duration (s)", time.nominal_duration_s], ["Reference duration (s)", time.reference_duration_s],
        ["Combined start uncertainty (s)", time.combined_start_uncertainty_s], ["Combined end uncertainty (s)", time.combined_end_uncertainty_s], ["Start rounding error (s)", time.started_at_rounding_error_s], ["Reference-end rounding error (s)", time.reference_end_rounding_error_s], ["Uncertainty combination", time.uncertainty_combination],
        ["Nominal candidate offsets", time.v1_candidate_offsets], ["Retained mapping expression (inert text)", time.candidate_reference_mapping], ["Resampled for clock drift", evidenceText(time.resampled_for_clock_drift)],
      ]} />
      <h3>Source clock declaration</h3>
      <Ledger rows={[["Source time domain", clock.source_domain], ["Reference time domain", clock.reference_domain], ["Reference epoch name", clock.reference_epoch], ["Declared clock method", clock.method], ["Source anchor (s)", evidenceText(clock.source_anchor_s)], ["Reference anchor (s)", evidenceText(clock.reference_anchor_s)], ["Declared drift (ppm)", evidenceText(clock.drift_ppm)], ["Anchor uncertainty (s)", evidenceText(clock.anchor_uncertainty_s)], ["Drift uncertainty (ppm)", evidenceText(clock.drift_uncertainty_ppm)], ["Clock evidence reference (inert text)", clock.evidence_ref], ["Clock relation verified", evidenceText(time.clock_relation_verified)]]} />
      <h3>Epoch declaration</h3>
      <Ledger rows={[["Epoch source ID", epoch.source_id], ["Epoch reference domain", epoch.reference_domain], ["Epoch reference name", epoch.reference_epoch], ["Declared epoch (UTC)", epoch.epoch_utc], ["Declared epoch uncertainty (s)", evidenceText(epoch.uncertainty_s)], ["Epoch declared by", epoch.declared_by], ["Epoch evidence reference (inert text)", epoch.evidence_ref], ["Epoch relation (inert text)", time.epoch_relation], ["Epoch declaration verified", evidenceText(time.epoch_declaration_verified)]]} />
    </div>
    <div className="inspection-block companion-gaps">
      <h3>Selected receipt: intervals, gaps and losses</h3><p className="platform-note">Gaps and missing units are not silence or reviewed coverage. A preceding receipt hash may be retained without its original bytes being delivered or checked.</p>
      <Ledger rows={[["Receipt index", evidenceText(receipt.index)], ["Nominal unit start", evidenceText(receipt.unit_start)], ["Stored segment units", evidenceText(receipt.units)], ["Source start (s)", evidenceText(receipt.source_start_s)], ["Source end (s)", evidenceText(receipt.source_end_s)], ["Reference start (s)", evidenceText(receipt.reference_start_s)], ["Reference end (s)", evidenceText(receipt.reference_end_s)], ["Receipt start uncertainty (s)", evidenceText(receipt.start_uncertainty_s)], ["Receipt end uncertainty (s)", evidenceText(receipt.end_uncertainty_s)], ["Missing units", evidenceText(receipt.missing_units)], ["Dropped units", evidenceText(receipt.dropped_units)], ["Unexplained missing units", evidenceText(receipt.unexplained_missing_units)], ["Declared source gap (s)", evidenceText(receipt.gap_source_s)], ["Gap reason", receipt.gap_reason || "No reason supplied"], ["Previous receipt SHA-256", receipt.previous_receipt_sha256 ?? "No predecessor declared"]]} />
      <h3>Retained source-snapshot accounting</h3><p className="platform-note">These snapshot totals are retained declarations, not a reconstructed or verified full-session accounting chain.</p>
      <Ledger rows={[["Snapshot stored units", evidenceText(binding.source_accounting.stored_units)], ["Snapshot missing units", evidenceText(binding.source_accounting.missing_units)], ["Snapshot dropped units", evidenceText(binding.source_accounting.dropped_units)], ["Snapshot source gaps (s)", evidenceText(binding.source_accounting.gap_source_s)], ["Acquisition state", binding.acquisition_state], ["Capture extent", binding.capture_extent], ["Acquisition completeness verified", evidenceText(binding.acquisition_completeness_verified)]]} />
    </div>
    <div className="inspection-block companion-origin">
      <h3>Unverified origin, calibration and authority</h3><Ledger rows={[["Original provenance", binding.provenance.original_provenance], ["Origin verified", evidenceText(binding.provenance.origin_verified)], ["Authorization verified", evidenceText(binding.authorization_verified)], ["Hardware verified", evidenceText(binding.hardware_verified)], ["Calibration status", binding.calibration_status], ["File-origin declaration (inert text)", binding.provenance.file_origin_declaration ? evidenceText(binding.provenance.file_origin_declaration) : "Not supplied"]]} />
      <h3>Reader software-check coverage</h3><p className="platform-note">The Acquisition reader checks delivered structure and consistency. Its exact projection is retained separately; software check flags do not establish physical facts or authorize operations.</p>
      <pre className="platform-json" aria-label="Reader verification coverage">{evidenceText(readerChecks)}</pre>
      <details className="data-table-disclosure"><summary>Complete parsed reader projection</summary><pre className="platform-json">{evidenceText(value.validation)}</pre></details>
      <details className="data-table-disclosure"><summary>Complete parsed original binding</summary><pre className="platform-json">{evidenceText(value.binding)}</pre></details>
      <p className="platform-note">Parsed views are for inspection. They are not the exact original JSON byte representation; use the retained document downloads below.</p>
    </div>
    <CompanionDownloads recordingId={value.recording_id} documents={value.documents} onError={onDownloadError} />
  </>;
}

function CompanionDownloads({ recordingId, documents, onError }: { recordingId: string; documents: CompanionDocument[]; onError: (caught: unknown) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const mounted = useRef(true);
  const request = useRef<AbortController | null>(null);
  const urls = useRef(new Set<string>());
  useEffect(() => {
    mounted.current = true;
    const activeUrls = urls.current;
    return () => { mounted.current = false; request.current?.abort(); for (const url of activeUrls) URL.revokeObjectURL(url); activeUrls.clear(); };
  }, []);
  async function download(document: CompanionDocument) {
    if (busy) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(document.role); setMessage(null);
    try {
      const response = await fetch(`${PLATFORM_API}/recordings/${encodeURIComponent(recordingId)}/acquisition-companion/documents/${document.role}`, { credentials: "same-origin", cache: "no-store", headers: { accept: "application/json" }, signal: controller.signal });
      const blob = await companionDownloadBlob(response, document);
      if (!mounted.current) return;
      const url = URL.createObjectURL(blob); urls.current.add(url);
      const anchor = window.document.createElement("a"); anchor.href = url; anchor.download = document.name; anchor.hidden = true; window.document.body.append(anchor); anchor.click(); anchor.remove();
      setTimeout(() => { URL.revokeObjectURL(url); urls.current.delete(url); }, 1000);
      setMessage(`Download started: ${document.name}. Bytes match the retained SHA-256; upstream source claims remain unverified.`);
    } catch (caught) { if (mounted.current && !controller.signal.aborted) onError(caught); }
    finally { if (mounted.current) setBusy(null); if (request.current === controller) request.current = null; }
  }
  return <div className="inspection-block companion-downloads"><h3>Exact retained JSON documents</h3><p className="platform-note">Five catalog roles, not filesystem paths. Downloads preserve original bytes and names; their transfer hash is checked against saved metadata. No declared URL or evidence reference is opened automatically.</p><div className="companion-document-list">{documents.map((document) => <section className="companion-document" key={document.role}><h4>{document.role}</h4><Ledger rows={[["Original basename", document.name], ["Retained bytes", evidenceText(document.bytes)], ["Retained SHA-256", document.sha256]]} /><button type="button" className="button secondary" disabled={busy !== null} onClick={() => void download(document)}>{busy === document.role ? `Downloading ${document.role}…` : `Download ${document.role}`}</button></section>)}</div>{message ? <p role="status">{message}</p> : null}</div>;
}
