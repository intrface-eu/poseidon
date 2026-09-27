"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { EventDetail, Review, ReviewLabel, VideoEvidence, Waveform } from "@/lib/api-types";
import { ApiError, apiRequest, jsonRequest } from "@/lib/client-api";
import { formatAmplitude, formatSeconds, formatUtc, reviewLabel } from "@/lib/format";
import { WaveformChart } from "./WaveformChart";

const MAX_VIDEO_BYTES = 64 * 1024 * 1024;

type ReviewDraft = {
  label: ReviewLabel | "";
  notes: string;
  reviewer: string;
};

function reviewDraft(review: Review | null): ReviewDraft {
  return {
    label: review?.label ?? "",
    notes: review?.notes ?? "",
    reviewer: review?.reviewer ?? "",
  };
}

function sameDraft(left: ReviewDraft, right: ReviewDraft) {
  return left.label === right.label && left.notes === right.notes && left.reviewer === right.reviewer;
}

export function EvidenceInspector({
  detail,
  waveform,
  loading,
  waveformLoading,
  error,
  onRetry,
  onDirtyChange,
  onReviewSaved,
  onVideoAttached,
  canWrite = true,
}: {
  detail: EventDetail | null;
  waveform: Waveform | null;
  loading: boolean;
  waveformLoading: boolean;
  error: string | null;
  onRetry: () => void;
  onDirtyChange: (dirty: boolean) => void;
  onReviewSaved: (review: Review) => void;
  onVideoAttached: (video: VideoEvidence) => void;
  canWrite?: boolean;
}) {
  if (!detail && loading) {
    return (
      <aside className="evidence-inspector" aria-label="Loading event detail" aria-busy="true">
        <div className="inspector-skeleton">
          <div className="skeleton line wide" />
          <div className="skeleton line" />
          <div className="skeleton chart" />
          <div className="skeleton field" />
        </div>
      </aside>
    );
  }

  if (!detail && error) {
    return (
      <aside className="evidence-inspector empty-inspector" aria-labelledby="inspector-error-title">
        <h2 id="inspector-error-title">Event detail unavailable</h2>
        <p>{error}</p>
        <button type="button" className="button secondary" onClick={onRetry}>Retry event</button>
      </aside>
    );
  }

  if (!detail) {
    return (
      <aside className="evidence-inspector empty-inspector" aria-labelledby="inspector-title">
        <h2 id="inspector-title">Inspect one candidate</h2>
        <p>Select an event from the register to view its recording context, source-derived waveform, optional video, and human review.</p>
        <ol className="inspection-steps">
          <li><span>1</span> Check provenance and calibration.</li>
          <li><span>2</span> Inspect the marked interval against the full recording envelope.</li>
          <li><span>3</span> Save an operator observation with a revision check.</li>
        </ol>
      </aside>
    );
  }

  return (
    <aside className={`evidence-inspector ${loading ? "refreshing" : ""}`} aria-labelledby="inspector-title">
      <header className="inspector-heading">
        <div>
          <h2 id="inspector-title">Evidence inspection</h2>
          <p className="full-identifier event-identifier">{detail.event.event_id}</p>
        </div>
        <span className={`tag ${detail.event.provenance}`}>{detail.event.provenance}</span>
      </header>

      <section className="inspection-block context-block" aria-labelledby="context-title">
        <div className="block-heading">
          <h3 id="context-title">Source context</h3>
        </div>
        <dl className="identifier-ledger" aria-label="Full evidence identifiers">
          <div><dt>Recording ID</dt><dd className="full-identifier">{detail.recording.recording_id}</dd></div>
          <div><dt>Run ID</dt><dd className="full-identifier">{detail.event.run_id}</dd></div>
        </dl>
        <dl className="metadata-grid">
          <div><dt>Device</dt><dd>{detail.event.device_id}</dd></div>
          <div><dt>Site / zone</dt><dd>{detail.event.site_id} / {detail.event.zone_id}</dd></div>
          <div><dt>Declared start</dt><dd>{formatUtc(detail.recording.started_at)}</dd></div>
          <div><dt>Imported</dt><dd>{formatUtc(detail.recording.imported_at)}</dd></div>
          <div><dt>Candidate interval</dt><dd>{formatSeconds(detail.event.start_time_s)}–{formatSeconds(detail.event.end_time_s)}</dd></div>
          <div><dt>Duration</dt><dd>{formatSeconds(detail.event.end_time_s - detail.event.start_time_s)}</dd></div>
          <div><dt>Normalized peak</dt><dd>{formatAmplitude(detail.event.normalized_peak_max)}</dd></div>
          <div><dt>Normalized RMS</dt><dd>{formatAmplitude(detail.event.normalized_rms_max)}</dd></div>
          <div><dt>Sample format</dt><dd>{detail.event.sample_rate_hz.toLocaleString()} Hz · {detail.event.channel_count} ch</dd></div>
          <div><dt>Calibration</dt><dd><span className="tag calibration">{detail.event.calibration_status}</span></dd></div>
        </dl>
        <div className="boundary-note compact-boundary">
          <strong>Candidate only</strong>
          <span>Replay found normalized amplitude activity. It did not identify a species or establish feeding.</span>
        </div>
      </section>

      <section className="inspection-block" aria-label="Waveform inspection">
        {waveformLoading && !waveform ? <div className="skeleton chart" /> : null}
        {waveform ? <WaveformChart waveform={waveform} event={detail.event} /> : null}
        {!waveformLoading && !waveform ? (
          <div className="inline-message error" role="alert">
            <strong>Waveform unavailable.</strong>
            <span>{error ?? "The API did not return the recording envelope."}</span>
            <button type="button" className="text-button" onClick={onRetry}>Retry</button>
          </div>
        ) : null}
      </section>

      <VideoEvidencePanel detail={detail} onVideoAttached={onVideoAttached} canWrite={canWrite} />
      <ReviewPanel detail={detail} onDirtyChange={onDirtyChange} onReviewSaved={onReviewSaved} canWrite={canWrite} />
    </aside>
  );
}

function ReviewPanel({
  detail,
  onDirtyChange,
  onReviewSaved,
  canWrite,
}: {
  detail: EventDetail;
  canWrite: boolean;
  onDirtyChange: (dirty: boolean) => void;
  onReviewSaved: (review: Review) => void;
}) {
  const initial = useMemo(() => reviewDraft(detail.event.review), [detail.event.review]);
  const [draft, setDraft] = useState<ReviewDraft>(initial);
  const [baseline, setBaseline] = useState<ReviewDraft>(initial);
  const [baseRevision, setBaseRevision] = useState(detail.event.review?.revision ?? 0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Review | null | undefined>(undefined);
  const currentEvent = useRef(detail.event.event_id);

  useEffect(() => {
    if (currentEvent.current !== detail.event.event_id) {
      currentEvent.current = detail.event.event_id;
      const next = reviewDraft(detail.event.review);
      setDraft(next);
      setBaseline(next);
      setBaseRevision(detail.event.review?.revision ?? 0);
      setError(null);
      setConflict(undefined);
    }
  }, [detail.event.event_id, detail.event.review]);

  const dirty = !sameDraft(draft, baseline);
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  function validateDraft(): string | null {
    if (!draft.label) return "Choose an observation label.";
    if (!draft.reviewer.trim()) return "Enter the operator name used for this review record.";
    if (draft.label === "confirmed_feeding" && !draft.notes.trim()) {
      return "Confirmed feeding observations require notes describing the basis.";
    }
    return null;
  }

  async function persistReview(expectedRevision: number) {
    if (!canWrite) return;
    const validation = validateDraft();
    if (validation) {
      setError(validation);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const review = await apiRequest<Review>(
        `/api/backend/api/v1/events/${encodeURIComponent(detail.event.event_id)}/review`,
        jsonRequest("PUT", {
          label: draft.label,
          notes: draft.notes,
          reviewer: draft.reviewer,
          expected_revision: expectedRevision,
        }),
      );
      const savedDraft = reviewDraft(review);
      setDraft(savedDraft);
      setBaseline(savedDraft);
      setBaseRevision(review.revision);
      setConflict(undefined);
      onReviewSaved(review);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        try {
          const latest = await apiRequest<EventDetail>(`/api/backend/api/v1/events/${encodeURIComponent(detail.event.event_id)}`);
          const latestReview = latest.event.review;
          setConflict(latestReview);
          setBaseRevision(latestReview?.revision ?? 0);
          setError("A newer review exists. Your draft is preserved below beside the latest server review.");
        } catch {
          setError("A newer review exists, but it could not be reloaded. Your draft is still preserved.");
        }
      } else {
        setError(caught instanceof ApiError ? caught.message : "The review could not be saved.");
      }
    } finally {
      setSaving(false);
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void persistReview(baseRevision);
  }

  function replaceDraftWithServerReview() {
    const latest = conflict ?? null;
    const latestDraft = reviewDraft(latest);
    setDraft(latestDraft);
    setBaseline(latestDraft);
    setBaseRevision(latest?.revision ?? 0);
    setConflict(undefined);
    setError(null);
    if (latest) onReviewSaved(latest);
  }

  function overwriteDisplayedRevision() {
    if (conflict === undefined) return;
    void persistReview(conflict?.revision ?? 0);
  }

  return (
    <section className="inspection-block review-block" aria-labelledby="review-title">
      <div className="block-heading">
        <div>
          <h3 id="review-title">Human observation</h3>
          <p>Operator-entered, not identity-attested.</p>
        </div>
        <span className="revision-stamp">revision {baseRevision}</span>
      </div>
      {!canWrite ? <p className="platform-note">Your role can inspect this candidate but cannot save reviews.</p> : null}
      <form className="review-form" onSubmit={save}>
        <div className="field-group">
          <label htmlFor={`review-label-${detail.event.event_id}`}>Observation label</label>
          <select
            id={`review-label-${detail.event.event_id}`}
            value={draft.label}
            onChange={(event) => setDraft((value) => ({ ...value, label: event.target.value as ReviewLabel | "" }))}
            disabled={saving || !canWrite}
            required
          >
            <option value="">Choose a label</option>
            <option value="confirmed_feeding">Confirmed feeding observation</option>
            <option value="non_feeding">Non-feeding observation</option>
            <option value="uncertain">Uncertain</option>
          </select>
        </div>
        <div className="field-group">
          <label htmlFor={`reviewer-${detail.event.event_id}`}>Reviewer</label>
          <input
            id={`reviewer-${detail.event.event_id}`}
            value={draft.reviewer}
            onChange={(event) => setDraft((value) => ({ ...value, reviewer: event.target.value }))}
            maxLength={80}
            disabled={saving || !canWrite}
            required
          />
          <small>{draft.reviewer.length}/80 characters</small>
        </div>
        <div className="field-group full">
          <label htmlFor={`notes-${detail.event.event_id}`}>Notes {draft.label === "confirmed_feeding" ? "(required)" : "(optional)"}</label>
          <textarea
            id={`notes-${detail.event.event_id}`}
            value={draft.notes}
            onChange={(event) => setDraft((value) => ({ ...value, notes: event.target.value }))}
            maxLength={2000}
            rows={4}
            disabled={saving || !canWrite}
            required={draft.label === "confirmed_feeding"}
          />
          <small>{draft.notes.length}/2000 characters</small>
        </div>
        {error ? (
          <div className={`inline-message ${conflict !== undefined ? "warning conflict-message" : "error"} full`} role="alert">
            <strong>{conflict !== undefined ? "Revision conflict." : "Review not saved."}</strong>
            <span>{error}</span>
            {conflict !== undefined ? (
              <>
                <div className="conflict-comparison">
                  <section className="conflict-version" aria-labelledby="server-review-title">
                    <h4 id="server-review-title">Latest server review</h4>
                    {conflict ? (
                      <dl>
                        <div><dt>Revision</dt><dd>{conflict.revision}</dd></div>
                        <div><dt>Label</dt><dd><span>{reviewLabel(conflict.label)}</span><code>{conflict.label}</code></dd></div>
                        <div><dt>Reviewer</dt><dd>{conflict.reviewer}</dd></div>
                        <div><dt>Notes</dt><dd className="conflict-notes">{conflict.notes || "No notes"}</dd></div>
                        <div><dt>Timestamp</dt><dd><time dateTime={conflict.updated_at}>{conflict.updated_at}</time></dd></div>
                      </dl>
                    ) : <p>No server review was returned.</p>}
                  </section>
                  <section className="conflict-version" aria-labelledby="preserved-draft-title">
                    <h4 id="preserved-draft-title">Preserved draft</h4>
                    <dl>
                      <div><dt>Label</dt><dd><span>{draft.label ? reviewLabel(draft.label) : "Not selected"}</span>{draft.label ? <code>{draft.label}</code> : null}</dd></div>
                      <div><dt>Reviewer</dt><dd>{draft.reviewer || "Not entered"}</dd></div>
                      <div><dt>Notes</dt><dd className="conflict-notes">{draft.notes || "No notes"}</dd></div>
                    </dl>
                  </section>
                </div>
                <p className="overwrite-warning">Saving your draft over the displayed revision creates a new review revision only if that server revision is still current.</p>
                <div className="conflict-actions">
                  <button type="button" className="button secondary" onClick={replaceDraftWithServerReview} disabled={saving || !canWrite}>
                    Replace draft with server review
                  </button>
                  <button type="button" className="button primary" onClick={overwriteDisplayedRevision} disabled={saving || !canWrite}>
                    {saving ? "Saving draft…" : `Save my draft over revision ${conflict?.revision ?? 0}`}
                  </button>
                </div>
              </>
            ) : null}
          </div>
        ) : null}
        <div className="form-actions full">
          <span>{dirty ? "Unsaved changes" : detail.event.review ? `Saved ${formatUtc(detail.event.review.updated_at)}` : "No review saved"}</span>
          <button className="button primary" type="submit" disabled={saving || !canWrite || !dirty || conflict !== undefined}>
            {saving ? "Saving review…" : conflict !== undefined ? "Resolve conflict above" : "Save review"}
          </button>
        </div>
      </form>
      {detail.event.review ? (
        <p className="saved-review-summary">
          Current server record: <strong>{reviewLabel(detail.event.review.label)}</strong> by {detail.event.review.reviewer}.
        </p>
      ) : null}
    </section>
  );
}

function VideoEvidencePanel({
  detail,
  onVideoAttached,
  canWrite = true,
}: {
  detail: EventDetail;
  onVideoAttached: (video: VideoEvidence) => void;
  canWrite?: boolean;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decoderError, setDecoderError] = useState(false);
  const video = detail.recording.video;
  const source = `/api/backend/api/v1/recordings/${encodeURIComponent(detail.recording.recording_id)}/video`;

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canWrite) return;
    const form = new FormData(event.currentTarget);
    const file = form.get("video");
    const offsetValue = form.get("offset_s");
    const offset = typeof offsetValue === "string" ? Number(offsetValue) : Number.NaN;
    if (!(file instanceof File) || file.size === 0) {
      setError("Choose an MP4 evidence file.");
      return;
    }
    if (file.size > MAX_VIDEO_BYTES) {
      setError("The video exceeds the 64 MiB development limit.");
      return;
    }
    if (file.type && file.type !== "video/mp4") {
      setError("The evidence attachment must be an MP4 file.");
      return;
    }
    if (!Number.isFinite(offset)) {
      setError("Enter a finite alignment offset in seconds.");
      return;
    }

    setUploading(true);
    setError(null);
    try {
      const metadata = await apiRequest<VideoEvidence>(
        `/api/backend/api/v1/recordings/${encodeURIComponent(detail.recording.recording_id)}/video`,
        { body: form, method: "POST" },
      );
      formRef.current?.reset();
      onVideoAttached(metadata);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The video evidence could not be attached.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <section className="inspection-block video-block" aria-labelledby="video-title">
      <div className="block-heading">
        <div>
          <h3 id="video-title">Optional video evidence</h3>
          <p>Visual context can support a human observation. It does not verify synchronization.</p>
        </div>
        {video ? <span className="tag attached">attached</span> : <span className="tag neutral">not attached</span>}
      </div>
      {video ? (
        <div className="video-evidence">
          <video
            key={`${detail.recording.recording_id}-${video.sha256}`}
            controls
            muted
            playsInline
            preload="metadata"
            src={source}
            onError={() => setDecoderError(true)}
            onLoadedMetadata={() => setDecoderError(false)}
          >
            This browser cannot play the attached video. The file remains stored as evidence.
          </video>
          <dl className="video-metadata">
            <div><dt>Alignment</dt><dd>Unverified · operator declared</dd></div>
            <div><dt>Offset</dt><dd>{video.offset_s >= 0 ? "+" : ""}{video.offset_s.toFixed(3)} s</dd></div>
            <div><dt>Attached</dt><dd>{formatUtc(video.uploaded_at)}</dd></div>
            <div><dt>SHA-256</dt><dd className="full-identifier">{video.sha256}</dd></div>
          </dl>
          {decoderError ? (
            <div className="inline-message warning" role="alert">
              <strong>Browser decoder could not open this MP4.</strong>
              <span>The attachment is still retained. Use a browser-supported MP4 encoding to preview it here.</span>
            </div>
          ) : null}
        </div>
      ) : (
        <form className="video-upload" onSubmit={upload} ref={formRef}>
          <div className="field-group">
            <label htmlFor={`video-${detail.recording.recording_id}`}>MP4 evidence</label>
            <input id={`video-${detail.recording.recording_id}`} name="video" type="file" accept="video/mp4,.mp4" required disabled={uploading || !canWrite} />
            <small>Up to 64 MiB. Attachment cannot replace an existing file.</small>
          </div>
          <div className="field-group offset-field">
            <label htmlFor={`offset-${detail.recording.recording_id}`}>Declared offset (seconds)</label>
            <input id={`offset-${detail.recording.recording_id}`} name="offset_s" type="number" step="0.001" defaultValue="0" required disabled={uploading || !canWrite} />
            <small>Operator-declared timing value; alignment remains unverified.</small>
          </div>
          <button className="button secondary" type="submit" disabled={uploading || !canWrite}>
            {uploading ? "Attaching video…" : "Attach video evidence"}
          </button>
          {error ? (
            <div className="inline-message error full" role="alert">
              <strong>Video not attached.</strong>
              <span>{error}</span>
            </div>
          ) : null}
        </form>
      )}
    </section>
  );
}
