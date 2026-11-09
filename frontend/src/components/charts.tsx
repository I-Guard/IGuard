import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RangeSeries } from "../types/api";
import { EmptyState } from "./feedback";

const GRID = "#27324a";
const AXIS = "#66738f";
export const PALETTE = ["#4f8cff", "#2fbf71", "#f0a63a", "#b07cff", "#ef5350", "#5ab0ff"];

const tooltipStyle = { background: "#111827", border: "1px solid #27324a", borderRadius: 6, fontSize: 12 };

export function TimeSeriesChart({ data, unit = "", height = 220, max }: { data: RangeSeries | undefined; unit?: string; height?: number; max?: number }) {
  const series = data?.series.filter((s) => s.points.length) ?? [];
  if (!series.length) return <EmptyState title="No data" hint="Prometheus returned no samples for this range. Missing data is not shown as zero." />;
  // merge series on timestamp; gaps stay undefined (rendered as gaps, not zeros)
  const rows = new Map<number, Record<string, number>>();
  series.forEach((s, i) => s.points.forEach((p) => { const r = rows.get(p.t) ?? { t: p.t }; r[`s${i}`] = p.v; rows.set(p.t, r); }));
  const merged = [...rows.values()].sort((a, b) => a.t - b.t);
  return (
    <div style={{ height }} data-testid="timeseries-chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={merged} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} stroke={AXIS} fontSize={11} tickFormatter={(t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} />
          <YAxis stroke={AXIS} fontSize={11} width={48} domain={[0, max ?? "auto"]} tickFormatter={(v: number) => `${Math.round(v * 10) / 10}${unit}`} />
          <Tooltip contentStyle={tooltipStyle} labelFormatter={(t) => new Date(Number(t) * 1000).toLocaleString()} formatter={(v) => `${Number(v).toFixed(2)}${unit}`} />
          {series.map((_, i) => <Area key={i} type="monotone" dataKey={`s${i}`} stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.12} strokeWidth={1.6} dot={false} connectNulls={false} isAnimationActive={false} />)}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Donut({ data, height = 200 }: { data: { name: string; value: number; color: string }[]; height?: number }) {
  const filtered = data.filter((d) => d.value > 0);
  if (!filtered.length) return <EmptyState title="No data" />;
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={filtered} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="85%" stroke="none" isAnimationActive={false}>
            {filtered.map((d) => <Cell key={d.name} fill={d.color} />)}
          </Pie>
          <Tooltip contentStyle={tooltipStyle} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SimpleBars({ data, height = 200, color = PALETTE[0] }: { data: { name: string; value: number }[]; height?: number; color?: string }) {
  if (!data.length) return <EmptyState title="No data" />;
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" stroke={AXIS} fontSize={11} />
          <YAxis stroke={AXIS} fontSize={11} allowDecimals={false} width={32} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "#1b2540" }} />
          <Bar dataKey="value" fill={color} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Horizontal usage meter. `value === null` means "no data" and is rendered as such - never as 0%. */
export function Meter({ label, value, warn = 80, crit = 90 }: { label: string; value: number | null; warn?: number; crit?: number }) {
  const tone = value === null ? "bg-ink-faint" : value >= crit ? "bg-crit" : value >= warn ? "bg-warn" : "bg-ok";
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs"><span className="text-ink-dim">{label}</span><span className="tabular-nums text-ink">{value === null ? "no data" : `${value.toFixed(1)}%`}</span></div>
      <div className="h-2 overflow-hidden rounded bg-bg" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value ?? undefined} aria-valuetext={value === null ? "no data" : `${value.toFixed(1)} percent`}>
        {value !== null && <div className={`h-full ${tone}`} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />}
      </div>
    </div>
  );
}
