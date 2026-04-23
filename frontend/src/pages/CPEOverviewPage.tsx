import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { cpeOverviewApi } from "@/api/endpoints";
import type { PatternScanResult } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { usePlotlyLayoutMerge } from "@/lib/plotlyTheme";
import Plot from "react-plotly.js";
import CircularProgress from "@mui/material/CircularProgress";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import DevicesIcon from "@mui/icons-material/Devices";
import MemoryIcon from "@mui/icons-material/Memory";
import StorageIcon from "@mui/icons-material/Storage";
import SpeedIcon from "@mui/icons-material/Speed";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import DescriptionIcon from "@mui/icons-material/Description";
import RouterIcon from "@mui/icons-material/Router";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import WarningIcon from "@mui/icons-material/Warning";
import ErrorIcon from "@mui/icons-material/Error";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import SearchIcon from "@mui/icons-material/Search";
import RefreshIcon from "@mui/icons-material/Refresh";
import TroubleshootIcon from "@mui/icons-material/Troubleshoot";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { CrossCPEGraphs } from "@/components/CrossCPEGraphs";

/* ================================================================ Types */
interface RebootEvent {
  timestamp: string;
  reason: string;
  reboot_type?: "soft" | "hard";
  is_short_reboot?: boolean;
}

interface RebootSummary {
  total: number;
  short_reboots?: number;
  normal_reboots?: number;
  reasons: Record<string, number>;
  types?: { soft: number; hard: number };
  events?: RebootEvent[];
}

export interface CPESummary {
  serial: string;
  mac: string;
  model: string;
  date_from?: string | null;
  date_to?: string | null;
  device_info: Record<string, string>;
  key_metrics: Record<string, unknown>;
  summary: { total_reports?: number; parsed_reports?: number; time_range?: Record<string, string> };
  reboot_summary: RebootSummary;
  pattern_summary: Record<string, { label: string; indexed: boolean; total_loglines: number; unique_patterns: number }>;
  log_stats: { file_count: number; total_size_mb: number };
  status: "parsed" | "not_parsed" | "failed";
  reboot_count: number;
  log_size_mb: number;
}

interface OverviewResponse {
  cpes: CPESummary[];
  pagination?: {
    page: number;
    per_page: number;
    total_items: number;
    total_pages: number;
    has_next: boolean;
    has_prev: boolean;
  };
}

/* ================================================================ Helpers */

/** CPE label for charts/tables -- show full serial */
function cpeLabel(c: CPESummary): string {
  return c.serial || "N/A";
}

/**
 * Generate N visually distinct colors using the golden-angle offset on
 * the HSL hue wheel.  This guarantees good separation even for large N.
 * Saturation and lightness are varied slightly so consecutive colors
 * don't look too similar even when hues happen to be close.
 */
function generateCpeColors(n: number): string[] {
  const colors: string[] = [];
  const goldenAngle = 137.508; // degrees – maximises hue separation
  for (let i = 0; i < n; i++) {
    const hue = (i * goldenAngle) % 360;
    const sat = 65 + (i % 3) * 10;        // 65 / 75 / 85 %
    const light = 50 + (i % 2) * 8;       // 50 / 58 %
    colors.push(`hsl(${hue.toFixed(0)}, ${sat}%, ${light}%)`);
  }
  return colors;
}

/** Check if a set of values are all the same */
function allSame(values: string[]): boolean {
  if (values.length <= 1) return true;
  return values.every((v) => v === values[0]);
}

/** Format bytes to readable */
function fmtSize(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb.toFixed(1)} MB`;
}

/** Format uptime seconds to readable */
function fmtUptime(sec: unknown): string {
  const s = Number(sec);
  if (isNaN(s) || s === 0) return "N/A";
  if (s >= 86400) return `${(s / 86400).toFixed(1)}d`;
  if (s >= 3600) return `${(s / 3600).toFixed(1)}h`;
  if (s >= 60) return `${(s / 60).toFixed(0)}m`;
  return `${s.toFixed(0)}s`;
}

/* ================================================================ Components */

import { useState, useEffect } from "react";
import FilterListIcon from "@mui/icons-material/FilterList";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";

/** Reusable collapsible card wrapper */
function CollapsibleCard({
  icon,
  title,
  defaultOpen = true,
  headerRight,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  defaultOpen?: boolean;
  headerRight?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-4 py-3 border-b border-border bg-muted/30 flex items-center gap-2 text-left hover:bg-muted/50 transition-colors cursor-pointer"
      >
        {icon}
        <h3 className="text-sm font-semibold flex-1">{title}</h3>
        {headerRight && (
          <span onClick={(e) => e.stopPropagation()} className="flex items-center">
            {headerRight}
          </span>
        )}
        {open ? (
          <ExpandLessIcon style={{ fontSize: 20 }} className="text-muted-foreground" />
        ) : (
          <ExpandMoreIcon style={{ fontSize: 20 }} className="text-muted-foreground" />
        )}
      </button>
      {open && children}
    </div>
  );
}

/** Section 1: Device Info Comparison Table */
function DeviceInfoTable({ cpes }: { cpes: CPESummary[] }) {
  const fields = [
    { key: "model", label: "Model" },
    { key: "manufacturer", label: "Manufacturer" },
    { key: "serial", label: "Serial" },
    { key: "mac", label: "MAC" },
    { key: "hw_version", label: "HW Version" },
    { key: "version", label: "SW Version" },
    { key: "sdk_version", label: "SDK" },
    { key: "wan_type", label: "WAN Type" },
    { key: "sw_upgrade", label: "SW Upgrade" },
  ];

  return (
    <CollapsibleCard
      icon={<DevicesIcon style={{ fontSize: 20 }} className="text-primary" />}
      title="Device Info Comparison"
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/20">
              <th className="text-left px-4 py-2 font-medium text-muted-foreground w-36">Attribute</th>
              {cpes.map((c) => (
                <th key={c.serial} className="text-left px-4 py-2 font-medium min-w-[160px]">
                  {cpeLabel(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {fields.map((f) => {
              const values = cpes.map((c) => c.device_info[f.key] || "N/A");
              const same = allSame(values);
              return (
                <tr key={f.key} className="border-b border-border/50 hover:bg-muted/10">
                  <td className="px-4 py-2 text-muted-foreground font-medium">{f.label}</td>
                  {values.map((v, i) => (
                    <td
                      key={i}
                      className={`px-4 py-2 ${!same && v !== "N/A" ? "font-semibold text-amber-600 dark:text-amber-400" : ""}`}
                    >
                      {v}
                    </td>
                  ))}
                </tr>
              );
            })}
            {/* Date range row */}
            <tr className="border-b border-border/50 hover:bg-muted/10">
              <td className="px-4 py-2 text-muted-foreground font-medium">Log Date Range</td>
              {cpes.map((c) => (
                <td key={c.serial} className="px-4 py-2">
                  {c.date_from && c.date_to ? `${c.date_from} to ${c.date_to}` : "N/A"}
                </td>
              ))}
            </tr>
            {/* Log stats rows */}
            <tr className="border-b border-border/50 hover:bg-muted/10">
              <td className="px-4 py-2 text-muted-foreground font-medium">Log Files</td>
              {cpes.map((c) => (
                <td key={c.serial} className="px-4 py-2">{c.log_stats.file_count}</td>
              ))}
            </tr>
            <tr className="hover:bg-muted/10">
              <td className="px-4 py-2 text-muted-foreground font-medium">Total Size</td>
              {cpes.map((c) => (
                <td key={c.serial} className="px-4 py-2">{fmtSize(c.log_stats.total_size_mb)}</td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </CollapsibleCard>
  );
}

/** Section 2: Key Metrics Comparison */
function MetricsComparison({ cpes }: { cpes: CPESummary[] }) {
  const metricDefs: Array<{
    key: string;
    label: string;
    icon: typeof MemoryIcon;
    format: (km: Record<string, unknown>, cpe?: CPESummary) => string;
    higher_is_better?: boolean;
    getValue: (km: Record<string, unknown>, cpe?: CPESummary) => number | null;
  }> = [
    {
      key: "reports",
      label: "Telemetry Reports",
      icon: DescriptionIcon,
      format: (km) => `${km.reports_parsed ?? "N/A"} / ${km.reports_total ?? "N/A"}`,
      getValue: (km) => km.reports_parsed != null ? Number(km.reports_parsed) : null,
      higher_is_better: true,
    },
    {
      key: "memory",
      label: "Memory Free",
      icon: StorageIcon,
      format: (km) => {
        if (km.memory_free_last == null) return "N/A";
        const unit = String(km.memory_unit || "KB");
        return `${km.memory_free_first} → ${km.memory_free_last} ${unit}${km.memory_total != null ? ` (of ${km.memory_total})` : ""}`;
      },
      getValue: (km) => km.memory_free_last != null ? Number(km.memory_free_last) : null,
      higher_is_better: true,
    },
    {
      key: "cpu",
      label: "CPU Usage",
      icon: MemoryIcon,
      format: (km) => {
        if (km.cpu_avg == null) return "N/A";
        return `avg ${km.cpu_avg}${km.cpu_unit || "%"}  peak ${km.cpu_peak}${km.cpu_unit || "%"}`;
      },
      getValue: (km) => km.cpu_avg != null ? Number(km.cpu_avg) : null,
      higher_is_better: false,
    },
    {
      key: "uptime",
      label: "Uptime",
      icon: RouterIcon,
      format: (km) => {
        if (km.uptime_last == null) return "N/A";
        const resets = Number(km.uptime_resets || 0);
        return `${fmtUptime(km.uptime_first)} → ${fmtUptime(km.uptime_last)}${resets > 0 ? ` (${resets} resets)` : ""}`;
      },
      getValue: (km) => km.uptime_last != null ? Number(km.uptime_last) : null,
      higher_is_better: true,
    },
    {
      key: "dsl_down",
      label: "DSL Downstream",
      icon: SpeedIcon,
      format: (km) => {
        if (km.dsl_down_min == null) return "N/A";
        return `${km.dsl_down_min} – ${km.dsl_down_max} ${km.dsl_down_unit || "kbps"}`;
      },
      getValue: (km) => km.dsl_down_max != null ? Number(km.dsl_down_max) : null,
      higher_is_better: true,
    },
    {
      key: "dsl_up",
      label: "DSL Upstream",
      icon: SpeedIcon,
      format: (km) => {
        if (km.dsl_up_min == null) return "N/A";
        return `${km.dsl_up_min} – ${km.dsl_up_max} ${km.dsl_up_unit || "kbps"}`;
      },
      getValue: (km) => km.dsl_up_max != null ? Number(km.dsl_up_max) : null,
      higher_is_better: true,
    },
    {
      key: "connected",
      label: "Connected Devices",
      icon: DevicesIcon,
      format: (km) => {
        if (km.connected_devices_avg == null) return "N/A";
        return `avg ${km.connected_devices_avg}  peak ${km.connected_devices_peak}`;
      },
      getValue: (km) => km.connected_devices_avg != null ? Number(km.connected_devices_avg) : null,
    },
    {
      key: "reboots",
      label: "Total Reboots",
      icon: RestartAltIcon,
      format: (_km: Record<string, unknown>, cpe?: CPESummary) => String(cpe?.reboot_summary.total ?? 0),
      getValue: (_km: Record<string, unknown>, cpe?: CPESummary) => cpe?.reboot_summary.total ?? 0,
      higher_is_better: false,
    },
    {
      key: "selfheal",
      label: "SelfHeal signals",
      icon: TroubleshootIcon,
      format: (km) => {
        const sev = km.selfheal_signal_severity;
        const tags = km.selfheal_signal_tags;
        if (!sev && (!Array.isArray(tags) || tags.length === 0)) return "—";
        const tagStr = Array.isArray(tags)
          ? tags.map((t) => String(t).replace(/_/g, " ")).join(" · ")
          : "";
        return sev ? `${String(sev)} · ${tagStr}` : tagStr || "—";
      },
      getValue: (km) => {
        const n = Number(km.selfheal_signal_tag_count);
        return Number.isFinite(n) && n > 0 ? n : null;
      },
      higher_is_better: false,
    },
  ];

  const formatWithCpe = (def: typeof metricDefs[0], km: Record<string, unknown>, cpe: CPESummary) =>
    def.format(km, cpe);
  const getValueWithCpe = (def: typeof metricDefs[0], km: Record<string, unknown>, cpe: CPESummary) =>
    def.getValue(km, cpe);

  return (
    <CollapsibleCard
      icon={<CompareArrowsIcon style={{ fontSize: 20 }} className="text-primary" />}
      title="Key Metrics Comparison"
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/20">
              <th className="text-left px-4 py-2 font-medium text-muted-foreground w-44">Metric</th>
              {cpes.map((c) => (
                <th key={c.serial} className="text-left px-4 py-2 font-medium min-w-[180px]">
                  {cpeLabel(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metricDefs.map((def) => {
              const values = cpes.map((c) => getValueWithCpe(def, c.key_metrics, c));
              const numericValues = values.filter((v) => v != null) as number[];
              const bestVal = def.higher_is_better === true
                ? Math.max(...numericValues)
                : def.higher_is_better === false
                  ? Math.min(...numericValues)
                  : null;
              const worstVal = def.higher_is_better === true
                ? Math.min(...numericValues)
                : def.higher_is_better === false
                  ? Math.max(...numericValues)
                  : null;
              const Icon = def.icon;

              return (
                <tr key={def.key} className="border-b border-border/50 hover:bg-muted/10">
                  <td className="px-4 py-2 text-muted-foreground font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      <Icon style={{ fontSize: 16 }} />
                      {def.label}
                    </span>
                  </td>
                  {cpes.map((c, i) => {
                    const val = values[i];
                    const isBest = val != null && numericValues.length > 1 && val === bestVal;
                    const isWorst = val != null && numericValues.length > 1 && val === worstVal;

                    return (
                      <td
                        key={c.serial}
                        className={`px-4 py-2 ${
                          isBest
                            ? "text-emerald-600 dark:text-emerald-400 font-semibold"
                            : isWorst
                              ? "text-red-600 dark:text-red-400 font-semibold"
                              : ""
                        }`}
                      >
                        <span className="inline-flex items-center gap-1">
                          {isBest && <CheckCircleIcon style={{ fontSize: 14 }} />}
                          {isWorst && <ErrorIcon style={{ fontSize: 14 }} />}
                          {formatWithCpe(def, c.key_metrics, c)}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </CollapsibleCard>
  );
}

/** Section 3: Reboot Comparison */
function RebootComparison({ cpes }: { cpes: CPESummary[] }) {
  const mergePlot = usePlotlyLayoutMerge();
  const labels = cpes.map(cpeLabel);
  const totals = cpes.map((c) => c.reboot_summary.total);
  const colors = generateCpeColors(cpes.length);

  // Collect all unique reasons
  const allReasons = new Set<string>();
  cpes.forEach((c) => {
    Object.keys(c.reboot_summary.reasons || {}).forEach((r) => allReasons.add(r));
  });
  const reasons = Array.from(allReasons).sort();

  // Calculate soft/hard breakdown for stacked bar chart
  const softCounts = cpes.map((c) => c.reboot_summary.types?.soft || 0);
  const hardCounts = cpes.map((c) => c.reboot_summary.types?.hard || 0);
  const hasSoftRebootData = softCounts.some((c) => c > 0);

  return (
    <CollapsibleCard
      icon={<RestartAltIcon style={{ fontSize: 20 }} className="text-primary" />}
      title="Reboot Comparison"
    >
      <div className="p-4 space-y-4">
        {/* Reboot type legend (only show if soft reboot data exists) */}
        {hasSoftRebootData && (
          <div className="flex items-center gap-4 text-xs bg-muted/30 rounded-lg px-3 py-2">
            <span className="text-muted-foreground font-medium">Reboot Types:</span>
            <div className="flex items-center gap-1.5">
              <span className="px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 font-medium">SOFT</span>
              <span className="text-muted-foreground">Software-initiated reboot (graceful shutdown)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="px-2 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 font-medium">HARD</span>
              <span className="text-muted-foreground">Hardware/Power reboot (unexpected)</span>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Stacked bar chart: soft vs hard reboots */}
          <div>
            <Plot
              data={
                hasSoftRebootData
                  ? [
                      {
                        type: "bar",
                        name: "Soft Reboots",
                        x: labels,
                        y: softCounts,
                        marker: { color: "#3b82f6" },
                        text: softCounts.map((c) => (c > 0 ? String(c) : "")),
                        textposition: "inside" as const,
                      },
                      {
                        type: "bar",
                        name: "Hard Reboots",
                        x: labels,
                        y: hardCounts,
                        marker: { color: "#ef4444" },
                        text: hardCounts.map((c) => (c > 0 ? String(c) : "")),
                        textposition: "inside" as const,
                      },
                    ]
                  : [
                      {
                        type: "bar",
                        x: labels,
                        y: totals,
                        marker: { color: colors },
                        text: totals.map(String),
                        textposition: "auto" as const,
                      },
                    ]
              }
              layout={mergePlot({
                title: { text: hasSoftRebootData ? "Reboots by Type per CPE" : "Total Reboots per CPE" },
                height: 380,
                margin: { t: 40, b: 120, l: 50, r: 20 },
                xaxis: { tickangle: -45, automargin: true },
                yaxis: { title: { text: "Reboots" } },
                barmode: hasSoftRebootData ? ("stack" as const) : undefined,
                showlegend: hasSoftRebootData,
                legend: { orientation: "h" as const, y: -0.3 },
              })}
              config={{ displayModeBar: false }}
              style={{ width: "100%" }}
            />
          </div>

          {/* Reasons breakdown table with reboot type badges */}
          {reasons.length > 0 && (
            <div className="overflow-x-auto">
              <p className="text-xs font-medium text-muted-foreground mb-2">Reboot Reasons Breakdown</p>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/20">
                    <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Reason</th>
                    {cpes.map((c) => (
                      <th key={c.serial} className="text-center px-3 py-1.5 font-medium">{cpeLabel(c)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {reasons.map((reason) => (
                    <tr key={reason} className="border-b border-border/50">
                      <td className="px-3 py-1.5 text-muted-foreground truncate max-w-[200px]" title={reason}>
                        {reason}
                      </td>
                      {cpes.map((c) => {
                        const count = c.reboot_summary.reasons?.[reason] || 0;
                        
                        // Count soft/hard for this reason
                        const eventsForReason = (c.reboot_summary.events || []).filter(
                          (e) => e.reason === reason
                        );
                        const softForReason = eventsForReason.filter((e) => e.reboot_type === "soft").length;
                        const hardForReason = eventsForReason.filter((e) => e.reboot_type === "hard").length;
                        
                        return (
                          <td key={c.serial} className="px-3 py-1.5 text-center">
                            {count > 0 ? (
                              <div className="inline-flex flex-col items-center gap-0.5">
                                <span className="font-semibold">{count}</span>
                                {hasSoftRebootData && (softForReason > 0 || hardForReason > 0) && (
                                  <div className="flex gap-1 text-[10px]">
                                    {softForReason > 0 && (
                                      <span className="px-1 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300">
                                        {softForReason}S
                                      </span>
                                    )}
                                    {hardForReason > 0 && (
                                      <span className="px-1 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300">
                                        {hardForReason}H
                                      </span>
                                    )}
                                  </div>
                                )}
                              </div>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Reboot type summary table (only if soft reboot data exists) */}
        {hasSoftRebootData && (
          <div className="overflow-x-auto">
            <p className="text-xs font-medium text-muted-foreground mb-2">Reboot Type Summary</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/20">
                  <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Type</th>
                  {cpes.map((c) => (
                    <th key={c.serial} className="text-center px-3 py-1.5 font-medium">{cpeLabel(c)}</th>
                  ))}
                  <th className="text-center px-3 py-1.5 font-medium text-muted-foreground">Total</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-border/50">
                  <td className="px-3 py-1.5 flex items-center gap-1.5">
                    <span className="px-2 py-0.5 rounded text-xs bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 font-medium">SOFT</span>
                    <span className="text-muted-foreground text-xs">Software</span>
                  </td>
                  {cpes.map((c) => (
                    <td key={c.serial} className="px-3 py-1.5 text-center font-semibold text-blue-700 dark:text-blue-300">
                      {c.reboot_summary.types?.soft || 0}
                    </td>
                  ))}
                  <td className="px-3 py-1.5 text-center font-bold text-blue-700 dark:text-blue-300">
                    {softCounts.reduce((a, b) => a + b, 0)}
                  </td>
                </tr>
                <tr className="border-b border-border/50">
                  <td className="px-3 py-1.5 flex items-center gap-1.5">
                    <span className="px-2 py-0.5 rounded text-xs bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 font-medium">HARD</span>
                    <span className="text-muted-foreground text-xs">Hardware/Power</span>
                  </td>
                  {cpes.map((c) => (
                    <td key={c.serial} className="px-3 py-1.5 text-center font-semibold text-red-700 dark:text-red-300">
                      {c.reboot_summary.types?.hard || 0}
                    </td>
                  ))}
                  <td className="px-3 py-1.5 text-center font-bold text-red-700 dark:text-red-300">
                    {hardCounts.reduce((a, b) => a + b, 0)}
                  </td>
                </tr>
                <tr className="border-b border-border/50">
                  <td className="px-3 py-1.5 font-medium text-muted-foreground">Total</td>
                  {cpes.map((c) => (
                    <td key={c.serial} className="px-3 py-1.5 text-center font-bold">
                      {c.reboot_summary.total}
                    </td>
                  ))}
                  <td className="px-3 py-1.5 text-center font-bold">
                    {totals.reduce((a, b) => a + b, 0)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}

        {/* Short Reboot Summary Table (show if any CPE has short reboot data) */}
        {cpes.some((c) => c.reboot_summary.short_reboots !== undefined && (c.reboot_summary.short_reboots || 0) > 0) && (
          <div className="overflow-x-auto">
            <p className="text-xs font-medium text-muted-foreground mb-2">Short Reboot Summary</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/20">
                  <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Type</th>
                  {cpes.map((c) => (
                    <th key={c.serial} className="text-center px-3 py-1.5 font-medium">{cpeLabel(c)}</th>
                  ))}
                  <th className="text-center px-3 py-1.5 font-medium text-muted-foreground">Total</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-border/50">
                  <td className="px-3 py-1.5 flex items-center gap-1.5">
                    <span className="px-2 py-0.5 rounded text-xs bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 font-medium">SHORT</span>
                    <span className="text-muted-foreground text-xs">Brief power cycle</span>
                  </td>
                  {cpes.map((c) => (
                    <td key={c.serial} className="px-3 py-1.5 text-center font-semibold text-purple-700 dark:text-purple-300">
                      {c.reboot_summary.short_reboots || 0}
                    </td>
                  ))}
                  <td className="px-3 py-1.5 text-center font-bold text-purple-700 dark:text-purple-300">
                    {cpes.reduce((sum, c) => sum + (c.reboot_summary.short_reboots || 0), 0)}
                  </td>
                </tr>
                <tr className="border-b border-border/50">
                  <td className="px-3 py-1.5 flex items-center gap-1.5">
                    <span className="px-2 py-0.5 rounded text-xs bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 font-medium">NORMAL</span>
                    <span className="text-muted-foreground text-xs">Extended power loss</span>
                  </td>
                  {cpes.map((c) => (
                    <td key={c.serial} className="px-3 py-1.5 text-center font-semibold text-red-700 dark:text-red-300">
                      {c.reboot_summary.normal_reboots || 0}
                    </td>
                  ))}
                  <td className="px-3 py-1.5 text-center font-bold text-red-700 dark:text-red-300">
                    {cpes.reduce((sum, c) => sum + (c.reboot_summary.normal_reboots || 0), 0)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>
    </CollapsibleCard>
  );
}

/** Truncate a pattern name for chart X-axis labels */
function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + "\u2026" : s;
}

/** Section 4: Pattern Analyzer Comparison */
function PatternAnalyzerComparison({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const mergePlot = usePlotlyLayoutMerge();

  // Auto-load cached scan results on mount
  const {
    data: scanData,
    isLoading: loadingCache,
  } = useQuery<PatternScanResult>({
    queryKey: ["cpe-overview-pattern-scan", projectId],
    queryFn: async () => {
      const res = await cpeOverviewApi.getPatternScan(projectId);
      return res.data;
    },
    enabled: !!projectId,
  });

  // Mutation for running a new scan
  const scanMutation = useMutation({
    mutationFn: async () => {
      const res = await cpeOverviewApi.runPatternScan(projectId);
      return res.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["cpe-overview-pattern-scan", projectId], data);
    },
  });

  const isScanning = scanMutation.isPending;
  const hasCachedData = scanData?.cached === true && scanData.domains && Object.keys(scanData.domains).length > 0;
  const domainEntries = hasCachedData ? Object.entries(scanData!.domains!) : [];

  // ---- Render helpers ----

  const scanButton = (
    <button
      onClick={() => scanMutation.mutate()}
      disabled={isScanning}
      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-muted hover:bg-muted/80 text-xs font-medium disabled:opacity-50"
    >
      {isScanning ? (
        <>
          <CircularProgress size={14} />
          Scanning...
        </>
      ) : (
        <>
          <RefreshIcon style={{ fontSize: 16 }} />
          Re-scan
        </>
      )}
    </button>
  );

  const headerTimestamp = scanData?.scanned_at ? (
    <span className="text-xs text-muted-foreground ml-2">
      Last scanned: {new Date(scanData.scanned_at).toLocaleString()}
      {scanData.elapsed_ms != null && ` (${(scanData.elapsed_ms / 1000).toFixed(1)}s)`}
    </span>
  ) : null;

  // ---- Render: loading ----
  if (loadingCache) {
    return (
      <div className="bg-card border border-border rounded-xl p-6 flex items-center justify-center gap-2 text-muted-foreground">
        <CircularProgress size={20} />
        <span className="text-sm">Loading pattern scan data...</span>
      </div>
    );
  }

  // ---- Render: no cached data ----
  if (!hasCachedData) {
    return (
      <CollapsibleCard
        icon={<SearchIcon style={{ fontSize: 20 }} className="text-primary" />}
        title="Pattern Analyzer Comparison"
      >
        <div className="p-6 flex flex-col items-center gap-3 text-center">
          <p className="text-sm text-muted-foreground">
            Run your project&apos;s regex patterns against all CPEs to compare match counts.
          </p>
          {scanMutation.isError && (
            <p className="text-sm text-destructive">
              {(scanMutation.error as Error)?.message
                || (scanMutation.error as { response?: { data?: { error?: string } } })?.response?.data?.error
                || "Scan failed"}
            </p>
          )}
          <button
            onClick={() => scanMutation.mutate()}
            disabled={isScanning}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
          >
            {isScanning ? (
              <>
                <CircularProgress size={16} color="inherit" />
                Scanning...
              </>
            ) : (
              <>
                <PlayArrowIcon style={{ fontSize: 18 }} />
                Run Pattern Scan
              </>
            )}
          </button>
        </div>
      </CollapsibleCard>
    );
  }

  // Custom blue-teal colorscale: light background for 0, dark teal/blue for high values
  const heatmapColorscale: Array<[number, string]> = [
    [0,    "#f0f4f8"],
    [0.15, "#d0e2f2"],
    [0.3,  "#a3c4e0"],
    [0.5,  "#5b9bd5"],
    [0.7,  "#2e75b6"],
    [0.85, "#1b4f8a"],
    [1,    "#0d2e5c"],
  ];

  // ---- Render: cached data with heatmaps ----
  return (
    <CollapsibleCard
      icon={<SearchIcon style={{ fontSize: 20 }} className="text-primary" />}
      title="Pattern Analyzer Comparison"
      headerRight={
        <span className="flex items-center gap-2">
          {headerTimestamp}
          {scanButton}
        </span>
      }
    >
      {domainEntries.map(([domain, domData]) => {
        const cpeSerials = domData.cpes.map((c) => c.serial);
        const patternNames = domData.patterns;

        // Compute total matches per pattern (sum across CPEs) for sorting
        const patternTotals = patternNames.map((_, pIdx) =>
          domData.cpes.reduce((sum, cpe) => sum + (cpe.counts[pIdx] ?? 0), 0)
        );

        // Filter out zero-count patterns, then sort ascending
        const sortedIndices = patternTotals
          .map((total, idx) => ({ total, idx }))
          .filter((item) => item.total > 0)
          .sort((a, b) => a.total - b.total)
          .map((item) => item.idx);

        // Skip domain entirely if no patterns have matches
        if (sortedIndices.length === 0) return null;

        const sortedPatternNames = sortedIndices.map((i) => patternNames[i]);

        // Build heatmap z-matrix in sorted order
        const zValues = sortedIndices.map((pIdx) =>
          domData.cpes.map((cpe) => cpe.counts[pIdx] ?? 0)
        );

        // Find the max value across the whole domain for consistent scaling
        const maxVal = Math.max(1, ...zValues.flat());

        // Annotation text for heatmap cells -- dark text on light cells, white on dark
        const annotations: Array<{
          x: string; y: string; text: string; showarrow: boolean;
          font: { color: string; size: number };
        }> = [];
        sortedPatternNames.forEach((pat, rowIdx) => {
          cpeSerials.forEach((serial, cIdx) => {
            const val = zValues[rowIdx][cIdx];
            const ratio = val / maxVal;
            annotations.push({
              x: serial,
              y: truncate(pat, 45),
              text: val > 0 ? val.toLocaleString() : "-",
              showarrow: false,
              font: {
                color: ratio > 0.45 ? "#fff" : "#334155",
                size: 11,
              },
            });
          });
        });

        return (
          <div key={domain} className="border-b border-border/50 last:border-b-0">
            <div className="px-4 pt-3 pb-1">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{domain}</p>
            </div>

            <div className="px-4 pb-3">
              <Plot
                data={[
                  {
                    type: "heatmap",
                    z: zValues,
                    x: cpeSerials,
                    y: sortedPatternNames.map((p) => truncate(p, 45)),
                    colorscale: heatmapColorscale,
                    showscale: true,
                    zmin: 0,
                    zmax: maxVal,
                    hoverongaps: false,
                    hovertemplate:
                      "<b>%{y}</b><br>CPE: %{x}<br>Matches: %{z}<extra></extra>",
                  } as any,
                ]}
                layout={mergePlot({
                  height: Math.max(220, sortedPatternNames.length * 30 + 140),
                  margin: { t: 10, b: 20, l: 20, r: 80 },
                  xaxis: { side: "bottom" as const, tickangle: -45, automargin: true },
                  yaxis: { autorange: false as const, range: [-0.5, sortedPatternNames.length - 0.5], dtick: 1, automargin: true },
                  annotations,
                  font: { size: 11 },
                })}
                config={{ displayModeBar: false }}
                style={{ width: "100%" }}
              />
            </div>
          </div>
        );
      })}
    </CollapsibleCard>
  );
}

/* ================================================================ Main Page */

export default function CPEOverviewPage() {
  const { projectId } = useProject();
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(20);
  const [sortBy, setSortBy] = useState<"serial" | "model" | "date_from" | "reboot_count" | "log_size">("serial");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [modelFilter, setModelFilter] = useState("");
  const [serialFilter, setSerialFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<"parsed" | "not_parsed" | "failed" | "">("");
  const [showFilters, setShowFilters] = useState(false);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [modelFilter, serialFilter, statusFilter]);

  const { data, isLoading, error } = useQuery<OverviewResponse>({
    queryKey: ["cpe-overview", projectId, page, perPage, sortBy, order, modelFilter, serialFilter, statusFilter],
    queryFn: async () => {
      if (!projectId) throw new Error("No project selected");
      const res = await cpeOverviewApi.getSummary(projectId, {
        page,
        per_page: perPage,
        sort_by: sortBy,
        order,
        model: modelFilter || undefined,
        serial: serialFilter || undefined,
        status: statusFilter || undefined,
      });
      return res.data;
    },
    enabled: !!projectId,
  });

  if (!projectId) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Select a project from the Dashboard.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
        <CircularProgress size={36} />
        <p className="text-sm">Loading CPE overview data...</p>
        <p className="text-xs text-muted-foreground/60">This may take a few seconds for multi-CPE projects.</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-destructive">
        <ErrorIcon style={{ fontSize: 20 }} className="mr-2" />
        Error loading CPE overview: {String(error)}
      </div>
    );
  }

  const cpes = data?.cpes || [];
  const pagination = data?.pagination;

  const toggleSort = (field: typeof sortBy) => {
    if (sortBy === field) {
      setOrder(order === "asc" ? "desc" : "asc");
    } else {
      setSortBy(field);
      setOrder("asc");
    }
  };

  if (cpes.length === 0 && !isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
        <WarningIcon style={{ fontSize: 32 }} />
        <p>No CPE data available for this project.</p>
        <p className="text-xs">Upload log files first from the Log Viewer page.</p>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4 overflow-auto h-full">
      {/* Page header with filters */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <CompareArrowsIcon style={{ fontSize: 24, color: "#1a73e8" }} />
          <h2 className="text-lg font-bold">CPE Overview</h2>
          {pagination && (
            <span className="text-sm text-muted-foreground ml-2">
              {pagination.total_items} CPE{pagination.total_items !== 1 ? "s" : ""} total
            </span>
          )}
        </div>
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-colors ${
            showFilters ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/80"
          }`}
        >
          <FilterListIcon style={{ fontSize: 18 }} />
          Filters
        </button>
      </div>

      {/* Filters Panel */}
      {showFilters && (
        <div className="bg-card border border-border rounded-xl p-4 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div>
              <label className="block text-xs font-medium mb-1.5 text-muted-foreground">Serial</label>
              <input
                type="text"
                value={serialFilter}
                onChange={(e) => setSerialFilter(e.target.value)}
                placeholder="CP..."
                className="w-full px-3 py-1.5 text-sm border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1.5 text-muted-foreground">Model</label>
              <input
                type="text"
                value={modelFilter}
                onChange={(e) => setModelFilter(e.target.value)}
                placeholder="DT-HGW01A..."
                className="w-full px-3 py-1.5 text-sm border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1.5 text-muted-foreground">Status</label>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as any)}
                className="w-full px-3 py-1.5 text-sm border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
              >
                <option value="">All</option>
                <option value="parsed">Parsed</option>
                <option value="not_parsed">Not Parsed</option>
                <option value="failed">Failed</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium mb-1.5 text-muted-foreground">Per Page</label>
              <select
                value={perPage}
                onChange={(e) => {
                  setPerPage(Number(e.target.value));
                  setPage(1);
                }}
                className="w-full px-3 py-1.5 text-sm border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
              >
                <option value="10">10</option>
                <option value="20">20</option>
                <option value="50">50</option>
                <option value="100">100</option>
              </select>
            </div>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Sort by:</span>
            {[
              { key: "serial" as const, label: "Serial" },
              { key: "model" as const, label: "Model" },
              { key: "date_from" as const, label: "Date" },
              { key: "reboot_count" as const, label: "Reboots" },
              { key: "log_size" as const, label: "Size" },
            ].map((s) => (
              <button
                key={s.key}
                onClick={() => toggleSort(s.key)}
                className={`flex items-center gap-1 px-2 py-1 rounded ${
                  sortBy === s.key ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/80"
                }`}
              >
                {s.label}
                {sortBy === s.key && (
                  order === "asc" ? <ArrowUpwardIcon style={{ fontSize: 14 }} /> : <ArrowDownwardIcon style={{ fontSize: 14 }} />
                )}
              </button>
            ))}
          </div>
          {(serialFilter || modelFilter || statusFilter) && (
            <button
              onClick={() => {
                setSerialFilter("");
                setModelFilter("");
                setStatusFilter("");
              }}
              className="text-xs text-primary hover:underline"
            >
              Clear all filters
            </button>
          )}
        </div>
      )}

      {/* Pagination Controls - Top */}
      {pagination && pagination.total_pages > 1 && (
        <div className="flex items-center justify-between bg-card border border-border rounded-xl px-4 py-2">
          <div className="text-sm text-muted-foreground">
            Showing {((pagination.page - 1) * pagination.per_page) + 1} - {Math.min(pagination.page * pagination.per_page, pagination.total_items)} of {pagination.total_items}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={!pagination.has_prev}
              className="p-1 rounded hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronLeftIcon style={{ fontSize: 20 }} />
            </button>
            <span className="text-sm">
              Page {pagination.page} of {pagination.total_pages}
            </span>
            <button
              onClick={() => setPage(Math.min(pagination.total_pages, page + 1))}
              disabled={!pagination.has_next}
              className="p-1 rounded hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronRightIcon style={{ fontSize: 20 }} />
            </button>
          </div>
        </div>
      )}

      {/* Section 1: Device Info */}
      <DeviceInfoTable cpes={cpes} />

      {/* Section 2: Key Metrics */}
      <MetricsComparison cpes={cpes} />

      {/* Section 2b: Cross-CPE Health Graphs */}
      <CrossCPEGraphs cpes={cpes} />

      {/* Section 3: Reboot Comparison */}
      <RebootComparison cpes={cpes} />

      {/* Section 4: Pattern Analyzer Comparison */}
      <PatternAnalyzerComparison projectId={projectId} />

      {/* Pagination Controls - Bottom */}
      {pagination && pagination.total_pages > 1 && (
        <div className="flex items-center justify-between bg-card border border-border rounded-xl px-4 py-2">
          <div className="text-sm text-muted-foreground">
            Showing {((pagination.page - 1) * pagination.per_page) + 1} - {Math.min(pagination.page * pagination.per_page, pagination.total_items)} of {pagination.total_items}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={!pagination.has_prev}
              className="p-1 rounded hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronLeftIcon style={{ fontSize: 20 }} />
            </button>
            <span className="text-sm">
              Page {pagination.page} of {pagination.total_pages}
            </span>
            <button
              onClick={() => setPage(Math.min(pagination.total_pages, page + 1))}
              disabled={!pagination.has_next}
              className="p-1 rounded hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronRightIcon style={{ fontSize: 20 }} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
