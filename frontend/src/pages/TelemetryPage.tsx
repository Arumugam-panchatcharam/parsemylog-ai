import { useQuery } from "@tanstack/react-query";
import { telemetryApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import Plot from "react-plotly.js";
import TimelineIcon from "@mui/icons-material/Timeline";
import WifiIcon from "@mui/icons-material/Wifi";
import SettingsInputAntennaIcon from "@mui/icons-material/SettingsInputAntenna";
import RouterIcon from "@mui/icons-material/Router";
import SpeedIcon from "@mui/icons-material/Speed";
import ThermostatIcon from "@mui/icons-material/Thermostat";
import MemoryIcon from "@mui/icons-material/Memory";
import StorageIcon from "@mui/icons-material/Storage";
import NetworkCheckIcon from "@mui/icons-material/NetworkCheck";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import ErrorIcon from "@mui/icons-material/Error";
import WarningIcon from "@mui/icons-material/Warning";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import CircularProgress from "@mui/material/CircularProgress";
import type { SvgIconComponent } from "@mui/icons-material";

/* ================================================================ Types */
interface RebootTimeline {
  times: string[];
  counts: number[];
  total_reboots: number;
  events: Array<{ time: string; count: number; prev_uptime: number; new_uptime: number }>;
}
interface TelemetryData {
  device_info: Record<string, string>;
  summary: { total: number; parsed: number; overall_time_range: { first?: string; last?: string } };
  key_metrics: Array<Record<string, unknown>>;
  status_labels: Array<{ type: string; instance: string; status: string; meta: Record<string, string> }>;
  charts: Array<{ group: string; traces: Array<{ label: string; unit: string; times: string[]; values: number[] }> }>;
  reboot_timeline?: RebootTimeline;
}

/* ================================================================ Helpers */
function metricIcon(label: string): SvgIconComponent {
  const l = label.toLowerCase();
  if (l.includes("temperature") || l.includes("temp")) return ThermostatIcon;
  if (l.includes("cpu") || l.includes("processor")) return MemoryIcon;
  if (l.includes("memory") || l.includes("ram")) return StorageIcon;
  if (l.includes("throughput") || l.includes("speed") || l.includes("bitrate")) return SpeedIcon;
  if (l.includes("latency") || l.includes("rtt") || l.includes("ping")) return NetworkCheckIcon;
  if (l.includes("channel") || l.includes("ssid") || l.includes("wifi")) return WifiIcon;
  if (l.includes("signal") || l.includes("rssi") || l.includes("snr")) return SettingsInputAntennaIcon;
  return RouterIcon;
}
function isIssue(m: Record<string, unknown>): boolean {
  const label = String(m.label || "").toLowerCase();
  const value = m.value !== undefined ? String(m.value) : "";
  const trend = String(m.trend || "");
  const resets = Number(m.resets || 0);
  if (label.includes("temp") && m.peak !== undefined && Number(m.peak) > 85) return true;
  if ((label.includes("cpu") || label.includes("memory")) && m.peak !== undefined && Number(m.peak) > 90) return true;
  if (["down", "false", "disabled", "error", "fail"].some((s) => value.toLowerCase().includes(s))) return true;
  if (label.includes("signal") && trend === "decreasing") return true;
  if (resets > 3) return true;
  return false;
}
function fmtMetric(m: Record<string, unknown>): string {
  const p: string[] = [];
  if (m.value !== undefined) p.push(String(m.value));
  if (m.first !== undefined) p.push(`${m.first} ${m.unit || ""} → ${m.last} ${m.unit || ""}`);
  if (m.avg !== undefined) p.push(`avg ${m.avg}${m.unit || ""}  peak ${m.peak}${m.unit || ""}`);
  if (m.min !== undefined) p.push(`${m.min} – ${m.max} ${m.unit || ""}`);
  if (m.counts) p.push(Object.entries(m.counts as Record<string, number>).map(([k, v]) => `${k}: ${v}`).join(", "));
  if (m.time_range) p.push(`(${String(m.time_range)})`);
  return p.join("  ").trim();
}

/* Device info field groups for the top row */
const DEV_GROUPS: Array<{ title: string; fields: Array<{ key: string; label: string }> }> = [
  { title: "Identity", fields: [{ key: "model", label: "Model" }, { key: "manufacturer", label: "Manufacturer" }] },
  { title: "Hardware", fields: [{ key: "mac", label: "MAC" }, { key: "serial", label: "Serial" }, { key: "hw_version", label: "HW Version" }] },
  { title: "Software", fields: [{ key: "version", label: "SW Version" }, { key: "sdk_version", label: "SDK" }] },
  { title: "Network", fields: [{ key: "wan_type", label: "WAN" }, { key: "sw_upgrade", label: "Upgrade" }] },
];

const NO_TOOLBAR = { displayModeBar: false } as const;

/* ================================================================ Component */
export default function TelemetryPage() {
  const { projectId } = useProject();
  const { data: rawData, isLoading, isError, error } = useQuery<TelemetryData>({
    queryKey: ["telemetry", projectId],
    queryFn: async () => (await telemetryApi.parse(projectId!)).data,
    enabled: !!projectId, retry: false, staleTime: 5 * 60 * 1000,
  });
  const data = rawData ?? null;

  const stColor = (v: string) => {
    const s = v.trim().toLowerCase();
    if (["up", "true", "enabled", "1"].includes(s)) return "border-green-300 bg-green-50 text-green-800 dark:border-green-700 dark:bg-green-900/20 dark:text-green-400";
    if (["down", "false", "disabled", "0", "error"].includes(s)) return "border-red-300 bg-red-50 text-red-800 dark:border-red-700 dark:bg-red-900/20 dark:text-red-400";
    return "border-gray-300 bg-gray-50 text-gray-700 dark:border-gray-600 dark:bg-gray-800/50 dark:text-gray-400";
  };
  const stIcon = (v: string) => {
    const s = v.trim().toLowerCase();
    if (["up", "true", "enabled", "1"].includes(s)) return <CheckCircleIcon style={{ fontSize: 15 }} className="text-green-600 dark:text-green-400" />;
    if (["down", "false", "disabled", "0", "error"].includes(s)) return <ErrorIcon style={{ fontSize: 15 }} className="text-red-600 dark:text-red-400" />;
    return <WarningIcon style={{ fontSize: 15 }} className="text-yellow-600 dark:text-yellow-400" />;
  };

  return (
    <div className="p-4 space-y-4 max-w-full overflow-y-auto">
      <div className="flex items-center gap-2">
        <TimelineIcon style={{ fontSize: 24, color: "#1a73e8" }} />
        <h2 className="text-lg font-semibold">Telemetry Dashboard</h2>
        {data?.summary && (
          <span className="ml-auto text-[11px] text-muted-foreground">
            {data.summary.parsed}/{data.summary.total} parsed
            {data.summary.overall_time_range?.first && ` | ${data.summary.overall_time_range.first.slice(0, 19)} — ${data.summary.overall_time_range.last?.slice(0, 19)}`}
          </span>
        )}
      </div>

      {isLoading && <div className="flex items-center gap-3 justify-center py-16 text-muted-foreground"><CircularProgress size={24} /><span className="text-sm">Parsing telemetry data...</span></div>}
      {isError && <div className="p-4 bg-destructive/10 text-destructive rounded-xl text-sm flex items-center gap-2"><ErrorIcon style={{ fontSize: 18 }} />{(error as { response?: { data?: { error?: string } } })?.response?.data?.error || "Error parsing telemetry"}</div>}

      {data && (
        <>
          {/* ========== ROW 1: Device Info grouped cards ========== */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {DEV_GROUPS.map((group) => {
              const entries = group.fields.filter((f) => data.device_info[f.key]);
              if (entries.length === 0) return null;
              return (
                <div key={group.title} className="bg-card border border-border rounded-xl p-3">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">{group.title}</p>
                  {entries.map(({ key, label }) => {
                    const val = data.device_info[key];
                    return (
                      <div key={key} className="flex items-baseline gap-2 text-xs py-0.5">
                        <span className="text-muted-foreground font-medium shrink-0">{label}</span>
                        <span className="font-semibold truncate">
                          {key === "sw_upgrade" && val.startsWith("Yes") ? (
                            <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400 text-[10px] font-bold">
                              <WarningIcon style={{ fontSize: 11 }} />{val}
                            </span>
                          ) : val}
                        </span>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>

          {/* ========== ROW 2: Radio/SSID + Key Metrics side by side ========== */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Radio / SSID Status */}
            {data.status_labels.length > 0 && (
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="px-4 py-2 border-b border-border bg-muted/30">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                    <SettingsInputAntennaIcon style={{ fontSize: 14, color: "#1a73e8" }} /> Radio / SSID Status
                  </h3>
                </div>
                <div className="p-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {data.status_labels.map((s, idx) => (
                    <div key={idx} className={`border rounded-lg p-2.5 ${stColor(s.status)}`}>
                      <div className="flex items-center gap-1.5 text-xs">
                        {stIcon(s.status)}
                        {s.type === "Radio" ? <SettingsInputAntennaIcon style={{ fontSize: 14 }} /> : <WifiIcon style={{ fontSize: 14 }} />}
                        <span className="font-semibold flex-1">{s.type} {s.instance}</span>
                        <span className="text-[10px] capitalize font-bold">{s.status}</span>
                      </div>
                      {Object.keys(s.meta).length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1.5 pl-6">
                          {Object.entries(s.meta).map(([k, v]) => (
                            <span key={k} className="text-[10px] bg-white/50 dark:bg-black/15 px-1.5 py-0.5 rounded font-medium">{k}: {v}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Key Metrics */}
            {data.key_metrics.length > 0 && (
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="px-4 py-2 border-b border-border bg-muted/30">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                    <SpeedIcon style={{ fontSize: 14, color: "#1a73e8" }} /> Key Metrics
                  </h3>
                </div>
                <div className="p-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {data.key_metrics.map((m, idx) => {
                    const bad = isIssue(m);
                    const MI = metricIcon(String(m.label));
                    return (
                      <div key={idx} className={`rounded-lg border p-2.5 ${bad ? "border-red-300 bg-red-50/80 dark:border-red-800 dark:bg-red-900/15" : "border-border"}`}>
                        <div className="flex items-center gap-2">
                          <div className={`rounded-md p-1 shrink-0 ${bad ? "bg-red-100 dark:bg-red-900/30" : "bg-primary/10"}`}>
                            <MI style={{ fontSize: 16, color: bad ? "#d93025" : "#1a73e8" }} />
                          </div>
                          <span className={`text-xs font-semibold flex-1 ${bad ? "text-red-700 dark:text-red-400" : ""}`}>{String(m.label)}</span>
                          {Number(m.resets) > 0 && <span className="text-[10px] text-red-600 dark:text-red-400 font-bold flex items-center gap-0.5"><RestartAltIcon style={{ fontSize: 11 }} />{String(m.resets)}</span>}
                          {m.trend === "decreasing" && <TrendingDownIcon style={{ fontSize: 13, color: "#d93025" }} />}
                          {m.trend === "increasing" && <TrendingUpIcon style={{ fontSize: 13, color: "#188038" }} />}
                        </div>
                        <p className={`text-[11px] mt-1 pl-7 ${bad ? "text-red-600 dark:text-red-400" : "text-muted-foreground"}`}>{fmtMetric(m)}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* ========== REBOOT TIMELINE ========== */}
          {data.reboot_timeline && data.reboot_timeline.total_reboots > 0 && (
            <div className="bg-card border border-border rounded-xl overflow-hidden">
              <div className="px-4 py-2 border-b border-border bg-muted/30 flex items-center justify-between">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                  <RestartAltIcon style={{ fontSize: 14, color: "#d93025" }} /> Reboot Timeline
                </h3>
                <span className="text-[10px] font-bold text-red-600 dark:text-red-400">{data.reboot_timeline.total_reboots} reboot(s) detected</span>
              </div>
              <div className="p-2">
                <Plot
                  data={[
                    {
                      x: data.reboot_timeline.times,
                      y: data.reboot_timeline.counts,
                      type: "scatter" as const,
                      mode: "lines+markers" as const,
                      name: "Cumulative Reboots",
                      line: { color: "#d93025", width: 2, shape: "hv" },
                      marker: { size: 4, color: "#d93025" },
                      fill: "tozeroy",
                      fillcolor: "rgba(217,48,37,0.08)",
                    },
                    ...(data.reboot_timeline.events.length > 0
                      ? [{
                          x: data.reboot_timeline.events.map((e) => e.time),
                          y: data.reboot_timeline.events.map((e) => e.count),
                          type: "scatter" as const,
                          mode: "markers" as const,
                          name: "Reboot Event",
                          marker: { size: 10, color: "#d93025", symbol: "x" },
                          text: data.reboot_timeline.events.map((e) => `Reboot #${e.count}`),
                          hovertemplate: "Reboot #%{y}<br>%{x}<extra></extra>",
                        }]
                      : []),
                  ]}
                  layout={{
                    height: 200,
                    margin: { l: 40, r: 15, t: 5, b: 35 },
                    xaxis: { title: { text: "Time" }, tickfont: { size: 10 } },
                    yaxis: { title: { text: "Reboots" }, tickfont: { size: 10 }, dtick: 1 },
                    hovermode: "x unified",
                    legend: { orientation: "h", y: 1.2, x: 0.5, xanchor: "center", font: { size: 10 } },
                    paper_bgcolor: "transparent",
                    plot_bgcolor: "transparent",
                    font: { family: "Roboto, sans-serif", size: 11 },
                  }}
                  config={NO_TOOLBAR}
                  style={{ width: "100%" }}
                />
              </div>
            </div>
          )}

          {/* ========== CHARTS ========== */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {data.charts.map((chart, cIdx) => (
              <div key={cIdx} className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="px-4 py-2 border-b border-border bg-muted/30">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{chart.group}</h3>
                </div>
                <div className="p-2">
                  <Plot
                    data={chart.traces.map((t) => ({ x: t.times, y: t.values, name: `${t.label} (${t.unit})`, type: "scatter" as const, mode: "lines+markers" as const, marker: { size: 3 } }))}
                    layout={{ height: 280, margin: { l: 45, r: 15, t: 5, b: 35 }, xaxis: { title: { text: "Time" }, tickfont: { size: 10 } }, yaxis: { title: { text: "Value" }, tickfont: { size: 10 } }, hovermode: "x unified", legend: { orientation: "h", y: 1.15, x: 0.5, xanchor: "center", font: { size: 10 } }, paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: { family: "Roboto, sans-serif", size: 11 } }}
                    config={NO_TOOLBAR}
                    style={{ width: "100%" }}
                  />
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
