"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  AcousticEvent,
  ApiPage,
  EventDetail,
  Job,
  MonitorStatus,
  Recording,
  Review,
  ReviewFilter,
  VideoEvidence,
  Waveform,
} from "@/lib/api-types";
import { ApiError, apiRequest, jsonRequest } from "@/lib/client-api";
import { formatUtc, shortId } from "@/lib/format";
import { AccessGate, LoadingGate, OfflineGate } from "./AccessGate";
import { EventRegister } from "./EventRegister";
import { EvidenceInspector } from "./EvidenceInspector";
import { ImportPanel } from "./ImportPanel";
import { RecordingRail } from "./RecordingRail";
import { canAdmin, canImport, canReview, isIdentity, PLATFORM_API, type Identity } from "@/lib/platform";
import { ObservationPanel } from "./ObservationPanel";
import { DevicePanel } from "./DevicePanel";
import { AcquisitionPanel } from "./AcquisitionPanel";
import { IdentityPanel } from "./IdentityPanel";
import { AuditPanel } from "./AuditPanel";
import { LifecyclePanel } from "./LifecyclePanel";
import { CompanionWorkspace } from "./CompanionWorkspace";
import { RequestError, useResource } from "./PlatformCommon";
import { DigitalWorkspace } from "./DigitalWorkspace";
import { DigitalHubBanner } from "./DigitalHub";
import { useDigitalResource } from "@/lib/use-digital-resource";
import type { HubStateRead } from "@/lib/digital";

type WorkspaceTab = "evidence" | "observations" | "devices" | "acquisition" | "identity" | "audit" | "lifecycle" | "companions" | "digital";

type SessionPhase = "checking" | "locked" | "offline" | "ready";
const EMPTY_PAGE = <T,>(): ApiPage<T> => ({ items: [], total: 0, limit: 0, offset: 0 });

export function OperatorApp() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [tab, setTab] = useState<WorkspaceTab>("evidence");
  const [dirtyObservation, setDirtyObservation] = useState(false);
  const [dirtyCompanion, setDirtyCompanion] = useState(false);
  const [phase, setPhase] = useState<SessionPhase>("checking");
  const [gateMessage, setGateMessage] = useState<string | undefined>();
  const [status, setStatus] = useState<MonitorStatus | null>(null);
  const [recordings, setRecordings] = useState<ApiPage<Recording> | null>(null);
  const [jobs, setJobs] = useState<ApiPage<Job> | null>(null);
  const [events, setEvents] = useState<ApiPage<AcousticEvent> | null>(null);
  const [recordingOffset, setRecordingOffset] = useState(0);
  const [eventOffset, setEventOffset] = useState(0);
  const [recordingFilter, setRecordingFilter] = useState("");
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [waveform, setWaveform] = useState<Waveform | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [waveformLoading, setWaveformLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [dirtyReview, setDirtyReview] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [trackedJobIds, setTrackedJobIds] = useState<string[]>([]);
  const [submissionMessage, setSubmissionMessage] = useState<string | null>(null);
  const [digitalVersion, setDigitalVersion] = useState(0);
  const digitalHub = useDigitalResource<HubStateRead>(phase === "ready" && identity?.role !== "device" ? `${PLATFORM_API}/hub-state` : null, digitalVersion);
  const refreshDigital = useCallback(() => setDigitalVersion((value) => value + 1), []);
  useEffect(() => {
    if (phase !== "ready" || identity?.role === "device") return;
    const timer = setInterval(refreshDigital, 5_000);
    return () => clearInterval(timer);
  }, [phase, identity, refreshDigital]);

  const sessionFailure = useCallback((caught: unknown, fallback: string, setter: (message: string) => void) => {
    if (caught instanceof ApiError && caught.status === 401) {
      setGateMessage("The local session expired or was rejected. Enter the workspace access key again.");
      setPhase("locked");
      setIdentity(null);
      setStatus(null);
      setRecordings(null); setJobs(null); setEvents(null); setTrackedJobIds([]);
      return;
    }
    setter(caught instanceof ApiError ? caught.message : fallback);
  }, []);

  const checkSession = useCallback(async () => {
    setPhase("checking");
    setGateMessage(undefined);
    setRecordings(null); setJobs(null); setEvents(null);
    setRecordingFilter(""); setSelectedEventId(null); setRecordingOffset(0); setEventOffset(0);
    setDetail(null); setWaveform(null); setTrackedJobIds([]); setSubmissionMessage(null);
    try {
      const actor = await apiRequest<Identity>(`${PLATFORM_API}/identity`);
      if (!isIdentity(actor)) throw new Error("Invalid API identity");
      setIdentity(actor);
      if (actor.role === "device") setTab("devices");
      else setStatus(await apiRequest<MonitorStatus>("/api/backend/api/v1/status"));
      setPhase("ready");
      setRefreshVersion((value) => value + 1);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        setPhase("locked");
        return;
      }
      setGateMessage(caught instanceof ApiError ? caught.message : "The local API is offline or unreachable.");
      setPhase("offline");
    }
  }, []);

  useEffect(() => {
    void checkSession();
  }, [checkSession]);

  useEffect(() => {
    if (phase !== "ready" || !identity || identity.role === "device") return;
    let active = true;
    setOverviewLoading(true);
    setOverviewError(null);
    Promise.all([
      apiRequest<MonitorStatus>("/api/backend/api/v1/status"),
      apiRequest<ApiPage<Recording>>(`/api/backend/api/v1/recordings?limit=50&offset=${recordingOffset}`),
      apiRequest<ApiPage<Job>>("/api/backend/api/v1/jobs?limit=10&offset=0"),
    ])
      .then(([nextStatus, nextRecordings, nextJobs]) => {
        if (!active) return;
        setStatus(nextStatus);
        setRecordings(nextRecordings);
        setJobs(nextJobs);
        const activeIds = nextJobs.items
          .filter((job) => job.status === "queued" || job.status === "running")
          .map((job) => job.id);
        if (activeIds.length) {
          setTrackedJobIds((current) => Array.from(new Set([...current, ...activeIds])));
        }
      })
      .catch((caught) => {
        if (active) sessionFailure(caught, "Workspace status could not be loaded.", setOverviewError);
      })
      .finally(() => active && setOverviewLoading(false));
    return () => {
      active = false;
    };
  }, [phase, identity, recordingOffset, refreshVersion, sessionFailure]);

  useEffect(() => {
    if (phase !== "ready" || !identity || identity.role === "device") return;
    let active = true;
    const query = new URLSearchParams({ limit: "25", offset: String(eventOffset) });
    if (recordingFilter) query.set("recording_id", recordingFilter);
    if (reviewFilter !== "all") query.set("review", reviewFilter);
    setEventsLoading(true);
    setEventsError(null);
    apiRequest<ApiPage<AcousticEvent>>(`/api/backend/api/v1/events?${query}`)
      .then((page) => active && setEvents(page))
      .catch((caught) => {
        if (active) sessionFailure(caught, "Candidate events could not be loaded.", setEventsError);
      })
      .finally(() => active && setEventsLoading(false));
    return () => {
      active = false;
    };
  }, [phase, identity, recordingFilter, reviewFilter, eventOffset, refreshVersion, sessionFailure]);

  useEffect(() => {
    if (phase !== "ready" || !selectedEventId) {
      setDetail(null);
      setWaveform(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setWaveformLoading(true);
    setDetailError(null);
    setWaveform(null);
    apiRequest<EventDetail>(`/api/backend/api/v1/events/${encodeURIComponent(selectedEventId)}`)
      .then(async (nextDetail) => {
        if (!active) return;
        setDetail(nextDetail);
        setDetailLoading(false);
        try {
          const nextWaveform = await apiRequest<Waveform>(
            `/api/backend/api/v1/recordings/${encodeURIComponent(nextDetail.recording.recording_id)}/waveform?points=512`,
          );
          if (active) setWaveform(nextWaveform);
        } catch (caught) {
          if (active) sessionFailure(caught, "The waveform envelope could not be loaded.", setDetailError);
        } finally {
          if (active) setWaveformLoading(false);
        }
      })
      .catch((caught) => {
        if (active) {
          sessionFailure(caught, "The selected event could not be loaded.", setDetailError);
          setDetailLoading(false);
          setWaveformLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [phase, selectedEventId, refreshVersion, sessionFailure]);

  useEffect(() => {
    if (phase !== "ready" || trackedJobIds.length === 0) return;
    let active = true;
    const timer = setTimeout(async () => {
      const results = await Promise.allSettled(
        trackedJobIds.map((id) => apiRequest<Job>(`/api/backend/api/v1/jobs/${encodeURIComponent(id)}`)),
      );
      if (!active) return;
      const updates = results.flatMap((result) => (result.status === "fulfilled" ? [result.value] : []));
      if (updates.length) {
        setJobs((current) => {
          const base = current ?? EMPTY_PAGE<Job>();
          const byId = new Map(base.items.map((job) => [job.id, job]));
          for (const update of updates) byId.set(update.id, update);
          return { ...base, items: Array.from(byId.values()).sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 10) };
        });
      }
      const completed = new Set(
        updates.filter((job) => job.status === "succeeded" || job.status === "failed").map((job) => job.id),
      );
      if (completed.size) {
        setTrackedJobIds((ids) => ids.filter((id) => !completed.has(id)));
        setRefreshVersion((value) => value + 1);
      } else {
        setRefreshVersion((value) => value + 1);
      }
    }, 1_200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [phase, trackedJobIds, refreshVersion]);

  function permitContextChange(change: () => void) {
    if ((dirtyReview || dirtyObservation || dirtyCompanion) && !window.confirm("Discard unsaved review, observation or companion-file changes and leave this context?")) return;
    setDirtyCompanion(false);
    setDirtyObservation(false);
    setDirtyReview(false);
    change();
  }

  function changeRecording(value: string) {
    permitContextChange(() => {
      setRecordingFilter(value);
      setEventOffset(0);
      setSelectedEventId(null);
      setDetail(null);
      setWaveform(null);
    });
  }

  function changeReview(value: ReviewFilter) {
    permitContextChange(() => {
      setReviewFilter(value);
      setEventOffset(0);
      setSelectedEventId(null);
      setDetail(null);
      setWaveform(null);
    });
  }

  function selectEvent(eventId: string) {
    if (eventId === selectedEventId) return;
    permitContextChange(() => {
      setSelectedEventId(eventId);
      setDetail(null);
      setWaveform(null);
    });
  }

  function trackSubmission(job: Job) {
    setSubmissionMessage(`Job ${shortId(job.id, 20)} was accepted as ${job.status}.`);
    setJobs((current) => {
      const base = current ?? EMPTY_PAGE<Job>();
      return { ...base, total: Math.max(base.total, base.items.length + 1), items: [job, ...base.items.filter((item) => item.id !== job.id)].slice(0, 10) };
    });
    if (job.status === "queued" || job.status === "running") {
      setTrackedJobIds((ids) => (ids.includes(job.id) ? ids : [...ids, job.id]));
    } else {
      setRefreshVersion((value) => value + 1);
    }
  }

  function reviewSaved(review: Review) {
    setDetail((current) => current ? { ...current, event: { ...current.event, review } } : current);
    setEvents((current) => current ? {
      ...current,
      items: current.items.map((event) => event.event_id === selectedEventId ? { ...event, review } : event),
    } : current);
    setDirtyReview(false);
    setRefreshVersion((value) => value + 1);
  }

  function videoAttached(video: VideoEvidence) {
    setDetail((current) => current ? { ...current, recording: { ...current.recording, video } } : current);
    setRecordings((current) => current ? {
      ...current,
      items: current.items.map((recording) => recording.recording_id === detail?.recording.recording_id ? { ...recording, video } : recording),
    } : current);
  }

  async function logout() {
    try {
      await apiRequest<{ authenticated: false }>("/api/session", jsonRequest("DELETE"));
    } finally {
      setPhase("locked");
      setIdentity(null);
      setStatus(null);
      setRecordings(null);
      setJobs(null);
      setEvents(null);
      setDetail(null);
      setWaveform(null);
      setSelectedEventId(null);
      setTrackedJobIds([]);
    }
  }

  const selectedRecording = useResource<Recording>(phase === "ready" && identity?.role !== "device" && recordingFilter ? `${PLATFORM_API}/recordings/${encodeURIComponent(recordingFilter)}` : null);
  const recordingItems = recordings?.items ?? [];
  const workspaceEmpty = Boolean(status && status.recordings === 0 && status.events === 0);
  const activeJobs = useMemo(() => jobs?.items.filter((job) => job.status === "queued" || job.status === "running") ?? [], [jobs]);

  if (phase === "checking") return <LoadingGate />;
  if (phase === "locked") return <AccessGate message={gateMessage} onAuthenticated={checkSession} />;
  if (phase === "offline") return <OfflineGate message={gateMessage ?? "The local API is offline or unreachable."} onRetry={checkSession} />;

  if (!identity) return <LoadingGate />;

  return (
    <div className="app-shell">
      <header className="utility-header">
        <div className="product-lockup">
          <span className="brand-mark" aria-hidden="true">A</span>
          <div>
            <strong>AEOLUS</strong>
            <span>Poseidon · local evidence monitor</span>
          </div>
        </div>
        <div className="mode-boundary" aria-label="Operating boundary">
          <span className="state-dot" />
          <span><strong>Monitor only</strong> · output unavailable</span>
        </div>
        <div className="header-actions">
          <span className="tag synthetic">Synthetic records stay marked</span>
          <button type="button" className="text-button" onClick={logout}>Lock workspace</button>
        </div>
      </header>

      <main className="operator-main">
        <section className="identity-strip" aria-label="Authenticated identity">
          <span>Actor <strong className="full-identifier">{identity.subject}</strong></span>
          <span>Role <strong>{identity.role}</strong></span>
          <span>Mode <strong>{identity.auth_mode}</strong></span>
          <span>Sites <strong className="full-identifier">{identity.site_ids.join(", ") || (identity.auth_mode === "local_development_key" ? "Local development authority" : "No sites")}</strong></span>
          {identity.device_id ? <span>Device <strong className="full-identifier">{identity.device_id}</strong></span> : null}
        </section>
        <nav className="workspace-nav" aria-label="Workbench sections">
          {([["evidence", "Evidence review"], ["observations", "Observation intervals"], ["devices", "Devices & telemetry"], ["acquisition", "Acquisition sessions"], ["companions", "Imported companions"], ["identity", "Identity & access"], ["audit", "Audit trail"], ["lifecycle", "Signed local lifecycle"], ["digital", "Digital operations"]] as [WorkspaceTab, string][]).map(([value, label]) => <button type="button" key={value} aria-current={tab === value ? "page" : undefined} disabled={(identity.role === "device" && ["evidence", "observations", "acquisition", "lifecycle", "digital"].includes(value)) || (value === "audit" && !canAdmin(identity))} onClick={() => { if (tab !== value) permitContextChange(() => setTab(value)); }}>{label}</button>)}
        </nav>
        {identity.role !== "device" ? <DigitalHubBanner hub={digitalHub.data} error={digitalHub.error} loading={digitalHub.loading} onRefresh={refreshDigital} /> : null}
        {tab === "digital" ? <DigitalWorkspace identity={identity} hub={digitalHub.data} version={digitalVersion} onRefresh={refreshDigital} /> : null}
        {tab === "evidence" ? <>
        <section className="status-strip" aria-label="Workspace status" aria-busy={overviewLoading}>
          <div><span>API state</span><strong>{status?.state ?? "checking"}</strong></div>
          <div><span>Recordings</span><strong>{status?.recordings ?? "—"}</strong></div>
          <div><span>Candidate events</span><strong>{status?.events ?? "—"}</strong></div>
          <div><span>Queue</span><strong>{status ? `${status.jobs.queued} queued · ${status.jobs.running} running` : "—"}</strong></div>
          <div><span>Failed jobs</span><strong className={status?.jobs.failed ? "failure-text" : ""}>{status?.jobs.failed ?? "—"}</strong></div>
          <button className="text-button" type="button" onClick={() => setRefreshVersion((value) => value + 1)} disabled={overviewLoading}>
            {overviewLoading ? "Refreshing…" : "Refresh"}
          </button>
        </section>

        {overviewError ? (
          <div className="inline-message error workspace-error" role="alert">
            <strong>Workspace status is stale.</strong>
            <span>{overviewError}</span>
            <button className="text-button" type="button" onClick={() => setRefreshVersion((value) => value + 1)}>Retry</button>
          </div>
        ) : null}

        <ImportPanel empty={workspaceEmpty} onSubmitted={trackSubmission} allowed={canImport(identity)} />

        <section className="job-traveler" aria-labelledby="jobs-title">
          <div className="job-heading">
            <h2 id="jobs-title">Processing traveler</h2>
            <span>{activeJobs.length ? `${activeJobs.length} active` : "Queue clear"}</span>
          </div>
          {submissionMessage ? <p className="submission-message" role="status">{submissionMessage}</p> : null}
          <div className="job-list">
            {jobs?.items.slice(0, 5).map((job) => (
              <div className="job-row" key={job.id}>
                <span className={`job-state ${job.status}`}><i />{job.status}</span>
                <strong title={job.id}>{shortId(job.id, 22)}</strong>
                <span title={job.recording_id}>{shortId(job.recording_id, 20)}</span>
                <time dateTime={job.updated_at}>{formatUtc(job.updated_at)}</time>
                {job.error ? <span className="job-error" title={job.error}>{job.error}</span> : <span className="job-ok">{job.status === "succeeded" ? "record accepted" : "awaiting terminal state"}</span>}
              </div>
            ))}
            {jobs && jobs.items.length === 0 ? <p className="job-empty">No submitted processing jobs.</p> : null}
            {!jobs && overviewLoading ? <div className="skeleton job" /> : null}
          </div>
        </section>

        <div className="workbench">
          <RecordingRail
            page={recordings}
            selected={recordingFilter}
            loading={overviewLoading}
            onSelect={changeRecording}
            onPage={setRecordingOffset}
          />
          <EventRegister
            page={events}
            recordings={recordingItems}
            recordingFilter={recordingFilter}
            reviewFilter={reviewFilter}
            selectedEventId={selectedEventId}
            loading={eventsLoading}
            error={eventsError}
            onRecordingFilter={changeRecording}
            onReviewFilter={changeReview}
            onSelect={selectEvent}
            onPage={setEventOffset}
            onRetry={() => setRefreshVersion((value) => value + 1)}
          />
          <EvidenceInspector
            detail={detail}
            canWrite={canReview(identity)}
            waveform={waveform}
            loading={detailLoading}
            waveformLoading={waveformLoading}
            error={detailError}
            onRetry={() => setRefreshVersion((value) => value + 1)}
            onDirtyChange={setDirtyReview}
            onReviewSaved={reviewSaved}
            onVideoAttached={videoAttached}
          />
        </div>
        </> : null}
        {tab === "observations" ? <div className="observation-workbench"><RecordingRail page={recordings} selected={recordingFilter} loading={overviewLoading} onSelect={changeRecording} onPage={setRecordingOffset} /><div className="observation-content"><RequestError message={selectedRecording.error} retry={selectedRecording.reload} />{selectedRecording.data ? <ObservationPanel key={selectedRecording.data.recording_id} recording={selectedRecording.data} identity={identity} onDirtyChange={setDirtyObservation} /> : <section className="platform-panel inspection-block"><h2>Observe any recording</h2><p>{selectedRecording.loading ? "Loading the selected recording…" : "Select a recording to inspect and annotate an independent interval. No candidate is required, including recordings with zero candidates."}</p></section>}</div></div> : null}
        {tab === "companions" ? <CompanionWorkspace identity={identity} recordings={recordings} jobs={jobs} initialRecordingId={recordingFilter} loading={overviewLoading} onRecordPage={setRecordingOffset} onSubmitted={trackSubmission} onDirtyChange={setDirtyCompanion} /> : null}
        {tab === "devices" ? <DevicePanel identity={identity} /> : null}
        {tab === "acquisition" ? <AcquisitionPanel identity={identity} recording={selectedRecording.data} /> : null}
        {tab === "identity" ? <IdentityPanel identity={identity} /> : null}
        {tab === "audit" ? <AuditPanel identity={identity} /> : null}
        {tab === "lifecycle" ? <LifecyclePanel identity={identity} /> : null}
      </main>
    </div>
  );
}
