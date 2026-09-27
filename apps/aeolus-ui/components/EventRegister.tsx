"use client";

import type { AcousticEvent, ApiPage, Recording, ReviewFilter } from "@/lib/api-types";
import { formatAmplitude, formatSeconds, reviewLabel, shortId } from "@/lib/format";

export function EventRegister({
  page,
  recordings,
  recordingFilter,
  reviewFilter,
  selectedEventId,
  loading,
  error,
  onRecordingFilter,
  onReviewFilter,
  onSelect,
  onPage,
  onRetry,
}: {
  page: ApiPage<AcousticEvent> | null;
  recordings: Recording[];
  recordingFilter: string;
  reviewFilter: ReviewFilter;
  selectedEventId: string | null;
  loading: boolean;
  error: string | null;
  onRecordingFilter: (value: string) => void;
  onReviewFilter: (value: ReviewFilter) => void;
  onSelect: (eventId: string) => void;
  onPage: (offset: number) => void;
  onRetry: () => void;
}) {
  return (
    <section className="event-register" aria-labelledby="events-title">
      <div className="register-heading">
        <div>
          <h2 id="events-title">Candidate events</h2>
          <p>Replay output awaiting or carrying a human observation.</p>
        </div>
        <span className="count-label">{page?.total ?? 0} records</span>
      </div>
      <div className="filter-row" aria-label="Event filters">
        <label>
          Recording
          <select value={recordingFilter} onChange={(event) => onRecordingFilter(event.target.value)}>
            <option value="">All recordings</option>
            {recordings.map((recording) => (
              <option value={recording.recording_id} key={recording.recording_id}>
                {recording.recording_id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Review
          <select value={reviewFilter} onChange={(event) => onReviewFilter(event.target.value as ReviewFilter)}>
            <option value="all">All states</option>
            <option value="unreviewed">Unreviewed</option>
            <option value="confirmed_feeding">Confirmed feeding observation</option>
            <option value="non_feeding">Non-feeding observation</option>
            <option value="uncertain">Uncertain</option>
          </select>
        </label>
      </div>

      {error ? (
        <div className="inline-message error register-error" role="alert">
          <strong>Events could not be loaded.</strong>
          <span>{error}</span>
          <button type="button" className="text-button" onClick={onRetry}>Retry</button>
        </div>
      ) : null}

      <div className="event-list" aria-busy={loading}>
        <div className="event-columns" aria-hidden="true">
          <span>Interval</span>
          <span>Peak</span>
          <span>Review</span>
          <span>Source</span>
        </div>
        {loading && !page ? (
          <>
            <div className="skeleton event" />
            <div className="skeleton event" />
            <div className="skeleton event" />
            <div className="skeleton event" />
          </>
        ) : null}
        {!loading && page && page.items.length === 0 ? (
          <div className="list-empty">
            <strong>No events match these filters.</strong>
            <span>Change the recording or review state, or submit evidence for processing.</span>
          </div>
        ) : null}
        <div className={loading && page ? "refreshing" : ""}>
          {page?.items.map((event) => {
            const state = event.review?.label ?? "unreviewed";
            const selected = event.event_id === selectedEventId;
            return (
              <button
                type="button"
                className={`event-row ${selected ? "selected" : ""}`}
                aria-pressed={selected}
                key={event.event_id}
                onClick={() => onSelect(event.event_id)}
              >
                <span className="event-interval">
                  <strong>{formatSeconds(event.start_time_s)}–{formatSeconds(event.end_time_s)}</strong>
                  <small title={event.event_id}>{shortId(event.event_id, 22)}</small>
                </span>
                <span className="measurement">{formatAmplitude(event.normalized_peak_max)}</span>
                <span className={`tag review ${state}`}>{reviewLabel(state)}</span>
                <span className="source-cell">
                  <span className={`tag ${event.provenance}`}>{event.provenance}</span>
                  <small>{shortId(event.recording_id, 16)}</small>
                </span>
              </button>
            );
          })}
        </div>
      </div>
      {page ? (
        <div className="pager" aria-label="Event pages">
          <button type="button" onClick={() => onPage(Math.max(0, page.offset - page.limit))} disabled={page.offset === 0 || loading}>
            Previous
          </button>
          <span>{page.total === 0 ? "0" : `${page.offset + 1}–${Math.min(page.total, page.offset + page.limit)}`} of {page.total}</span>
          <button type="button" onClick={() => onPage(page.offset + page.limit)} disabled={page.offset + page.limit >= page.total || loading}>
            Next
          </button>
        </div>
      ) : null}
    </section>
  );
}
