"use client";

import { useState } from "react";
import type { ApiPage } from "@/lib/api-types";
import { PLATFORM_API } from "@/lib/platform";
import { parseCalibration, type CalibrationRead } from "../../../libs/proto-ts/src/calibration-v1";
import { Ledger, PageControls, RequestError } from "./PlatformCommon";
import { useDigitalResource as useResource } from "@/lib/use-digital-resource";

export function CalibrationEntry({ item }: { item: CalibrationRead }) {
  const { validity } = item;
  let record;
  try { record = parseCalibration(item.record); }
  catch { return <RequestError message="The API calibration record failed the shared digital-only contract. No calibration claim is shown." />; }
  return <div className="inspection-block" data-calibration-id={record.record_id} data-calibration-validity={validity}>
    <h3 className="full-identifier">{record.record_id}</h3><p><strong>DIGITAL_ONLY=true · Not physical calibration.</strong></p>
    <Ledger rows={[["API validity", validity], ["Instrument", record.instrument_id], ["Quantity", record.quantity], ["Declared UCUM unit", record.unit], ["Value (decimal text)", record.value], ["Uncertainty (decimal text)", record.uncertainty.value], ["Coverage factor (decimal text)", record.uncertainty.coverage_factor], ["Valid from (UTC)", record.valid_from], ["Valid until (UTC)", record.valid_until], ["Supersedes record", record.supersedes_id ?? "None; initial record"], ["Method", record.method], ["Reference ID", record.reference_id], ["Operator principal", record.operator_id], ["Signing key ID", record.key_id], ["Source document SHA-256", record.source_documents.join("\n")]]} />
    <p className="platform-note">Immutable signed digital record. Validity and supersession come from the API; they do not establish a calibrated receive chain, physical units accuracy or underwater SPL.</p>
  </div>;
}

export function DigitalCalibrations({ version }: { version: number }) {
  const [offset, setOffset] = useState(0);
  const [predecessorId, setPredecessorId] = useState<string | null>(null);
  const records = useResource<ApiPage<CalibrationRead>>(`${PLATFORM_API}/calibrations?limit=25&offset=${offset}`, version);
  const predecessor = useResource<CalibrationRead>(predecessorId ? `${PLATFORM_API}/calibrations/${encodeURIComponent(predecessorId)}` : null, version);
  return <section className="platform-panel" aria-labelledby="calibrations-title"><header className="platform-heading"><div><h2 id="calibrations-title">Digital calibration records</h2><p>Signed declarations and immutable supersession links. Every record in this tranche is digital-only, never physical calibration.</p></div></header><div className="inspection-block">
    <RequestError message={records.error} retry={records.reload} />{records.loading ? <p role="status">Refreshing digital calibration records…</p> : null}
    {records.data?.items.length === 0 ? <p className="list-empty">No digital calibration records in this scope. Evidence remains uncalibrated; none is inferred.</p> : null}
    {records.data?.items.map((item) => <details className="data-table-disclosure" key={item.record.record_id}><summary>{item.record.record_id} · {item.validity} · {item.record.instrument_id} · DIGITAL ONLY</summary><CalibrationEntry item={item} />{item.record.supersedes_id ? <div className="inspection-block"><button type="button" className="button secondary" onClick={() => setPredecessorId(item.record.supersedes_id)}>Read predecessor {item.record.supersedes_id}</button></div> : null}</details>)}
    <PageControls page={records.data} onPage={setOffset} loading={records.loading} />
    {predecessorId ? <section className="digital-predecessor" aria-label="Immutable calibration predecessor"><div className="block-heading"><h3>Predecessor returned by the API</h3><button type="button" className="text-button" onClick={() => setPredecessorId(null)}>Close predecessor</button></div><RequestError message={predecessor.error} retry={predecessor.reload} />{predecessor.loading ? <p role="status">Loading immutable predecessor…</p> : null}{predecessor.data ? <CalibrationEntry item={predecessor.data} /> : null}</section> : null}
  </div></section>;
}
