"use client";

import { useEffect, useState, type FormEvent } from "react";
import type { ApiPage } from "@/lib/api-types";
import { apiRequest, jsonRequest } from "@/lib/client-api";
import { canAdmin, PLATFORM_API, type Credential, type Identity, type Principal, type PrincipalInput, type Role } from "@/lib/platform";
import { Ledger, PageControls, RequestError, errorMessage, useResource } from "./PlatformCommon";

export function IdentityPanel({ identity }: { identity: Identity }) {
  const admin = canAdmin(identity);
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const principals = useResource<ApiPage<Principal>>(admin ? `${PLATFORM_API}/principals?limit=25&offset=${offset}` : null, version);
  const [subject, setSubject] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [sites, setSites] = useState(identity.site_ids.join(", "));
  const [deviceId, setDeviceId] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState<Credential | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    // A revealed token exists only in this mounted client component. Never serialize it.
    const clear = () => setSecret(null);
    const hidden = () => { if (document.visibilityState === "hidden") clear(); };
    window.addEventListener("pagehide", clear); document.addEventListener("visibilitychange", hidden);
    return () => { window.removeEventListener("pagehide", clear); document.removeEventListener("visibilitychange", hidden); };
  }, []);
  async function create(event: FormEvent) {
    event.preventDefault(); if (!admin || secret) return;
    const site_ids = Array.from(new Set(sites.split(",").map((site) => site.trim()).filter(Boolean)));
    if (!site_ids.length || (role === "device" && (site_ids.length !== 1 || !deviceId.trim()))) { setError("Select at least one exact site. Device credentials require one site and an existing registered device ID."); return; }
    if (identity.auth_mode === "scoped_token" && site_ids.some((site) => !identity.site_ids.includes(site))) { setError("New scopes must be a subset of your authorized sites."); return; }
    const body: PrincipalInput = { subject, role, site_ids, device_id: role === "device" ? deviceId.trim() : null };
    setPending(true); setError(null); setMessage(null);
    try { const result = await apiRequest<Credential>(`${PLATFORM_API}/principals`, jsonRequest("POST", body)); setSecret(result); setVersion((value) => value + 1); setSubject(""); }
    catch (caught) { setError(errorMessage(caught)); } finally { setPending(false); }
  }
  async function lifecycle(row: Principal, operation: "rotate" | "revoke") {
    if (!admin || secret || !window.confirm(operation === "rotate" ? `Rotate the token for ${row.subject}? The current token stops working immediately. The replacement appears once.` : `Revoke access for ${row.subject}? Its current token will stop working.`)) return;
    setPending(true); setError(null); setMessage(null);
    try {
      if (operation === "rotate") setSecret(await apiRequest<Credential>(`${PLATFORM_API}/principals/${encodeURIComponent(row.id)}/rotate`, { method: "POST" }));
      else { await apiRequest<Principal>(`${PLATFORM_API}/principals/${encodeURIComponent(row.id)}/revoke`, { method: "POST" }); setMessage(`Revoked ${row.subject}.`); }
      setVersion((value) => value + 1);
    } catch (caught) { setError(errorMessage(caught)); } finally { setPending(false); }
  }
  return <section className="platform-panel" aria-labelledby="identity-title"><header className="platform-heading"><div><h2 id="identity-title">Identity & access</h2><p>Local authorization foundations. A workspace development key is not a production identity system.</p></div></header><div className="inspection-block"><Ledger rows={[["Authenticated subject", identity.subject], ["Role", identity.role], ["Auth mode", identity.auth_mode], ["Site scopes", identity.site_ids.length ? identity.site_ids.join(", ") : identity.auth_mode === "local_development_key" ? "Local development authority; no site restriction" : "No sites"], ["Device binding", identity.device_id ?? "Human principal"]]} /><p className="platform-note">Disabled controls reflect this identity. The API independently authorizes every operation and site/device scope.</p></div>
    {secret ? <section className="inspection-block one-time-secret" aria-labelledby="secret-title"><h3 id="secret-title">One-time token for {secret.principal.subject}</h3><p>Store this token now in your approved secret store. It will not be shown again. Switching sections, hiding this page, or dismissing this panel clears it. No copy is saved in browser storage or rendered page source.</p><Ledger rows={[["Principal ID", secret.principal.id], ["Role", secret.principal.role], ["Sites", secret.principal.site_ids.join(", ")], ["Device", secret.principal.device_id ?? "Not a device"]]} /><label>One-time secret<input type="text" className="full-identifier" readOnly autoComplete="off" spellCheck={false} value={secret.token} onFocus={(event) => event.target.select()} /></label><button type="button" className="button primary" onClick={() => { setSecret(null); setMessage("Token display cleared. If you did not store it, rotate the credential to issue a replacement."); }}>I stored the token; clear display</button></section> : null}
    <div className="inspection-block"><h3>Scoped token provisioning</h3><p className="platform-note">Device provisioning binds an existing local test device and exactly one site. Registration and token issuance do not authorize real field enrollment.</p><form className="platform-form" onSubmit={create}><fieldset disabled={!admin || pending || Boolean(secret)}><label>Principal subject<input value={subject} required maxLength={80} onChange={(event) => setSubject(event.target.value)} /></label><label>Principal role<select value={role} onChange={(event) => setRole(event.target.value as Role)}><option value="viewer">Viewer · read evidence</option><option value="reviewer">Reviewer · human observations</option><option value="admin">Admin · scoped registry and access</option><option value="operator">Operator · signed local digital commands</option><option value="device">Device · exact telemetry identity</option></select></label><label>Authorized site IDs (comma-separated)<input value={sites} required onChange={(event) => setSites(event.target.value)} /></label>{role === "device" ? <label>Registered device ID<input value={deviceId} required maxLength={128} onChange={(event) => setDeviceId(event.target.value)} /></label> : null}</fieldset><button type="submit" className="button primary" disabled={!admin || pending || Boolean(secret)}>{pending ? "Issuing credential…" : "Issue scoped token"}</button>{!admin ? <p>Your {identity.role} role cannot provision, rotate, revoke, or list other principals.</p> : null}</form><RequestError message={error} />{message ? <p role="status">{message}</p> : null}</div>
    {admin ? <div className="inspection-block"><div className="block-heading"><h3>Principals in your scope</h3><button type="button" className="button secondary" disabled={Boolean(secret)} onClick={() => setVersion((value) => value + 1)}>Refresh principals</button></div><RequestError message={principals.error} retry={() => setVersion((value) => value + 1)} />{principals.loading ? <p role="status">Loading principals…</p> : null}{principals.data?.items.length === 0 ? <p className="list-empty">No scoped principals. The local development key is not a scoped principal record.</p> : null}{principals.data?.items.map((row) => <details className="data-table-disclosure" key={row.id}><summary>{row.subject} · {row.role} · {row.revoked_at ? "revoked" : "active"}</summary><div className="inspection-block"><Ledger rows={[["Principal ID", row.id], ["Subject", row.subject], ["Role", row.role], ["Sites", row.site_ids.join(", ")], ["Device", row.device_id ?? "None"], ["Created", row.created_at], ["Updated", row.updated_at], ["Revoked", row.revoked_at ?? "Not revoked"]]} /><div className="conflict-actions"><button type="button" className="button secondary" disabled={pending || Boolean(secret) || Boolean(row.revoked_at)} onClick={() => void lifecycle(row, "rotate")}>Rotate token</button><button type="button" className="button secondary" disabled={pending || Boolean(secret) || Boolean(row.revoked_at)} onClick={() => void lifecycle(row, "revoke")}>Revoke principal</button></div></div></details>)}<PageControls page={principals.data} onPage={setOffset} /></div> : null}
  </section>;
}
