"use client";

import { useEffect, useRef, useState } from "react";
import { apiRequest } from "./client-api";

// Retain same-scope rows during polling so open audit disclosures do not collapse.
// A failed refresh clears the snapshot; it never leaves stale command authority visible.
export function useDigitalResource<T>(path: string | null, version = 0) {
  const previousPath = useRef<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  useEffect(() => {
    const abort = new AbortController();
    if (previousPath.current !== path) setData(null);
    previousPath.current = path;
    setError(null); setLoading(Boolean(path));
    if (path) void apiRequest<T>(path, { signal: abort.signal }).then((value) => {
      if (!abort.signal.aborted) setData(value);
    }).catch((caught) => {
      if (!abort.signal.aborted) { setData(null); setError(caught instanceof Error ? caught.message : "Digital state could not be refreshed. Retry when the API is available."); }
    }).finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [path, version, retry]);
  // Never expose a prior path's data during the render before the effect runs.
  return { data: previousPath.current === path ? data : null, error, loading, reload: () => setRetry((value) => value + 1) };
}
