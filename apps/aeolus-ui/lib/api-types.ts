export type ReviewLabel = "confirmed_feeding" | "non_feeding" | "uncertain";
export type ReviewFilter = "all" | "unreviewed" | ReviewLabel;

export type ApiPage<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

export type MonitorStatus = {
  mode: "monitor_only";
  emission_enabled: false;
  state: string;
  uptime_s: number;
  recordings: number;
  events: number;
  jobs: {
    queued: number;
    running: number;
    failed: number;
  };
};

export type Job = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  recording_id: string;
  created_at: string;
  updated_at: string;
  error: string | null;
};

export type VideoEvidence = {
  sha256: string;
  offset_s: number;
  uploaded_at: string;
  alignment: "operator_declared";
};

export type Recording = {
  schema_version: number;
  recording_id: string;
  site_id: string;
  zone_id: string;
  device_id: string;
  started_at: string;
  provenance: "field" | "synthetic";
  wav_sha256: string;
  calibration_status: "uncalibrated";
  duration_s: number;
  sample_rate_hz: number;
  channel_count: number;
  event_count: number;
  reviewed_count: number;
  imported_at: string;
  video: VideoEvidence | null;
};

export type Review = {
  label: ReviewLabel;
  notes: string;
  reviewer: string;
  revision: number;
  updated_at: string;
};

export type AcousticEvent = {
  schema_version: number;
  event_id: string;
  recording_id: string;
  site_id: string;
  zone_id: string;
  device_id: string;
  event_type: "acoustic_candidate";
  source: "replay";
  provenance: "field" | "synthetic";
  start_frame: number;
  end_frame: number;
  start_time_s: number;
  end_time_s: number;
  sample_rate_hz: number;
  channel_count: number;
  normalized_peak_max: number;
  normalized_rms_max: number;
  amplitude_units: "normalized_pcm16_full_scale";
  calibration_status: "uncalibrated";
  detector_version: string;
  detector_config_id: string;
  run_id: string;
  emission_enabled: false;
  review: Review | null;
};

export type EventDetail = {
  event: AcousticEvent;
  recording: Recording;
};

export type WaveformBucket = {
  start_s: number;
  end_s: number;
  min: number;
  max: number;
};

export type Waveform = {
  recording_id: string;
  duration_s: number;
  sample_rate_hz: number;
  channel_count: number;
  amplitude_units: "normalized_pcm16_full_scale";
  calibration_status: "uncalibrated";
  buckets: WaveformBucket[];
};

export type ApiErrorPayload = {
  error?: {
    code?: string;
    message?: string;
  };
};
