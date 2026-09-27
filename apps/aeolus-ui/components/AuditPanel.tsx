"use client";

import { useState } from "react";
import type { ApiPage } from "@/lib/api-types";
import { canAdmin, PLATFORM_API, type AuditEntry, type Identity } from "@/lib/platform";
import { Ledger, PageControls, RequestError, useResource } from "./PlatformCommon";

export function AuditPanel({ identity }: { identity: Identity }) {
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const entries = useResource<ApiPage<AuditEntry>>(canAdmin(identity) ? `${PLATFORM_API}/audit?limit=25&offset=${offset}` : null, version);
  return <section className="platform-panel" aria-labelledby="audit-title"><header className="platform-heading"><div><h2 id="audit-title">Security audit trail</h2><p>Server-recorded actions and exact authenticated actors, limited to your authorized scope. Credentials never belong in audit detail.</p></div><button type="button" className="button secondary" disabled={!canAdmin(identity) || entries.loading} onClick={() => setVersion((value) => value + 1)}>Refresh audit</button></header><div className="inspection-block">{!canAdmin(identity) ? <p>Your {identity.role} role cannot read the admin audit trail.</p> : null}<RequestError message={entries.error} retry={() => setVersion((value) => value + 1)} />{entries.loading ? <p role="status">Loading audit trail…</p> : null}{entries.data?.items.length === 0 ? <p className="list-empty">No audit entries in this scope.</p> : null}{entries.data?.items.map((row) => <details className="data-table-disclosure" key={row.id}><summary>{row.action} · {row.created_at} · {row.actor_subject}</summary><div className="inspection-block"><Ledger rows={[["Audit ID", row.id], ["Action", row.action], ["Actor", row.actor_subject], ["Auth mode", row.auth_mode], ["Site", row.site_id], ["Device", row.device_id], ["Resource", row.resource_id], ["Timestamp", row.created_at]]} /><h3>Action detail</h3><pre className="platform-json">{JSON.stringify(row.details, null, 2)}</pre></div></details>)}<PageControls page={entries.data} onPage={setOffset} /></div></section>;
}
