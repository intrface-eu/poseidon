"use client";

import { KeyboardEvent, PointerEvent, useId, useMemo, useState } from "react";
import type { AcousticEvent, Waveform } from "@/lib/api-types";
import { formatAmplitude, formatSeconds } from "@/lib/format";
import { bucketX, envelopePath, intervalRect } from "@/lib/waveform";

const VIEW_WIDTH = 1000;
const VIEW_HEIGHT = 286;
const PLOT = { left: 62, top: 22, width: 914, height: 218 };

export function WaveformChart({ waveform, event, interval }: { waveform: Waveform; event?: AcousticEvent; interval?: { start_s: number; end_s: number; label: string } }) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const patternId = useId().replace(/:/g, "");
  const path = useMemo(
    () => envelopePath(waveform.buckets, waveform.duration_s, PLOT),
    [waveform],
  );
  const selectedInterval = event ? { start_s: event.start_time_s, end_s: event.end_time_s, label: "Candidate interval" } : interval;
  const highlight = selectedInterval ? intervalRect(selectedInterval.start_s, selectedInterval.end_s, waveform.duration_s, PLOT) : null;
  const active = activeIndex === null ? null : waveform.buckets[activeIndex] ?? null;
  const crosshairX = active ? bucketX(active, waveform.duration_s, PLOT) : null;

  function indexFromPointer(pointerEvent: PointerEvent<SVGSVGElement>): number {
    const bounds = pointerEvent.currentTarget.getBoundingClientRect();
    const viewX = ((pointerEvent.clientX - bounds.left) / bounds.width) * VIEW_WIDTH;
    const ratio = Math.max(0, Math.min(1, (viewX - PLOT.left) / PLOT.width));
    return Math.min(waveform.buckets.length - 1, Math.max(0, Math.round(ratio * (waveform.buckets.length - 1))));
  }

  function handleKeys(keyEvent: KeyboardEvent<SVGSVGElement>) {
    if (waveform.buckets.length === 0) return;
    if (keyEvent.key === "ArrowRight" || keyEvent.key === "ArrowLeft") {
      keyEvent.preventDefault();
      const direction = keyEvent.key === "ArrowRight" ? 1 : -1;
      setActiveIndex((index) => Math.max(0, Math.min(waveform.buckets.length - 1, (index ?? 0) + direction)));
    }
    if (keyEvent.key === "Home") {
      keyEvent.preventDefault();
      setActiveIndex(0);
    }
    if (keyEvent.key === "End") {
      keyEvent.preventDefault();
      setActiveIndex(waveform.buckets.length - 1);
    }
  }

  const tooltipLeft = crosshairX === null ? 0 : (crosshairX / VIEW_WIDTH) * 100;

  return (
    <figure className="waveform-figure" aria-labelledby={`waveform-title-${patternId}`}>
      <figcaption>
        <div>
          <h3 id={`waveform-title-${patternId}`}>All-channel peak envelope</h3>
          <p>Source-derived min/max buckets · normalized PCM16 full-scale · not SPL</p>
        </div>
        <span className="tag calibration">{waveform.calibration_status}</span>
      </figcaption>
      <p className="chart-scroll-cue">Scroll horizontally to inspect the full timeline. The data table follows the chart.</p>
      <div className="chart-wrap">
        <div className="chart-canvas">
        <svg
          className="waveform-chart"
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          role="img"
          aria-label="Normalized waveform envelope from minus one to plus one. Use left and right arrow keys to inspect buckets."
          tabIndex={0}
          onPointerMove={(pointerEvent) => waveform.buckets.length > 0 && setActiveIndex(indexFromPointer(pointerEvent))}
          onPointerLeave={() => setActiveIndex(null)}
          onFocus={() => waveform.buckets.length > 0 && setActiveIndex((index) => index ?? 0)}
          onBlur={() => setActiveIndex(null)}
          onKeyDown={handleKeys}
        >
          <defs>
            <pattern id={patternId} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="8" className="event-hatch" />
            </pattern>
          </defs>
          {[1, 0, -1].map((value) => {
            const y = PLOT.top + ((1 - value) / 2) * PLOT.height;
            return (
              <g key={value}>
                <line className={`gridline ${value === 0 ? "baseline" : ""}`} x1={PLOT.left} x2={PLOT.left + PLOT.width} y1={y} y2={y} />
                <text className="axis-label y-label" x={PLOT.left - 12} y={y + 4} textAnchor="end">{value > 0 ? "+1" : value}</text>
              </g>
            );
          })}
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
            const x = PLOT.left + ratio * PLOT.width;
            return (
              <g key={ratio}>
                <line className="time-guide" x1={x} x2={x} y1={PLOT.top} y2={PLOT.top + PLOT.height} />
                <text className="axis-label" x={x} y={PLOT.top + PLOT.height + 25} textAnchor={ratio === 0 ? "start" : ratio === 1 ? "end" : "middle"}>
                  {formatSeconds(waveform.duration_s * ratio, waveform.duration_s < 10 ? 3 : 1)}
                </text>
              </g>
            );
          })}
          {highlight ? <>
            <rect className="event-window" x={highlight.x} y={PLOT.top} width={highlight.width} height={PLOT.height} fill={`url(#${patternId})`} />
            <line className="event-edge" x1={highlight.x} x2={highlight.x} y1={PLOT.top} y2={PLOT.top + PLOT.height} />
            <line className="event-edge" x1={highlight.x + highlight.width} x2={highlight.x + highlight.width} y1={PLOT.top} y2={PLOT.top + PLOT.height} />
          </> : null}
          {path ? <path className="envelope-mark" d={path} /> : null}
          {highlight ? <text className="event-label" x={Math.min(highlight.x + 6, PLOT.left + PLOT.width - 150)} y={PLOT.top + 15}>{selectedInterval?.label}</text> : null}
          {crosshairX !== null ? (
            <line className="crosshair" x1={crosshairX} x2={crosshairX} y1={PLOT.top} y2={PLOT.top + PLOT.height} />
          ) : null}
          <text className="axis-title" x={PLOT.left} y={VIEW_HEIGHT - 4}>Nominal time from segment start</text>
        </svg>
        {active && crosshairX !== null ? (
          <div
            className={`chart-tooltip ${tooltipLeft > 72 ? "align-right" : ""}`}
            style={{ left: `${tooltipLeft}%` }}
            role="status"
            aria-live="polite"
          >
            <strong>{formatSeconds(active.start_s)}–{formatSeconds(active.end_s)}</strong>
            <span><i className="line-key" /> max {formatAmplitude(active.max)}</span>
            <span><i className="line-key lower" /> min {formatAmplitude(active.min)}</span>
          </div>
        ) : null}
        </div>
      </div>
      <details className="data-table-disclosure">
        <summary>Accessible waveform data table ({waveform.buckets.length} buckets)</summary>
        <div className="table-scroll">
          <table>
            <caption>All waveform min/max buckets returned by the local API.</caption>
            <thead>
              <tr><th scope="col">Bucket</th><th scope="col">Start (s)</th><th scope="col">End (s)</th><th scope="col">Minimum</th><th scope="col">Maximum</th></tr>
            </thead>
            <tbody>
              {waveform.buckets.map((bucket, index) => (
                <tr key={`${bucket.start_s}-${bucket.end_s}-${index}`}>
                  <th scope="row">{index + 1}</th>
                  <td>{bucket.start_s.toFixed(6)}</td>
                  <td>{bucket.end_s.toFixed(6)}</td>
                  <td>{bucket.min.toFixed(6)}</td>
                  <td>{bucket.max.toFixed(6)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <div className="chart-notes">
        <span><i className="swatch envelope" /> Combined extrema across {waveform.channel_count} channel{waveform.channel_count === 1 ? "" : "s"}</span>
        {selectedInterval ? <span><i className="swatch interval" /> {event ? "Selected candidate interval" : selectedInterval.label}</span> : null}
      </div>
    </figure>
  );
}
