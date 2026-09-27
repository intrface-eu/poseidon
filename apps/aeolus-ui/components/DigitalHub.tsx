"use client";

import type { HubStateRead } from "@/lib/digital";
import { Ledger, RequestError } from "./PlatformCommon";

export function DigitalHubBanner({ hub, error, loading, onRefresh }: { hub: HubStateRead | null; error: string | null; loading: boolean; onRefresh: () => void }) {
  return <section className="platform-panel digital-hub-banner" aria-label="Local digital hub state" aria-busy={loading}>
    <div className="platform-heading"><div><h2>LOCAL DIGITAL state: <span data-hub-state>{hub?.state ?? (loading ? "checking" : "unavailable")}</span></h2><p>Controller software state only. Not hardware connectivity, safety approval or output authorization. Emit entry is always refused.</p></div><button type="button" className="button secondary" disabled={loading} onClick={onRefresh}>Refresh digital state</button></div>
    <div className="inspection-block"><RequestError message={error} retry={onRefresh} />{hub ? <p className="platform-note full-identifier">{hub.binding ? `Explicit hub ${hub.binding.device_id} · site ${hub.binding.site_id} · zone ${hub.binding.zone_id}` : "No registered hub binding. No first/default device is used for commands."}</p> : <p className="platform-note">No current hub-state response. Commands stay unavailable until the API returns an explicit binding.</p>}</div>
  </section>;
}

export function HubAudit({ hub }: { hub: HubStateRead | null }) {
  return <section className="platform-panel" aria-labelledby="hub-audit-title"><header className="platform-heading"><div><h2 id="hub-audit-title">Digital watchdogs & transition audit</h2><p>The server reports each watchdog and the last ten local state transitions. No physical interlock is represented here.</p></div></header><div className="inspection-block">
    {!hub ? <p className="list-empty">Refresh digital state to load watchdogs and transitions.</p> : <>
      <div className="table-scroll" tabIndex={0} aria-label="Digital watchdogs table"><table className="platform-table"><caption>Controller-defined watchdog status</caption><thead><tr><th scope="col">Watchdog</th><th scope="col">Digital status</th><th scope="col">Reason</th></tr></thead><tbody>{hub.watchdogs.map((watchdog) => <tr key={watchdog.id}><th scope="row">{watchdog.id}</th><td>{watchdog.healthy ? "Healthy" : "Unhealthy"}</td><td>{watchdog.reason}</td></tr>)}</tbody></table></div>
      {hub.watchdogs.length === 0 ? <p>No watchdog observations returned. Rearm stays unavailable.</p> : null}
      <h3>Last ten transitions</h3>{hub.last_transitions.length === 0 ? <p className="list-empty">No recorded transitions.</p> : null}
      <ol className="digital-transition-list">{hub.last_transitions.map((transition) => <li key={transition.id} data-transition-id={transition.id}><strong>{transition.from_state} to {transition.to_state}</strong><span>{transition.reason}</span><Ledger rows={[["UTC", transition.created_at], ["Cause ID", transition.cause_id], ["Command ID", transition.command_id ?? "Watchdog or recovery transition"]]} /></li>)}</ol>
    </>}
  </div></section>;
}
