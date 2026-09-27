"use client";

import { useState, type FormEvent } from "react";
import type { ApiPage } from "@/lib/api-types";
import { apiRequest, jsonRequest } from "@/lib/client-api";
import { canAdmin, canImport, parseBoundedObject, PLATFORM_API, type Identity } from "@/lib/platform";
import { encodeArtifact, MAX_ARTIFACT_BYTES, transitionAllowed, type LocalTarget, type TargetHistory, type Transition, type TrustKey } from "@/lib/lifecycle";
import { Ledger, RequestError, errorMessage, useResource } from "./PlatformCommon";

const base = `${PLATFORM_API}/lifecycle`;
const actionLabels: Record<Transition, string> = { activate: "Activate local trial", confirm: "Confirm declared local test health", rollback: "Roll back local target", recover: "Recover local target" };

export function LifecyclePanel({ identity }: { identity: Identity }) {
  const [version, setVersion] = useState(0);
  const [selected, setSelected] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [manifestName, setManifestName] = useState("");
  const [artifactName, setArtifactName] = useState("");
  const keys = useResource<ApiPage<TrustKey>>(`${base}/keys`, version);
  const targets = useResource<ApiPage<LocalTarget>>(`${base}/targets`, version);
  const target = useResource<LocalTarget>(selected ? `${base}/targets/${encodeURIComponent(selected)}` : null, version);
  const history = useResource<ApiPage<TargetHistory>>(selected ? `${base}/targets/${encodeURIComponent(selected)}/history` : null, version);
  const admin = canAdmin(identity);
  const trustAdmin = canImport(identity);
  async function perform(action: () => Promise<unknown>, success: string) {
    setPending(true); setError(null); setMessage(null);
    try { await action(); setVersion((value) => value + 1); setMessage(success); }
    catch (caught) { setError(errorMessage(caught)); }
    finally { setPending(false); }
  }
  function addKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!trustAdmin) return;
    const form = new FormData(event.currentTarget);
    const body = { id: String(form.get("id")), site_ids: String(form.get("site_ids")).split(",").map((site) => site.trim()).filter(Boolean), public_key_hex: String(form.get("public_key_hex")).trim() };
    if (!window.confirm(`Trust public key ${body.id} for the listed sites? This changes local signature trust. No private key will be requested.`)) return;
    void perform(() => apiRequest(`${base}/keys`, jsonRequest("POST", body)), "Public trust key stored for local validation.");
  }
  function createTarget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!admin) return;
    const form = new FormData(event.currentTarget);
    const body = { id: String(form.get("id")), device_id: String(form.get("device_id")), simulation: true, initial_sha256: String(form.get("initial_sha256")), initial_version: String(form.get("initial_version")), security_floor: Number(form.get("security_floor")) };
    void perform(async () => { const row = await apiRequest<LocalTarget>(`${base}/targets`, jsonRequest("POST", body)); setSelected(row.id); }, "Local simulated target created. The baseline digest is declared, not an installed-image measurement.");
  }
  async function stage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!admin || !target.data) return;
    const form = new FormData(event.currentTarget);
    const manifest = form.get("manifest"); const artifact = form.get("artifact");
    if (!(manifest instanceof File) || !manifest.size || manifest.size > 64 * 1024 || !(artifact instanceof File) || !artifact.size || artifact.size > MAX_ARTIFACT_BYTES) { setError("Choose a signed manifest JSON up to 64 KiB and the exact artifact bytes up to 1 MiB. No private signing key is accepted."); return; }
    setPending(true); setError(null); setMessage(null);
    try {
      const signed = parseBoundedObject(await manifest.text());
      const artifact_base64 = encodeArtifact(new Uint8Array(await artifact.arrayBuffer()));
      await apiRequest<LocalTarget>(`${base}/targets/${encodeURIComponent(target.data.id)}/stage`, jsonRequest("POST", { manifest: signed, artifact_base64 }));
      setVersion((value) => value + 1); setMessage("Artifact staged after server signature, byte, compatibility and replay checks. It has not been activated or installed.");
    } catch (caught) { setError(caught instanceof SyntaxError ? "The signed manifest is not valid JSON. Files stay selected for correction." : errorMessage(caught)); }
    finally { setPending(false); }
  }
  function transition(action: Transition) {
    if (!target.data || !admin || !transitionAllowed(target.data.state, action)) return;
    const warning = action === "confirm" ? "Declare that this LOCAL SOFTWARE TEST passed? This is not measured hardware health. Confirmation may advance the security floor and prevent rollback." : `${actionLabels[action]} for ${target.data.id}? Only local simulated state changes; no installation, flash, service or field command runs.`;
    if (!window.confirm(warning)) return;
    void perform(() => apiRequest(`${base}/targets/${encodeURIComponent(target.data!.id)}/${action}`, { method: "POST" }), `${actionLabels[action]} recorded. Inspect transition history for the exact actor and result.`);
  }
  return <section className="platform-panel" aria-labelledby="lifecycle-title"><header className="platform-heading"><div><h2 id="lifecycle-title">Signed local lifecycle</h2><p>Simulation only. Real signature and artifact-byte checks; no installation, flashing, field command or physical health measurement.</p></div><button type="button" className="button secondary" disabled={pending} onClick={() => setVersion((value) => value + 1)}>Refresh local lifecycle</button></header><div className="inspection-block"><div className="inline-message warning"><strong>Local simulated targets only</strong><span>Declared baselines and test-health confirmations are software-test records, not evidence of installed firmware or safe hardware. Sign artifacts offline; never paste a private key here.</span></div><RequestError message={error} />{message ? <p role="status">{message}</p> : null}</div>
    <div className="platform-split"><div className="inspection-block"><h3>Local test targets</h3><RequestError message={targets.error} retry={() => setVersion((value) => value + 1)} />{targets.loading ? <p role="status">Loading local targets…</p> : null}{targets.data?.items.length === 0 ? <p className="list-empty">No local simulation targets. Registered devices do not automatically become rollout targets.</p> : null}{targets.data?.items.map((row) => <button type="button" key={row.id} className={`recording-row ${row.id === selected ? "selected" : ""}`} disabled={pending} onClick={() => { setSelected(row.id); setError(null); setMessage(null); }}><strong className="full-identifier">{row.id}</strong><span>{row.state} · revision {row.revision} · site {row.site_id}</span><span className="tag synthetic">Local simulation only</span></button>)}<details className="data-table-disclosure"><summary>Create a local simulation target</summary><form className="platform-form inspection-block" onSubmit={createTarget}><fieldset disabled={!admin || pending}><label>Local target ID<input name="id" required maxLength={128} /></label><label>Registered synthetic/bench device ID<input aria-label="Registered synthetic/bench device ID" name="device_id" required maxLength={128} /><small>REEF or Hub only; field devices and gateways are rejected.</small></label><label className="full">Declared baseline SHA-256<input name="initial_sha256" required pattern="[a-f0-9]{64}" minLength={64} maxLength={64} className="full-identifier" /></label><label>Declared baseline version<input name="initial_version" required maxLength={80} /></label><label>Initial security floor<input name="security_floor" type="number" min="0" step="1" required /></label></fieldset><button type="submit" className="button primary" disabled={!admin || pending}>Create simulation target</button></form></details></div>
    <div className="inspection-block"><h3>Selected local target</h3><RequestError message={target.error} />{target.loading ? <p role="status">Loading target…</p> : null}{target.data ? <><Ledger rows={[["Target ID", target.data.id], ["Simulation", "Local only; no physical target"], ["Device ID", target.data.device_id], ["Site", target.data.site_id], ["Target kind", target.data.target_kind], ["Hardware revision", target.data.hardware_revision], ["State", target.data.state], ["Revision", target.data.revision], ["Current SHA-256", target.data.current_sha256], ["Current version", target.data.current_version], ["Security floor", target.data.security_floor], ["Highest sequence", target.data.highest_sequence], ["Staged manifest", target.data.staged_manifest_id], ["Trial manifest", target.data.trial_manifest_id], ["Previous SHA-256", target.data.previous_sha256], ["Updated", target.data.updated_at]]} /><form className="platform-form" onSubmit={stage} key={target.data.id}><fieldset disabled={!admin || pending || ["staged", "trial"].includes(target.data.state)}><label>Signed manifest JSON<input aria-label="Signed manifest JSON" name="manifest" type="file" accept="application/json,.json" required onChange={(event) => setManifestName(event.target.files?.[0]?.name ?? "")} /><small>Public signed manifest only, up to 64 KiB.</small></label><label>Exact artifact file<input aria-label="Exact artifact file" name="artifact" type="file" required onChange={(event) => setArtifactName(event.target.files?.[0]?.name ?? "")} /><small>Up to 1 MiB. Bytes are checked, never executed.</small></label></fieldset><button type="submit" className="button primary" disabled={!admin || pending || ["staged", "trial"].includes(target.data.state)}>Stage signed artifact locally</button><p className="platform-note">{manifestName || "No manifest selected"} · {artifactName || "No artifact selected"}. Stage is separate from activation.</p></form><div className="conflict-actions">{(Object.keys(actionLabels) as Transition[]).map((action) => <button type="button" key={action} className="button secondary" disabled={!admin || pending || !transitionAllowed(target.data!.state, action)} onClick={() => transition(action)}>{actionLabels[action]}</button>)}</div><p className="platform-note">Rollback and recovery remain subject to the server security floor. Sequence high-water marks are not reset by a failed trial.</p></> : !selected ? <p>Select a local target to stage bytes or inspect state.</p> : null}</div></div>
    {selected ? <div className="inspection-block"><h3>Local transition history</h3><RequestError message={history.error} />{history.data?.items.map((row) => <details className="data-table-disclosure" key={row.revision}><summary>Revision {row.revision} · {row.action} · actor {row.actor_subject}</summary><div className="inspection-block"><Ledger rows={[["Actor", row.actor_subject], ["Auth mode", row.auth_mode], ["Timestamp", row.created_at]]} /><pre className="platform-json">{JSON.stringify(row.details, null, 2)}</pre></div></details>)}</div> : null}
    <div className="inspection-block"><h3>Public trust keys</h3><RequestError message={keys.error} />{keys.data?.items.length === 0 ? <p>No public trust keys registered.</p> : null}{keys.data?.items.map((key) => <details className="data-table-disclosure" key={key.id}><summary>{key.id} · {key.revoked_at ? "revoked" : "trusted for listed sites"}</summary><div className="inspection-block"><Ledger rows={[["Key ID", key.id], ["Sites", key.site_ids.join(", ")], ["Ed25519 public key", key.public_key_hex], ["Created", key.created_at], ["Revoked", key.revoked_at ?? "Not revoked"]]} /><button type="button" className="button secondary" disabled={!trustAdmin || pending || Boolean(key.revoked_at)} onClick={() => { if (window.confirm(`Revoke public trust key ${key.id}? New staging and trial advancement under it will be rejected.`)) void perform(() => apiRequest(`${base}/keys/${encodeURIComponent(key.id)}/revoke`, { method: "POST" }), "Public trust key revoked."); }}>Revoke public trust key</button></div></details>)}<details className="data-table-disclosure"><summary>Add an Ed25519 public trust key</summary><form className="platform-form inspection-block" onSubmit={addKey}><fieldset disabled={!trustAdmin || pending}><label>Public key ID<input name="id" required maxLength={128} /></label><label>Public key site IDs (comma-separated)<input name="site_ids" required /></label><label className="full">Ed25519 public key (64 lowercase hex digits)<input name="public_key_hex" required minLength={64} maxLength={64} pattern="[a-f0-9]{64}" className="full-identifier" /></label></fieldset><button type="submit" className="button primary" disabled={!trustAdmin || pending}>Trust public key locally</button><p className="platform-note">Only the local development key can alter trust roots. No private signing key field exists.</p></form></details></div></section>;
}
