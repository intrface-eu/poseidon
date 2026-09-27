"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { ApiPage } from "@/lib/api-types";
import { ApiError, apiRequest } from "@/lib/client-api";
import type { ClockQuality, Provenance } from "@/lib/platform";

export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "The request could not be completed. Retry when the local API is available.";
}
export function useResource<T>(path: string | null, version = 0) {
  const [retryVersion, setRetryVersion] = useState(0);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  useEffect(() => {
    let active = true;
    setData(null);
    setError(null);
    setLoading(Boolean(path));
    if (path) apiRequest<T>(path).then((value) => { if (active) setData(value); })
      .catch((caught) => { if (active) setError(errorMessage(caught)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [path, version, retryVersion]);
  return { data, error, loading, reload: () => setRetryVersion((value) => value + 1) };
}
export function RequestError({ message, retry }: { message: string | null; retry?: () => void }) {
  return message ? <div className="inline-message error" role="alert"><strong>Request not completed.</strong><span>{message}</span>{retry ? <button className="text-button" type="button" onClick={retry}>Retry</button> : null}</div> : null;
}
export function PageControls({ page, onPage, loading = false }: { page: ApiPage<unknown> | null; onPage: (offset: number) => void; loading?: boolean }) {
  if (!page) return null;
  return <div className="pager"><button type="button" disabled={loading || page.offset === 0} onClick={() => onPage(Math.max(0, page.offset - page.limit))}>Previous page</button><span>{page.total ? `${page.offset + 1}–${Math.min(page.offset + page.items.length, page.total)} of ${page.total}` : "0 records"}</span><button type="button" disabled={loading || page.offset + page.limit >= page.total} onClick={() => onPage(page.offset + page.limit)}>Next page</button></div>;
}
export function Ledger({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="identifier-ledger platform-ledger">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? "Not supplied"}</dd></div>)}</dl>;
}
export function SourceClock({ provenance, clock }: { provenance: Provenance; clock: ClockQuality }) {
  return <Ledger rows={[
    ["Source", <span key="source" className={`tag ${provenance.source_kind}`}>{provenance.source_kind}</span>], ["Source ID", provenance.source_id], ["Transport", provenance.transport],
    ["Clock quality", clock.status], ["Clock method", clock.method], ["Uncertainty (ms)", clock.uncertainty_ms], ["Offset (ms)", clock.offset_ms], ["Reference", clock.reference],
  ]} />;
}
