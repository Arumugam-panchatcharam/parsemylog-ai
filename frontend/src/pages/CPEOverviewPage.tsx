import { useQuery } from "@tanstack/react-query";
import { cpeOverviewApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
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

/* ================================================================ Types */
interface CPESummary {
  serial: string;
  mac: string;
  date_from: string | null;
  date_to: string | null;
  device_info: Record<string, string>;
  key_metrics: Record<string, unknown>;
  summary: { total_reports?: number; parsed_reports?: number; time_range?: Record<string, string> };
  reboot_summary: { total: number; reasons: Record<string, number>; events?: Array<{ timestamp: string; reason: string }> };
  pattern_summary: Record<string, { label: string; indexed: boolean; total_loglines: number; unique_patterns: number }>;
  log_stats: { file_count: number; total_size_mb: number };
}

interface OverviewData {
  cpes: CPESummary[];
}

/* ================================================================ Helpers */

/** Short CPE label for charts/tables */
function cpeLabel(c: CPESummary): string {
  const s = c.serial || "N/A";
  return s.length > 14 ? s.slice(0, 6) + ".." + s.slice(-4) : s;
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
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-border bg-muted/30 flex items-center gap-2">
        <DevicesIcon style={{ fontSize: 20 }} className="text-primary" />
        <h3 className="text-sm font-semibold">Device Info Comparison</h3>
      </div>
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
    </div>
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
  ];

  const formatWithCpe = (def: typeof metricDefs[0], km: Record<string, unknown>, cpe: CPESummary) =>
    def.format(km, cpe);
  const getValueWithCpe = (def: typeof metricDefs[0], km: Record<string, unknown>, cpe: CPESummary) =>
    def.getValue(km, cpe);

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-border bg-muted/30 flex items-center gap-2">
        <CompareArrowsIcon style={{ fontSize: 20 }} className="text-primary" />
        <h3 className="text-sm font-semibold">Key Metrics Comparison</h3>
      </div>
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
    </div>
  );
}

/** Section 3: Reboot Comparison */
function RebootComparison({ cpes }: { cpes: CPESummary[] }) {
  const labels = cpes.map(cpeLabel);
  const totals = cpes.map((c) => c.reboot_summary.total);

  // Collect all unique reasons
  const allReasons = new Set<string>();
  cpes.forEach((c) => {
    Object.keys(c.reboot_summary.reasons || {}).forEach((r) => allReasons.add(r));
  });
  const reasons = Array.from(allReasons).sort();

  // Bar colors
  const barColors = [
    "#4285f4", "#ea4335", "#fbbc04", "#34a853", "#ff6d01",
    "#46bdc6", "#7baaf7", "#f07b72", "#fcd04f", "#71c287",
  ];

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-border bg-muted/30 flex items-center gap-2">
        <RestartAltIcon style={{ fontSize: 20 }} className="text-primary" />
        <h3 className="text-sm font-semibold">Reboot Comparison</h3>
      </div>
      <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Total reboots bar chart */}
        <div>
          <Plot
            data={[
              {
                type: "bar",
                x: labels,
                y: totals,
                marker: { color: barColors.slice(0, cpes.length) },
                text: totals.map(String),
                textposition: "auto" as const,
              },
            ]}
            layout={{
              title: { text: "Total Reboots per CPE" },
              height: 300,
              margin: { t: 40, b: 50, l: 50, r: 20 },
              yaxis: { title: { text: "Reboots" } },
              paper_bgcolor: "transparent",
              plot_bgcolor: "transparent",
              font: { color: "#888" },
            }}
            config={{ displayModeBar: false }}
            style={{ width: "100%" }}
          />
        </div>

        {/* Reasons breakdown table */}
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
                      return (
                        <td key={c.serial} className={`px-3 py-1.5 text-center ${count > 0 ? "font-semibold" : "text-muted-foreground"}`}>
                          {count || "-"}
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
    </div>
  );
}

/** Section 4: Pattern Domain Comparison */
function PatternComparison({ cpes }: { cpes: CPESummary[] }) {
  const domains = ["wireless", "platform", "core_router", "cellular", "mesh"];
  const domainLabels = domains.map((d) => {
    const first = cpes.find((c) => c.pattern_summary[d]);
    return first?.pattern_summary[d]?.label || d;
  });

  const barColors = [
    "#4285f4", "#ea4335", "#fbbc04", "#34a853", "#ff6d01",
    "#46bdc6", "#7baaf7", "#f07b72", "#fcd04f", "#71c287",
  ];

  // Build grouped bar traces: one trace per CPE
  const loglineTraces = cpes.map((c, i) => ({
    type: "bar" as const,
    name: cpeLabel(c),
    x: domainLabels,
    y: domains.map((d) => c.pattern_summary[d]?.total_loglines || 0),
    marker: { color: barColors[i % barColors.length] },
  }));

  const patternTraces = cpes.map((c, i) => ({
    type: "bar" as const,
    name: cpeLabel(c),
    x: domainLabels,
    y: domains.map((d) => c.pattern_summary[d]?.unique_patterns || 0),
    marker: { color: barColors[i % barColors.length] },
  }));

  // Also build a summary table
  const hasAnyPatterns = cpes.some((c) =>
    domains.some((d) => c.pattern_summary[d]?.indexed)
  );

  if (!hasAnyPatterns) {
    return (
      <div className="bg-card border border-border rounded-xl p-6 text-center text-muted-foreground">
        <WarningIcon style={{ fontSize: 32 }} className="mb-2" />
        <p>No pattern data available. Make sure log indexing is complete.</p>
      </div>
    );
  }

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-border bg-muted/30 flex items-center gap-2">
        <DescriptionIcon style={{ fontSize: 20 }} className="text-primary" />
        <h3 className="text-sm font-semibold">Pattern Domain Comparison</h3>
      </div>

      <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Log lines per domain */}
        <Plot
          data={loglineTraces}
          layout={{
            title: { text: "Log Lines per Domain" },
            barmode: "group",
            height: 320,
            margin: { t: 40, b: 60, l: 60, r: 20 },
            yaxis: { title: { text: "Log Lines" } },
            paper_bgcolor: "transparent",
            plot_bgcolor: "transparent",
            font: { color: "#888" },
            legend: { orientation: "h" as const, y: -0.2 },
          }}
          config={{ displayModeBar: false }}
          style={{ width: "100%" }}
        />

        {/* Unique patterns per domain */}
        <Plot
          data={patternTraces}
          layout={{
            title: { text: "Unique Patterns per Domain" },
            barmode: "group",
            height: 320,
            margin: { t: 40, b: 60, l: 60, r: 20 },
            yaxis: { title: { text: "Unique Patterns" } },
            paper_bgcolor: "transparent",
            plot_bgcolor: "transparent",
            font: { color: "#888" },
            legend: { orientation: "h" as const, y: -0.2 },
          }}
          config={{ displayModeBar: false }}
          style={{ width: "100%" }}
        />
      </div>

      {/* Summary table */}
      <div className="px-4 pb-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/20">
              <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Domain</th>
              {cpes.map((c) => (
                <th key={c.serial} className="text-center px-3 py-1.5 font-medium" colSpan={2}>
                  {cpeLabel(c)}
                </th>
              ))}
            </tr>
            <tr className="border-b border-border bg-muted/10">
              <th className="px-3 py-1" />
              {cpes.map((c) => (
                <React.Fragment key={c.serial}>
                  <th className="text-center px-2 py-1 text-xs text-muted-foreground font-normal">Lines</th>
                  <th className="text-center px-2 py-1 text-xs text-muted-foreground font-normal">Patterns</th>
                </React.Fragment>
              ))}
            </tr>
          </thead>
          <tbody>
            {domains.map((domain) => {
              const label = cpes[0]?.pattern_summary[domain]?.label || domain;
              return (
                <tr key={domain} className="border-b border-border/50 hover:bg-muted/10">
                  <td className="px-3 py-1.5 text-muted-foreground font-medium">{label}</td>
                  {cpes.map((c) => {
                    const ps = c.pattern_summary[domain];
                    return (
                      <React.Fragment key={c.serial}>
                        <td className="text-center px-2 py-1.5">
                          {ps?.indexed ? ps.total_loglines.toLocaleString() : "-"}
                        </td>
                        <td className="text-center px-2 py-1.5">
                          {ps?.indexed ? ps.unique_patterns.toLocaleString() : "-"}
                        </td>
                      </React.Fragment>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ================================================================ Main Page */
import React from "react";

export default function CPEOverviewPage() {
  const { projectId } = useProject();

  const { data, isLoading, error } = useQuery<OverviewData>({
    queryKey: ["cpe-overview", projectId],
    queryFn: async () => {
      if (!projectId) throw new Error("No project selected");
      const res = await cpeOverviewApi.getSummary(projectId);
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

  if (cpes.length === 0) {
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
      {/* Page header */}
      <div className="flex items-center gap-2 mb-2">
        <CompareArrowsIcon style={{ fontSize: 24, color: "#1a73e8" }} />
        <h2 className="text-lg font-bold">CPE Overview</h2>
        <span className="text-sm text-muted-foreground ml-2">
          {cpes.length} CPE{cpes.length !== 1 ? "s" : ""} in this project
        </span>
      </div>

      {/* Section 1: Device Info */}
      <DeviceInfoTable cpes={cpes} />

      {/* Section 2: Key Metrics */}
      <MetricsComparison cpes={cpes} />

      {/* Section 3: Reboot Comparison */}
      <RebootComparison cpes={cpes} />

      {/* Section 4: Pattern Domain Comparison */}
      <PatternComparison cpes={cpes} />
    </div>
  );
}
