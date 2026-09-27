"use client";

import type { ApiPage, Recording } from "@/lib/api-types";
import { formatUtc, shortId } from "@/lib/format";

export function RecordingRail({
  page,
  selected,
  loading,
  onSelect,
  onPage,
}: {
  page: ApiPage<Recording> | null;
  selected: string;
  loading: boolean;
  onSelect: (recordingId: string) => void;
  onPage: (offset: number) => void;
}) {
  const items = page?.items ?? [];
  return (
    <nav className="recording-rail" aria-labelledby="recordings-title" aria-busy={loading}>
      <div className="rail-heading">
        <h2 id="recordings-title">Recordings</h2>
        <span>{page?.total ?? 0}</span>
      </div>
      <button
        type="button"
        className={`recording-row all-recordings ${selected === "" ? "selected" : ""}`}
        aria-pressed={selected === ""}
        onClick={() => onSelect("")}
      >
        <span className="recording-title">All recordings</span>
        <span className="recording-meta">Whole workspace</span>
      </button>
      <div className={`recording-list ${loading && page ? "refreshing" : ""}`}>
        {loading && !page ? (
          <>
            <div className="skeleton record" />
            <div className="skeleton record" />
            <div className="skeleton record" />
          </>
        ) : null}
        {!loading && page && items.length === 0 ? (
          <p className="rail-empty">No recording records yet.</p>
        ) : null}
        {items.map((recording) => {
          const isSelected = selected === recording.recording_id;
          return (
            <button
              type="button"
              className={`recording-row ${isSelected ? "selected" : ""}`}
              key={recording.recording_id}
              aria-pressed={isSelected}
              onClick={() => onSelect(recording.recording_id)}
            >
              <span className="recording-title" title={recording.recording_id}>
                {shortId(recording.recording_id, 24)}
              </span>
              <span className="recording-meta">{recording.site_id} · {recording.zone_id}</span>
              <span className="recording-meta">Declared start · {formatUtc(recording.started_at)}</span>
              <span className="tag-row">
                <span className={`tag ${recording.provenance}`}>{recording.provenance}</span>
                <span className="tag calibration">{recording.calibration_status}</span>
                <span className="tag neutral">{recording.reviewed_count}/{recording.event_count} reviewed</span>
              </span>
            </button>
          );
        })}
      </div>
      {page && page.total > page.limit ? (
        <div className="pager compact" aria-label="Recording pages">
          <button type="button" onClick={() => onPage(Math.max(0, page.offset - page.limit))} disabled={page.offset === 0 || loading}>
            Previous
          </button>
          <span>{page.offset + 1}–{Math.min(page.total, page.offset + page.limit)}</span>
          <button type="button" onClick={() => onPage(page.offset + page.limit)} disabled={page.offset + page.limit >= page.total || loading}>
            Next
          </button>
        </div>
      ) : null}
    </nav>
  );
}
