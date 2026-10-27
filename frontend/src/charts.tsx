import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useI18n } from "./Language";
import { axis, formats, scale } from "./metrics.ts";
import type { Formats } from "./metrics.ts";

/** Statistics formats in the current visual language. */
export function useFormats(): Formats {
  const { language, t, n } = useI18n();
  return useMemo(() => formats(language, t, n), [language, t, n]);
}

// In-house SVG charts (H6.2 E6, D076): one series in the accent or, for OK/KO, the status pair validated for
// color blindness. Null is never drawn as zero: it has its own "no data" mark. Every chart has its table.

export type Datum = { key: string; label: string; value: number | null; tip: string[] };
export type Stacked = { key: string; label: string; ok: number; ko: number; tip: string[] };

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    setWidth(element.clientWidth);
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

type Tip = { x: number; y: number; lines: string[] } | null;

/** Readout of the mark under the pointer or with focus: the value first, the label after. */
function Tooltip({ tip, width }: { tip: Tip; width: number }) {
  if (!tip) return null;
  const left = Math.min(Math.max(tip.x, 8), Math.max(8, width - 220));
  return <div className="chart-tip" style={{ left, top: tip.y }} role="status">
    {tip.lines.map((line, index) => index === 0 ? <strong key={index}>{line}</strong> : <span key={index}>{line}</span>)}
  </div>;
}

function Frame({ label, children, tip, width, frameRef }: { label: string; children: ReactNode; tip: Tip; width: number; frameRef: React.RefObject<HTMLDivElement | null> }) {
  return <div className="chart" ref={frameRef} role="group" aria-label={label}>
    {children}
    <Tooltip tip={tip} width={width} />
  </div>;
}

/** Horizontal bars of one series (magnitude by category), with the value at the tip. */
export function BarChart({ data, label, unit = "" }: { data: Datum[]; label: string; unit?: string }) {
  const { compact } = useFormats();
  const { t } = useI18n();
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const { top: max, ticks } = axis(Math.max(0, ...data.map(d => d.value ?? 0)));
  const labelWidth = Math.min(180, Math.max(96, Math.round(width * 0.32)));
  const valueRoom = 72;
  const plot = Math.max(40, width - labelWidth - valueRoom);
  const row = 32;
  const height = data.length * row + 24;
  return <Frame label={label} tip={tip} width={width} frameRef={ref}>
    {width > 0 && <svg width={width} height={height} aria-hidden="true" className="chart-svg">
      {ticks.map(value => {
        const x = labelWidth + (scale(value, max, plot) ?? 0);
        return <g key={value}>
          <line x1={x} x2={x} y1={0} y2={height - 20} className="chart-grid" />
          <text x={x} y={height - 4} textAnchor="middle" className="chart-tick">{compact(value)}</text>
        </g>;
      })}
      {data.map((d, index) => {
        const y = index * row;
        const length = scale(d.value, max, plot);
        const show = (event: { currentTarget: SVGGElement }) => {
          const box = event.currentTarget.getBoundingClientRect();
          const frame = ref.current!.getBoundingClientRect();
          setTip({ x: box.left - frame.left + labelWidth, y: box.bottom - frame.top + 4, lines: d.tip });
        };
        return <g key={d.key} className="chart-hit" onPointerEnter={show} onPointerLeave={() => setTip(null)}>
          <rect x={0} y={y} width={width} height={row} className="chart-hit-area" />
          <text x={labelWidth - 10} y={y + row / 2 + 4} textAnchor="end" className="chart-label">{clip(d.label, labelWidth)}</text>
          {length == null
            ? <><circle cx={labelWidth + 5} cy={y + row / 2} r={4} className="chart-absent" />
              <text x={labelWidth + 16} y={y + row / 2 + 4} className="chart-value muted-text">{t("metrics.no_data")}</text></>
            : <><path d={bar(labelWidth, y + (row - 16) / 2, Math.max(length, 1), 16)} className="chart-bar" />
              <text x={labelWidth + Math.max(length, 1) + 6} y={y + row / 2 + 4} className="chart-value">{compact(d.value)}{unit}</text></>}
        </g>;
      })}
      <line x1={labelWidth} x2={labelWidth} y1={0} y2={height - 20} className="chart-axis" />
    </svg>}
  </Frame>;
}

/** Columns of one series in chronological order; days without data carry their mark, not a zero column. */
export function ColumnChart({ data, label }: { data: Datum[]; label: string }) {
  const { compact } = useFormats();
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const { top: max, ticks } = axis(Math.max(0, ...data.map(d => d.value ?? 0)));
  const left = 52, bottom = 24, height = 200;
  const plotHeight = height - bottom - 8;
  const plot = Math.max(40, width - left - 8);
  const band = data.length ? plot / data.length : plot;
  const column = Math.min(24, Math.max(3, band - 2));
  const every = Math.max(1, Math.ceil(80 / band));
  return <Frame label={label} tip={tip} width={width} frameRef={ref}>
    {width > 0 && <svg width={width} height={height} aria-hidden="true" className="chart-svg">
      {ticks.map(value => {
        const y = 8 + plotHeight - (scale(value, max, plotHeight) ?? 0);
        return <g key={value}>
          <line x1={left} x2={width - 8} y1={y} y2={y} className="chart-grid" />
          <text x={left - 8} y={y + 4} textAnchor="end" className="chart-tick">{compact(value)}</text>
        </g>;
      })}
      {data.map((d, index) => {
        const x = left + index * band + (band - column) / 2;
        const length = scale(d.value, max, plotHeight);
        const base = 8 + plotHeight;
        const show = () => setTip({ x: x - 8, y: 8, lines: d.tip });
        return <g key={d.key} className="chart-hit" onPointerEnter={show} onPointerLeave={() => setTip(null)}>
          <rect x={left + index * band} y={0} width={band} height={height - bottom} className="chart-hit-area" />
          {length == null ? <circle cx={x + column / 2} cy={base - 6} r={4} className="chart-absent" />
            : <path d={column_(x, base, column, Math.max(length, 1))} className="chart-bar" />}
          {(index % every === 0 || index === data.length - 1) && (index === data.length - 1 || data.length - 1 - index >= every) &&
            <text x={x + column / 2} y={height - 6} textAnchor="middle" className="chart-tick">{d.label}</text>}
        </g>;
      })}
      <line x1={left} x2={width - 8} y1={8 + plotHeight} y2={8 + plotHeight} className="chart-axis" />
    </svg>}
  </Frame>;
}

/** OK/KO stacked by ordered category (phases): OK at the base, KO on top, separated by 2 px of surface. */
export function StackedColumns({ data, label }: { data: Stacked[]; label: string }) {
  const { compact } = useFormats();
  const { t } = useI18n();
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const { top: max, ticks } = axis(Math.max(0, ...data.map(d => d.ok + d.ko)), 4, true);
  const left = 40, bottom = 24, height = 200;
  const plotHeight = height - bottom - 8;
  const plot = Math.max(40, width - left - 8);
  const band = data.length ? plot / data.length : plot;
  const column = Math.min(24, Math.max(3, band - 2));
  const every = Math.max(1, Math.ceil(56 / band));
  const base = 8 + plotHeight;
  return <Frame label={label} tip={tip} width={width} frameRef={ref}>
    <ul className="chart-legend" aria-hidden="true">
      <li><span className="chart-key chart-key-ok" />{t("stats.legend.ok")}</li>
      <li><span className="chart-key chart-key-ko" />{t("stats.legend.ko")}</li>
    </ul>
    {width > 0 && <svg width={width} height={height} aria-hidden="true" className="chart-svg">
      {ticks.map(value => {
        const y = base - (scale(value, max, plotHeight) ?? 0);
        return <g key={value}>
          <line x1={left} x2={width - 8} y1={y} y2={y} className="chart-grid" />
          <text x={left - 8} y={y + 4} textAnchor="end" className="chart-tick">{compact(value)}</text>
        </g>;
      })}
      {data.map((d, index) => {
        const x = left + index * band + (band - column) / 2;
        const ok = scale(d.ok, max, plotHeight) ?? 0;
        const ko = scale(d.ko, max, plotHeight) ?? 0;
        const gap = d.ok && d.ko ? 2 : 0;
        return <g key={d.key} className="chart-hit" onPointerEnter={() => setTip({ x: x - 8, y: 36, lines: d.tip })} onPointerLeave={() => setTip(null)}>
          <rect x={left + index * band} y={0} width={band} height={height - bottom} className="chart-hit-area" />
          {d.ok > 0 && <path d={d.ko ? rect(x, base - ok, column, ok) : column_(x, base, column, ok)} className="chart-ok" />}
          {d.ko > 0 && <path d={column_(x, base - ok - gap, column, Math.max(ko - gap, 1))} className="chart-ko" />}
          {(index % every === 0 || index === data.length - 1) &&
            <text x={x + column / 2} y={height - 6} textAnchor="middle" className="chart-tick">{d.label}</text>}
        </g>;
      })}
      <line x1={left} x2={width - 8} y1={base} y2={base} className="chart-axis" />
    </svg>}
  </Frame>;
}

// Bar with the data end rounded (4 px) and a straight base.
function bar(x: number, y: number, length: number, thickness: number) {
  const r = Math.min(4, length, thickness / 2);
  return `M${x},${y}H${x + length - r}Q${x + length},${y} ${x + length},${y + r}V${y + thickness - r}Q${x + length},${y + thickness} ${x + length - r},${y + thickness}H${x}Z`;
}

function column_(x: number, base: number, width: number, length: number) {
  const r = Math.min(4, length, width / 2);
  const top = base - length;
  return `M${x},${base}V${top + r}Q${x},${top} ${x + r},${top}H${x + width - r}Q${x + width},${top} ${x + width},${top + r}V${base}Z`;
}

function rect(x: number, y: number, width: number, height: number) {
  return `M${x},${y}H${x + width}V${y + height}H${x}Z`;
}

function clip(text: string, room: number) {
  const chars = Math.max(6, Math.floor((room - 14) / 7));
  return text.length > chars ? `${text.slice(0, chars - 1)}…` : text;
}
