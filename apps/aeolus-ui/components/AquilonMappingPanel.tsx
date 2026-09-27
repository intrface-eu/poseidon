"use client";

import { useEffect, useState, type FormEvent } from "react";
import { ApiError, apiRequest, jsonRequest } from "@/lib/client-api";
import { canAdmin, PLATFORM_API, type AquilonMappingInput, type Device, type Identity } from "@/lib/platform";
import { Ledger, RequestError, errorMessage } from "./PlatformCommon";

export function AquilonMappingPanel({ device, identity }: { device: Device; identity: Identity }) {
  const [mapping, setMapping] = useState<AquilonMappingInput | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [devEui, setDevEui] = useState("");
  const [refs, setRefs] = useState("");
  const readable = canAdmin(identity) || (identity.role === "device" && identity.device_id === device.id);
  const path = `${PLATFORM_API}/devices/${encodeURIComponent(device.id)}/aquilon-mapping`;
  useEffect(() => {
    if (!readable) { setLoading(false); return; }
    let active = true; setLoading(true); setError(null);
    apiRequest<AquilonMappingInput>(path).then((row) => { if (active) setMapping(row); }).catch((caught) => {
      if (!active) return;
      if (caught instanceof ApiError && caught.status === 404) setMapping(null);
      else setError(errorMessage(caught));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [path, readable, version]);
  async function save(event: FormEvent) {
    event.preventDefault(); if (!canAdmin(identity) || mapping || loading || device.revoked_at) return;
    let calibration_refs: AquilonMappingInput["calibration_refs"];
    try {
      if (new TextEncoder().encode(refs).byteLength > 60 * 1024) throw new Error("too large");
      calibration_refs = refs.trim() ? JSON.parse(refs) : [];
      if (!Array.isArray(calibration_refs)) throw new Error("not array");
    } catch { setError("Calibration references must be a JSON array within 60 KiB, or empty when none exists."); return; }
    if (!window.confirm(`Bind DevEUI ${devEui} to ${device.id}? This mapping and its calibration references cannot be replaced.`)) return;
    setPending(true); setError(null);
    try { setMapping(await apiRequest<AquilonMappingInput>(path, jsonRequest("PUT", { dev_eui: devEui, calibration_refs }))); }
    catch (caught) { setError(errorMessage(caught)); } finally { setPending(false); }
  }
  if (!readable) return <p className="platform-note">AQUILON mapping is visible to admins and the matching device identity only.</p>;
  return <details className="data-table-disclosure"><summary>AQUILON identity and calibration mapping</summary><div className="inspection-block"><p className="platform-note">Local registry mapping only. A DevEUI is not enrollment authorization; calibration IDs are references, not calibration certificates.</p><RequestError message={error} retry={() => setVersion((value) => value + 1)} />{loading ? <p role="status">Loading mapping…</p> : mapping ? <><Ledger rows={[["DevEUI", mapping.dev_eui], ["Device ID", device.id]]} /><pre className="platform-json">{JSON.stringify(mapping.calibration_refs, null, 2)}</pre><p>Mapping is immutable. No replacement action is available.</p></> : <><p>No AQUILON mapping for this device.</p><form className="platform-form" onSubmit={save}><fieldset disabled={!canAdmin(identity) || pending || Boolean(device.revoked_at)}><label>DevEUI (16 lowercase hex digits)<input required pattern="[a-f0-9]{16}" minLength={16} maxLength={16} value={devEui} onChange={(event) => setDevEui(event.target.value)} /></label><label className="full">Calibration reference array (optional)<textarea aria-label="Calibration reference array (optional)" value={refs} onChange={(event) => setRefs(event.target.value)} maxLength={61440} rows={5} className="full-identifier" /><small>Each JSON entry contains code (1–65535), sensor_kind (temperature, salinity, or dissolved_oxygen), and calibration_id. Empty means no calibration references. Never invent a reference to promote raw counts into calibrated values.</small></label></fieldset><button type="submit" className="button primary" disabled={!canAdmin(identity) || pending || Boolean(device.revoked_at)}>Store immutable mapping</button></form></>}</div></details>;
}
