"use client";

import { useState, type FormEvent } from "react";
import { apiRequest, jsonRequest } from "@/lib/client-api";
import { canAdmin, PLATFORM_API, type Identity } from "@/lib/platform";
import type { HubStateRead } from "@/lib/digital";
import { DeviceHealthList, AlarmList } from "./DigitalHealth";
import { HubAudit } from "./DigitalHub";
import { DigitalCommands, CommandHistory } from "./DigitalCommands";
import { DigitalCalibrations } from "./DigitalCalibrations";
import { RequestError, errorMessage } from "./PlatformCommon";

export function DigitalWorkspace({ identity, hub, version, onRefresh }: { identity: Identity; hub: HubStateRead | null; version: number; onRefresh: () => void }) {
  return <div className="platform-stack">
    <DigitalCommands identity={identity} hub={hub} onChanged={onRefresh} />
    {canAdmin(identity) && identity.auth_mode === "local_development_key" ? <ExplicitHubBinding hub={hub} onChanged={onRefresh} /> : null}
    <AlarmList identity={identity} version={version} onChanged={onRefresh} />
    <HubAudit hub={hub} />
    <DeviceHealthList version={version} />
    <DigitalCalibrations version={version} />
    <CommandHistory version={version} />
  </div>;
}

function ExplicitHubBinding({ hub, onChanged }: { hub: HubStateRead | null; onChanged: () => void }) {
  const [deviceId, setDeviceId] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  async function bind(event: FormEvent) {
    event.preventDefault(); setPending(true); setError(null); setMessage(null);
    try {
      await apiRequest(`${PLATFORM_API}/hub-binding`, jsonRequest("PUT", { device_id: deviceId }));
      setMessage("API accepted the explicit immutable hub binding. No hardware was connected or enabled.");
      onChanged();
    } catch (caught) { setError(errorMessage(caught)); } finally { setPending(false); }
  }
  return <section className="platform-panel inspection-block"><details><summary>Explicit synthetic hub enrollment</summary><p className="platform-note">Local-development admin only. First register a synthetic hub and enroll its explicit zone/health profile under Devices & telemetry. Binding is immutable; the API rejects other device kinds and missing profiles. No device is selected by default.</p>
    {hub?.binding ? <p className="full-identifier">Already bound to {hub.binding.device_id} at {hub.binding.site_id} / {hub.binding.zone_id}.</p> : null}
    <form className="platform-form" onSubmit={bind}><fieldset disabled={pending || Boolean(hub?.binding)}><label>Exact registered synthetic hub ID<input required maxLength={128} value={deviceId} onChange={(event) => setDeviceId(event.target.value)} /></label></fieldset><button type="submit" className="button secondary" disabled={pending || Boolean(hub?.binding)}>{pending ? "Binding explicit hub…" : "Bind this exact registered hub"}</button></form><RequestError message={error} />{message ? <p role="status">{message}</p> : null}
  </details></section>;
}
