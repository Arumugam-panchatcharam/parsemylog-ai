import { useState, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { telemetryApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import Plot from "react-plotly.js";
import TelemetryOverviewTab from "@/pages/TelemetryOverviewTab";
import TimelineIcon from "@mui/icons-material/Timeline";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
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
import RefreshIcon from "@mui/icons-material/Refresh";
import ExploreIcon from "@mui/icons-material/Explore";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import CachedIcon from "@mui/icons-material/Cached";
import DownloadIcon from "@mui/icons-material/Download";
import SignalCellularAltIcon from "@mui/icons-material/SignalCellularAlt";
import HomeIcon from "@mui/icons-material/Home";
import PowerSettingsNewIcon from "@mui/icons-material/PowerSettingsNew";
import SecurityIcon from "@mui/icons-material/Security";
import HubIcon from "@mui/icons-material/Hub";
import ToggleOnIcon from "@mui/icons-material/ToggleOn";
import DeviceHubIcon from "@mui/icons-material/DeviceHub";
import DevicesIcon from "@mui/icons-material/Devices";
import NavigateBeforeIcon from "@mui/icons-material/NavigateBefore";
import NavigateNextIcon from "@mui/icons-material/NavigateNext";
import FilterListIcon from "@mui/icons-material/FilterList";
import CircularProgress from "@mui/material/CircularProgress";
import Slider from "@mui/material/Slider";
import type { SvgIconComponent } from "@mui/icons-material";

/* ================================================================ Types */
interface RebootTimeline {
  times: string[];
  counts: number[];
  total_reboots: number;
  events: Array<{ 
    time: string; 
    count: number; 
    prev_uptime: number; 
    new_uptime: number;
    reboot_type?: "soft" | "hard";
  }>;
  all_events?: Array<{ 
    time: string; 
    source?: string; 
    label?: string;
    reason?: string;
    reboot_type?: "soft" | "hard";
  }>;
}
interface AvailableFieldInfo {
  key: string;
  type: string;
  plottable: boolean;
  count: number;
  samples: string[];
}
interface AvailableFields {
  configured_keys: string[];
  unconfigured: Record<string, AvailableFieldInfo[]>;
  stats: { total_fields: number; configured: number; unconfigured: number };
}
interface TopoRadio { band: string; standards: string; channel: string; bandwidth: string; temperature: string; bss_count: number; sta_count: number }
interface TopoClient {
  mac: string; band: string; ssid: string; operating_standard: string;
  max_phy_rate: number; last_dl_rate: number; last_ul_rate: number;
  signal_strength_dbm: string; bytes_rx: number; bytes_tx: number;
  connect_time: number; retrans_count: number; is_affiliated: boolean;
}
interface TopoNode {
  id: string; index: string; is_gateway: boolean;
  manufacturer: string; model: string; serial_number: string; software_version: string;
  backhaul_mac: string; backhaul_media_type: string; backhaul_phy_rate: number; backhaul_al_id: string;
  radios: TopoRadio[]; connected_clients: number; clients: TopoClient[];
  memory: { free: string; total: string; cached: string };
  cpu: { usage: string; temperature: string };
  onboarded: string; service_active: string;
  backhaul_signal_strength: string; backhaul_link_utilization: string;
}
interface TopoEdge { from_id: string; to_id: string; media_type: string; phy_rate: number; signal_strength: string; link_utilization: string; is_wifi: boolean }
interface TopoSnapshot { time: string; log_timestamp: string; profile: string; device_count: number; nodes: TopoNode[]; edges: TopoEdge[]; mermaid: string }
interface MeshTopology { snapshots: TopoSnapshot[]; total_snapshots: number; time_range: { start: string; end: string } }

interface TelemetryData {
  device_info: Record<string, string>;
  summary: { 
    total: number; 
    parsed: number; 
    overall_time_range: { first?: string; last?: string };
    profile_stats?: Record<string, { parsed: number }>;
  };
  key_metrics: Array<Record<string, unknown>>;
  status_labels: Array<{ type: string; instance: string; status: string; meta: Record<string, string> }>;
  charts: Array<{ group: string; traces: Array<{ label: string; unit: string; times: string[]; values: number[]; raw_values?: number[]; raw_unit_original?: string; normalized?: boolean }> }>;
  reboot_timeline?: RebootTimeline;
  mesh_topology?: MeshTopology;
  available_fields?: AvailableFields;
  cached?: boolean;
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
function fmtVal(v: unknown, unit: string): string {
  const n = Number(v);
  if (isNaN(n)) return String(v);
  const u = unit.toLowerCase();
  if (u === "kb") {
    if (n >= 1_000_000) return `${(n / (1024 * 1024)).toFixed(2)} GB`;
    if (n >= 1024) return `${(n / 1024).toFixed(1)} MB`;
    return `${n} KB`;
  }
  if (u === "sec" || u === "s") {
    if (n >= 86400) return `${(n / 86400).toFixed(1)} days`;
    if (n >= 3600) return `${(n / 3600).toFixed(1)} hours`;
    if (n >= 120) return `${(n / 60).toFixed(0)} min`;
  }
  return `${n} ${unit}`;
}

function fmtMetric(m: Record<string, unknown>): string {
  const p: string[] = [];
  const unit = String(m.unit || "");
  if (m.value !== undefined) p.push(String(m.value));
  if (m.first !== undefined) p.push(`${fmtVal(m.first, unit)} → ${fmtVal(m.last, unit)}`);
  if (m.total !== undefined && m.total !== null) p.push(`(total: ${fmtVal(m.total, unit)})`);
  if (m.avg !== undefined) p.push(`avg ${fmtVal(m.avg, unit)}  peak ${fmtVal(m.peak, unit)}`);
  if (m.min !== undefined) p.push(`${fmtVal(m.min, unit)} – ${fmtVal(m.max, unit)}`);
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
  const { cpeId } = useCPE();
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<"cpe" | "overview">("cpe");
  const [reparsing, setReparsing] = useState(false);
  const [showDiscovery, setShowDiscovery] = useState(false);
  const [showExportDialog, setShowExportDialog] = useState(false);

  const { data: rawData, isLoading, isError, error } = useQuery<TelemetryData>({
    queryKey: ["telemetry", projectId, cpeId],
    queryFn: async () => (await telemetryApi.parse(projectId!, cpeId)).data,
    enabled: !!projectId, retry: false, staleTime: 5 * 60 * 1000,
  });
  const data = rawData ?? null;

  const handleReparse = async () => {
    setReparsing(true);
    try {
      const res = await telemetryApi.parse(projectId!, cpeId, true);
      qc.setQueryData(["telemetry", projectId, cpeId], res.data);
    } catch { /* ignore */ }
    setReparsing(false);
  };

  const handleExportCsv = async (profiles: string[], format: 'combined' | 'separate') => {
    if (!projectId || !cpeId) return;
    
    try {
      const response = await telemetryApi.exportCsv(projectId, cpeId, profiles, format);
      
      // Get filename from Content-Disposition header or generate one
      const contentDisposition = response.headers['content-disposition'];
      let filename = 'telemetry_export.csv';
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="?(.+)"?/);
        if (match) filename = match[1];
      }
      
      // Create blob and download
      const blob = new Blob([response.data]);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      
      setShowExportDialog(false);
    } catch (err) {
      console.error('Export failed:', err);
      alert('Failed to export CSV. Please try again.');
    }
  };

  const stColor = (v: string) => {
    const s = v.trim().toLowerCase();
    if (["up", "true", "enabled", "1", "good", "connected"].includes(s)) return "border-green-300 bg-green-50 text-green-800 dark:border-green-700 dark:bg-green-900/20 dark:text-green-400";
    if (["down", "false", "disabled", "0", "error", "bad", "poor", "disconnected"].includes(s)) return "border-red-300 bg-red-50 text-red-800 dark:border-red-700 dark:bg-red-900/20 dark:text-red-400";
    return "border-gray-300 bg-gray-50 text-gray-700 dark:border-gray-600 dark:bg-gray-800/50 dark:text-gray-400";
  };
  const stIcon = (v: string) => {
    const s = v.trim().toLowerCase();
    if (["up", "true", "enabled", "1", "good", "connected"].includes(s)) return <CheckCircleIcon style={{ fontSize: 15 }} className="text-green-600 dark:text-green-400" />;
    if (["down", "false", "disabled", "0", "error", "bad", "poor", "disconnected"].includes(s)) return <ErrorIcon style={{ fontSize: 15 }} className="text-red-600 dark:text-red-400" />;
    return <WarningIcon style={{ fontSize: 15 }} className="text-yellow-600 dark:text-yellow-400" />;
  };

  const statusTypeIcon = (type: string): SvgIconComponent => {
    const t = type.toLowerCase();
    if (t.includes("radio")) return SettingsInputAntennaIcon;
    if (t.includes("ssid") || t.includes("wifi")) return WifiIcon;
    if (t.includes("cellular")) return SignalCellularAltIcon;
    if (t.includes("smart")) return HomeIcon;
    if (t.includes("power") || t.includes("dpd")) return PowerSettingsNewIcon;
    if (t.includes("cujo") || t.includes("security")) return SecurityIcon;
    if (t.includes("airties") || t.includes("edge")) return HubIcon;
    if (t.includes("gpon")) return NetworkCheckIcon;
    if (t.includes("ppp") || t.includes("wanoe") || t.includes("wan")) return RouterIcon;
    return ToggleOnIcon;
  };

  return (
    <div className="p-4 space-y-4 max-w-full overflow-y-auto">
      <div className="flex items-center gap-2 flex-wrap">
        <TimelineIcon style={{ fontSize: 24, color: "#1a73e8" }} />
        <h2 className="text-lg font-semibold">Telemetry Dashboard</h2>
        {activeTab === "cpe" && data?.cached && (
          <span className="inline-flex items-center gap-1 text-[10px] text-blue-600 bg-blue-50 border border-blue-200 rounded px-1.5 py-0.5">
            <CachedIcon style={{ fontSize: 12 }} /> cached
          </span>
        )}
        {activeTab === "cpe" && data?.summary && (
          <span className="text-[11px] text-muted-foreground">
            {data.summary.parsed}/{data.summary.total} parsed
            {data.summary.overall_time_range?.first && ` | ${data.summary.overall_time_range.first.slice(0, 19)} — ${data.summary.overall_time_range.last?.slice(0, 19)}`}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {activeTab === "cpe" && data && (
            <>
              <button
                onClick={() => setShowExportDialog(true)}
                className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border hover:bg-muted transition-colors"
                title="Export telemetry data to CSV"
              >
                <DownloadIcon style={{ fontSize: 15 }} />
                Export CSV
              </button>
              <button
                onClick={() => setShowDiscovery((v) => !v)}
                className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border hover:bg-muted transition-colors"
              >
                <ExploreIcon style={{ fontSize: 15 }} />
                All Fields
                {data.available_fields?.stats && (
                  <span className="text-[10px] bg-primary/10 text-primary rounded px-1">{data.available_fields.stats.total_fields}</span>
                )}
              </button>
            </>
          )}
          {activeTab === "cpe" && (
            <button
              onClick={handleReparse}
              disabled={reparsing || isLoading}
              className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border hover:bg-muted transition-colors disabled:opacity-50"
              title="Re-parse from raw log file"
            >
              {reparsing ? <CircularProgress size={14} /> : <RefreshIcon style={{ fontSize: 15 }} />}
              Re-parse
            </button>
          )}
        </div>
      </div>

      {/* ========== Tab bar ========== */}
      <div className="flex items-center gap-1 border-b border-border">
        <button
          onClick={() => setActiveTab("cpe")}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "cpe"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
          }`}
        >
          <TimelineIcon style={{ fontSize: 16 }} />
          CPE Analysis
        </button>
        <button
          onClick={() => setActiveTab("overview")}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "overview"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
          }`}
        >
          <CompareArrowsIcon style={{ fontSize: 16 }} />
          Cross-CPE Overview
        </button>
      </div>

      {/* ========== Cross-CPE Overview tab ========== */}
      {activeTab === "overview" && <TelemetryOverviewTab />}

      {/* ========== CPE Analysis tab ========== */}
      {activeTab === "cpe" && (
        <>
      {isLoading && <div className="flex items-center gap-3 justify-center py-16 text-muted-foreground"><CircularProgress size={24} /><span className="text-sm">Parsing telemetry data...</span></div>}
      {isError && <div className="p-4 bg-destructive/10 text-destructive rounded-xl text-sm flex items-center gap-2"><ErrorIcon style={{ fontSize: 18 }} />{(error as { response?: { data?: { error?: string } } })?.response?.data?.error || "Error parsing telemetry"}</div>}

      {/* ========== Available Fields Discovery Panel ========== */}
      {showDiscovery && data?.available_fields && (
        <AvailableFieldsPanel fields={data.available_fields} onClose={() => setShowDiscovery(false)} />
      )}

      {/* ========== CSV Export Dialog ========== */}
      {showExportDialog && data && (
        <ExportDialog
          availableProfiles={data.summary?.profile_stats ? Object.keys(data.summary.profile_stats) : []}
          onClose={() => setShowExportDialog(false)}
          onExport={handleExportCsv}
          profileCounts={data.summary?.profile_stats}
          hasData={!!data.summary?.parsed}
        />
      )}

      {data && (
        <>
          {/* ========== ROW 1: Device Info grouped cards ========== */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {DEV_GROUPS.map((group) => {
              const entries = group.fields.filter((f) => (data.device_info ?? {})[f.key]);
              if (entries.length === 0) return null;
              return (
                <div key={group.title} className="bg-card border border-border rounded-xl p-3">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">{group.title}</p>
                  {entries.map(({ key, label }) => {
                    const val = (data.device_info ?? {})[key];
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

          {/* ========== MESH TOPOLOGY ========== */}
          {data.mesh_topology && data.mesh_topology.total_snapshots > 0 && (
            <MeshTopologyPanel topology={data.mesh_topology} />
          )}

          {/* ========== ROW 2: Radio/SSID + Key Metrics side by side ========== */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Radio / SSID Status */}
            {(data.status_labels ?? []).length > 0 && (
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="px-4 py-2 border-b border-border bg-muted/30">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                    <SettingsInputAntennaIcon style={{ fontSize: 14, color: "#1a73e8" }} /> Feature Status
                  </h3>
                </div>
                <div className="p-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                  {(data.status_labels ?? []).map((s, idx) => {
                    const TypeIcon = statusTypeIcon(s.type);
                    const displayName = s.instance ? `${s.type} ${s.instance}` : s.type;
                    return (
                      <div key={idx} className={`border rounded-lg p-2.5 ${stColor(s.status)}`}>
                        <div className="flex items-center gap-1.5 text-xs">
                          {stIcon(s.status)}
                          <TypeIcon style={{ fontSize: 14 }} />
                          <span className="font-semibold flex-1">{displayName}</span>
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
                    );
                  })}
                </div>
              </div>
            )}

            {/* Key Metrics */}
            {(data.key_metrics ?? []).length > 0 && (
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="px-4 py-2 border-b border-border bg-muted/30">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                    <SpeedIcon style={{ fontSize: 14, color: "#1a73e8" }} /> Key Metrics
                  </h3>
                </div>
                <div className="p-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {(data.key_metrics ?? []).map((m, idx) => {
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

          {/* ========== CHARTS ========== */}
          {(data.charts ?? []).length > 0 && (
            <div className="space-y-2">
              {data.summary?.parsed === 0 && (
                <p className="text-[11px] text-muted-foreground mb-2">
                  Charts from selfHeal and telemetry_marker (no telemetry2_0 data).
                </p>
              )}
              {/* Reboot Legend */}
              {(data.reboot_timeline?.all_events ?? []).length > 0 && (
                <div className="bg-card border border-border rounded-lg p-2 mb-2">
                  <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
                    <span className="font-semibold">Reboot Markers:</span>
                    <div className="flex items-center gap-1">
                      <div className="w-6 h-0.5 bg-[#1a73e8]"></div>
                      <span><span className="font-mono font-semibold text-[#1a73e8]">B</span> = BootTime (actual reboot start)</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <div className="w-6 h-0.5 border-t-2 border-dashed border-[#d93025]"></div>
                      <span><span className="font-mono font-semibold text-[#d93025]">TR</span> = Telemetry Recovery (services online)</span>
                    </div>
                    <div className="border-l border-border pl-4 ml-2 flex items-center gap-3">
                      <div className="flex items-center gap-1">
                        <span className="font-mono font-semibold text-[#3b82f6]">S</span>
                        <span>= Soft Reboot (software)</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="font-mono font-semibold text-[#d93025]">H</span>
                        <span>= Hard Reboot (power/crash)</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                {(data.charts ?? []).map((chart, cIdx) => {
                  // Build reboot event vertical lines - use all_events for both BootTime and Telemetry
                  const rebootShapes = (data.reboot_timeline?.all_events ?? []).map((e: any) => {
                    const isBootTime = e.source === "boottime";
                    const isSoft = e.reboot_type === "soft";
                    const isHard = e.reboot_type === "hard";
                    
                    // Determine color: use reboot_type if available, otherwise use source-based color
                    let lineColor = isBootTime ? "#1a73e8" : "#d93025"; // Default: blue for BootTime, red for Telemetry
                    if (isSoft) lineColor = "#3b82f6"; // Soft reboot = blue
                    else if (isHard) lineColor = "#d93025"; // Hard reboot = red
                    
                    return {
                      type: "line" as const,
                      x0: e.time,
                      x1: e.time,
                      y0: 0,
                      y1: 1,
                      yref: "paper" as const,
                      line: { 
                        color: lineColor, 
                        width: isBootTime ? 2 : 1.5, 
                        dash: (isBootTime ? "solid" : "dot") as "solid" | "dot" | "dash" | "longdash" | "dashdot" | "longdashdot"
                      },
                    };
                  });

                  // Build reboot event annotations
                  const rebootAnnotations = (data.reboot_timeline?.all_events ?? []).map((e: any) => {
                    const isBootTime = e.source === "boottime";
                    const sourceLabel = e.label || (isBootTime ? "B" : "TR");
                    const isSoft = e.reboot_type === "soft";
                    const isHard = e.reboot_type === "hard";
                    
                    // Show both source and type: "B-S", "TR-H", etc.
                    const typeLabel = isSoft ? "S" : isHard ? "H" : "";
                    const fullLabel = typeLabel ? `${sourceLabel}-${typeLabel}` : sourceLabel;
                    
                    // Determine color based on reboot_type
                    let fontColor = isBootTime ? "#1a73e8" : "#d93025";
                    if (isSoft) fontColor = "#3b82f6";
                    else if (isHard) fontColor = "#d93025";
                    
                    return {
                      x: e.time,
                      y: 1,
                      yref: "paper" as const,
                      text: fullLabel,
                      showarrow: false,
                      font: { 
                        size: 9, 
                        color: fontColor, 
                        family: "monospace" 
                      },
                      yanchor: "bottom" as const,
                    };
                  });

                  // Build invisible scatter points for reboot hover tooltips
                  const rebootHoverTrace = {
                    type: "scatter" as const,
                    mode: "markers" as const,
                    x: (data.reboot_timeline?.all_events ?? []).map((e: any) => e.time),
                    y: (data.reboot_timeline?.all_events ?? []).map(() => 0), // Bottom of chart
                    marker: {
                      size: 10,
                      opacity: 0, // Invisible but still hoverable
                    },
                    hovertemplate: (data.reboot_timeline?.all_events ?? []).map((e: any) => {
                      const isBootTime = e.source === "boottime";
                      const sourceLabel = isBootTime ? "BootTime" : "Telemetry Recovery";
                      const typeLabel = e.reboot_type === "soft" ? "Soft Reboot" : 
                                       e.reboot_type === "hard" ? "Hard Reboot" : "Reboot";
                      const reasonText = e.reason && e.reason !== "" ? 
                                        `<br><b>Reason:</b> ${e.reason}` : "";
                      
                      return `<b>${sourceLabel}</b> (${typeLabel})<br><b>Time:</b> %{x}${reasonText}<extra></extra>`;
                    }),
                    showlegend: false,
                    name: "Reboot Events",
                  };

                  return (
                    <div key={cIdx} className="bg-card border border-border rounded-xl overflow-hidden">
                      <div className="px-4 py-2 border-b border-border bg-muted/30">
                        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{chart.group}</h3>
                      </div>
                      <div className="p-2">
                        <Plot
                          data={[
                            ...chart.traces.map((t) => {
                              if (t.normalized && t.raw_values && t.raw_unit_original) {
                                // Normalized trace: show raw values in hover
                                return {
                                  x: t.times,
                                  y: t.values,
                                  name: `${t.label} (${t.raw_unit_original})`,
                                  type: "scatter" as const,
                                  mode: "lines+markers" as const,
                                  marker: { size: 3 },
                                  customdata: t.raw_values,
                                  hovertemplate: `<b>${t.label}</b><br>%{x}<br>%{customdata} ${t.raw_unit_original}<extra></extra>`,
                                };
                              } else {
                                // Normal trace
                                return {
                                  x: t.times,
                                  y: t.values,
                                  name: `${t.label} (${t.unit})`,
                                  type: "scatter" as const,
                                  mode: "lines+markers" as const,
                                  marker: { size: 3 },
                                };
                              }
                            }),
                            rebootHoverTrace, // Add hover trace for reboot events
                          ]}
                          layout={{
                            height: 280,
                            margin: { l: 45, r: 15, t: 5, b: 35 },
                            xaxis: { title: { text: "Time" }, tickfont: { size: 10 } },
                            yaxis: { title: { text: "Value" }, tickfont: { size: 10 } },
                            hovermode: "x unified",
                            legend: { orientation: "h", y: 1.15, x: 0.5, xanchor: "center", font: { size: 10 } },
                            paper_bgcolor: "transparent",
                            plot_bgcolor: "transparent",
                            font: { family: "Roboto, sans-serif", size: 11 },
                            shapes: rebootShapes,
                            annotations: rebootAnnotations,
                          }}
                          config={NO_TOOLBAR}
                          style={{ width: "100%" }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

        </>
      )}
        </>
      )}
    </div>
  );
}

/* ================================================================ Mesh Topology */

/** Render a MAC address with the last two octets bolded */
function MacBold({ mac }: { mac: string }) {
  const parts = mac.split(":");
  if (parts.length >= 3) {
    const head = parts.slice(0, -2).join(":");
    const tail = parts.slice(-2).join(":");
    return <>{head}:<span className="font-bold">{tail}</span></>;
  }
  return <>{mac}</>;
}

function signalColor(sig: string): string {
  const val = parseFloat(sig);
  if (isNaN(val) || val === 0) return "text-gray-400";
  // Signal is RSSI in dBm (negative values): -30 excellent, -67 good, -70 fair, -80+ poor
  if (val >= -55) return "text-green-600 dark:text-green-400";
  if (val >= -67) return "text-emerald-600 dark:text-emerald-400";
  if (val >= -75) return "text-yellow-600 dark:text-yellow-400";
  return "text-red-600 dark:text-red-400";
}

/** Badge color classes for WiFi operating standard */
function stdBadge(std: string): { bg: string; text: string; label: string } {
  switch (std.toLowerCase()) {
    case "be": return { bg: "bg-purple-100 dark:bg-purple-900/40", text: "text-purple-700 dark:text-purple-300", label: "WiFi 7 (be)" };
    case "ax": return { bg: "bg-green-100 dark:bg-green-900/40", text: "text-green-700 dark:text-green-300", label: "WiFi 6 (ax)" };
    case "ac": return { bg: "bg-blue-100 dark:bg-blue-900/40", text: "text-blue-700 dark:text-blue-300", label: "WiFi 5 (ac)" };
    case "n":  return { bg: "bg-gray-100 dark:bg-gray-800/60", text: "text-gray-600 dark:text-gray-300", label: "WiFi 4 (n)" };
    default:   return { bg: "bg-gray-100 dark:bg-gray-800/60", text: "text-gray-500 dark:text-gray-400", label: std || "?" };
  }
}

/** Format bytes to a human-readable string */
function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const val = bytes / Math.pow(1024, i);
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`;
}

/** Format Kbps rate to readable Mbps / Gbps */
function formatRate(kbps: number): string {
  if (kbps === 0) return "—";
  if (kbps >= 1_000_000) return `${(kbps / 1_000_000).toFixed(1)}Gbps`;
  if (kbps >= 1000) return `${Math.round(kbps / 1000)}Mbps`;
  return `${kbps}Kbps`;
}

/** Format seconds to a human-readable duration */
function formatDuration(seconds: number): string {
  if (seconds === 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h${m > 0 ? ` ${m}m` : ""}`;
  return `${m}m`;
}

function memPercent(free: string, total: string): number | null {
  const f = parseInt(free, 10);
  const t = parseInt(total, 10);
  if (isNaN(f) || isNaN(t) || t === 0) return null;
  return Math.round(((t - f) / t) * 100);
}

function MeshTopologyPanel({ topology }: { topology: MeshTopology }) {
  // Detect unique profiles across all snapshots
  const profiles = useMemo(() => {
    const s = new Set<string>();
    for (const snap of topology.snapshots) {
      if (snap.profile) s.add(snap.profile);
    }
    return Array.from(s).sort();
  }, [topology.snapshots]);

  const [selectedProfile, setSelectedProfile] = useState<string>("all");

  // Filter snapshots by selected profile
  const filteredSnapshots = useMemo(() => {
    if (selectedProfile === "all") return topology.snapshots;
    return topology.snapshots.filter((s) => s.profile === selectedProfile);
  }, [topology.snapshots, selectedProfile]);

  const [snapshotIdx, setSnapshotIdx] = useState(filteredSnapshots.length - 1);

  // Clamp snapshot index when filtered list changes
  if (snapshotIdx >= filteredSnapshots.length && filteredSnapshots.length > 0) {
    setSnapshotIdx(filteredSnapshots.length - 1);
  }

  const snap = filteredSnapshots[snapshotIdx] ?? filteredSnapshots[0];

  // Build tree structure using edges (not backhaul_al_id) to avoid duplicates
  const gateway = snap?.nodes.find((n) => n.is_gateway) ?? null;
  const { childMap, connectedIds } = useMemo(() => {
    const m = new Map<string, TopoNode[]>();
    const connected = new Set<string>();
    if (!snap) return { childMap: m, connectedIds: connected };
    const nodeById = new Map(snap.nodes.map((n) => [n.id, n]));

    // Build from edges -- each edge.to_id is a child of edge.from_id
    for (const edge of snap.edges) {
      const child = nodeById.get(edge.to_id);
      if (!child) continue;
      connected.add(edge.to_id);
      if (!m.has(edge.from_id)) m.set(edge.from_id, []);
      m.get(edge.from_id)!.push(child);
    }
    return { childMap: m, connectedIds: connected };
  }, [snap]);

  if (!snap) return (
    <div className="bg-card border border-border rounded-xl p-6 text-center text-sm text-muted-foreground">
      No topology snapshots found for the selected profile.
    </div>
  );

  // Get edge info for a node
  const edgeFor = (nodeId: string) => snap.edges.find((e) => e.to_id === nodeId);

  const sliderMarks = filteredSnapshots.map((s, i) => ({
    value: i,
    label: i === 0 || i === filteredSnapshots.length - 1 ? s.time.slice(11, 16) : "",
  }));

  // Recursive render for multi-hop topology
  const renderChildren = (parentId: string, depth: number) => {
    const children = childMap.get(parentId) || [];
    if (children.length === 0) return null;
    return (
      <div className="relative flex justify-center" style={{ marginTop: depth === 1 ? 0 : 8 }}>
        {/* Horizontal connector bar spanning all children */}
        {children.length > 1 && (
          <div
            className="absolute top-0 border-t-2 border-dashed border-blue-400"
            style={{
              left: `calc(${100 / (2 * children.length)}% + 4px)`,
              right: `calc(${100 / (2 * children.length)}% + 4px)`,
            }}
          />
        )}
        {/* flex-nowrap prevents children from wrapping to a second row,
            which would break the horizontal connector bar alignment */}
        <div className="flex flex-nowrap justify-center gap-3">
          {children.map((node) => {
            const edge = edgeFor(node.id);
            const isWifi = edge?.is_wifi ?? true;
            return (
              <div key={node.id} className="flex flex-col items-center shrink-0 transition-all duration-200">
                {/* Vertical drop-down line from horizontal bar */}
                <div className={`w-0 h-5 ${isWifi ? "border-l-2 border-dashed border-blue-400" : "border-l-2 border-solid border-gray-500"}`} />
                {/* Edge label */}
                {edge && (
                  <span className="text-[9px] text-muted-foreground bg-muted/60 px-1.5 py-0.5 rounded mb-1 whitespace-nowrap">
                    {edge.media_type.replace("IEEE ", "")} {edge.phy_rate > 0 ? `${edge.phy_rate}Mbps` : ""}
                    {edge.signal_strength ? <span className={` ml-1 font-bold ${signalColor(edge.signal_strength)}`}>{edge.signal_strength}dBm</span> : ""}
                  </span>
                )}
                {/* Node card */}
                <DeviceNodeCard node={node} />
                {/* Render this node's children (multi-hop) */}
                {childMap.has(node.id) && (
                  <div className="w-0 h-5 mt-1 border-l-2 border-dashed border-blue-400" />
                )}
                {renderChildren(node.id, depth + 1)}
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  // Orphan = not gateway, not connected via any edge
  const orphans = snap.nodes.filter((n) => !n.is_gateway && !connectedIds.has(n.id));

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-4 py-2 border-b border-border bg-muted/30 flex items-center gap-2">
        <DeviceHubIcon style={{ fontSize: 16, color: "#1a73e8" }} />
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
          Mesh Topology
        </h3>
        <span className="text-[10px] text-muted-foreground ml-1">
          {snap.device_count} devices
        </span>

        {/* Profile selector (shown only when multiple profiles exist) */}
        {profiles.length > 1 && (
          <div className="flex items-center gap-1.5 ml-2">
            <FilterListIcon style={{ fontSize: 14 }} className="text-muted-foreground" />
            <select
              value={selectedProfile}
              onChange={(e) => {
                setSelectedProfile(e.target.value);
                setSnapshotIdx(0);
              }}
              className="text-[11px] px-2 py-0.5 rounded border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 cursor-pointer"
            >
              <option value="all">All Profiles ({topology.total_snapshots})</option>
              {profiles.map((p) => {
                const count = topology.snapshots.filter((s) => s.profile === p).length;
                return (
                  <option key={p} value={p}>
                    {p} ({count})
                  </option>
                );
              })}
            </select>
          </div>
        )}

        <span className="ml-auto text-[10px] text-muted-foreground">
          Snapshot {snapshotIdx + 1} of {filteredSnapshots.length}
          {snap.profile && <span className="ml-1 font-medium">({snap.profile})</span>}
        </span>
      </div>

      {/* Time Slider */}
      {filteredSnapshots.length > 1 && (
        <div className="px-4 pt-3 pb-1 border-b border-border bg-muted/10">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSnapshotIdx((i) => Math.max(0, i - 1))}
              disabled={snapshotIdx === 0}
              className="p-0.5 rounded hover:bg-muted disabled:opacity-30 transition-colors"
            >
              <NavigateBeforeIcon style={{ fontSize: 18 }} />
            </button>
            <div className="flex-1 px-2">
              <Slider
                value={snapshotIdx}
                min={0}
                max={filteredSnapshots.length - 1}
                step={1}
                marks={sliderMarks}
                onChange={(_, v) => setSnapshotIdx(v as number)}
                valueLabelDisplay="auto"
                valueLabelFormat={(v) => {
                  const s = filteredSnapshots[v];
                  return s ? s.time.slice(0, 19).replace("T", " ") : "";
                }}
                size="small"
                sx={{
                  "& .MuiSlider-markLabel": { fontSize: "10px" },
                  "& .MuiSlider-thumb": { width: 14, height: 14 },
                }}
              />
            </div>
            <button
              onClick={() => setSnapshotIdx((i) => Math.min(filteredSnapshots.length - 1, i + 1))}
              disabled={snapshotIdx === filteredSnapshots.length - 1}
              className="p-0.5 rounded hover:bg-muted disabled:opacity-30 transition-colors"
            >
              <NavigateNextIcon style={{ fontSize: 18 }} />
            </button>
            <span className="text-[11px] text-muted-foreground font-mono whitespace-nowrap min-w-[140px] text-right">
              {snap.time.slice(0, 19).replace("T", " ")}
            </span>
          </div>
        </div>
      )}

      {/* Topology Graph */}
      <div className="p-4 overflow-x-auto">
        <div className="flex flex-col items-center min-w-[400px]">
          {/* Gateway node */}
          {gateway && <DeviceNodeCard node={gateway} />}

          {/* Vertical connector from gateway down to horizontal bar */}
          {gateway && (childMap.get(gateway.id)?.length ?? 0) > 0 && (
            <div className="w-0 h-4 border-l-2 border-dashed border-blue-400" />
          )}

          {/* Children of gateway */}
          {gateway && renderChildren(gateway.id, 1)}

          {/* Orphan extenders (not connected by any edge) */}
          {orphans.length > 0 && (
            <div className="mt-6 pt-4 border-t border-dashed border-gray-300 dark:border-gray-600 w-full">
              <p className="text-[10px] text-muted-foreground text-center mb-2 uppercase tracking-wider">
                Unconnected Devices ({orphans.length})
              </p>
              <div className="flex flex-wrap justify-center gap-4">
                {orphans.map((node) => (
                  <div key={node.id} className="flex flex-col items-center">
                    {/* Show available backhaul info even for orphans */}
                    {(node.backhaul_media_type || node.backhaul_phy_rate > 0) && (
                      <span className="text-[9px] text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-950/30 px-1.5 py-0.5 rounded mb-1 whitespace-nowrap border border-orange-200 dark:border-orange-800">
                        {node.backhaul_media_type.replace("IEEE ", "")} {node.backhaul_phy_rate > 0 ? `${node.backhaul_phy_rate}Mbps` : ""}
                        {node.backhaul_signal_strength ? <span className={` ml-1 font-bold ${signalColor(node.backhaul_signal_strength)}`}>{node.backhaul_signal_strength}dBm</span> : ""}
                        <span className="ml-1 text-orange-500">(no parent found)</span>
                      </span>
                    )}
                    <DeviceNodeCard node={node} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Check if model name indicates a Speed Home WLAN device */
function isSpeedHomeWlan(model: string): boolean {
  return model.toUpperCase().includes("SHWLAN");
}

function DeviceNodeCard({ node }: { node: TopoNode }) {
  const [showClients, setShowClients] = useState(false);
  const mem = memPercent(node.memory.free, node.memory.total);
  const bands = node.radios.map((r) => r.band).filter(Boolean);
  const totalClients = node.connected_clients;
  const isSHWLAN = !node.is_gateway && isSpeedHomeWlan(node.model);

  // Non-affiliated clients (real WiFi clients), sorted by standard then RSSI
  const stdOrder: Record<string, number> = { be: 0, ax: 1, ac: 2, n: 3 };
  const visibleClients = (node.clients ?? [])
    .filter((c) => !c.is_affiliated)
    .sort((a, b) => {
      const sa = stdOrder[a.operating_standard] ?? 9;
      const sb = stdOrder[b.operating_standard] ?? 9;
      if (sa !== sb) return sa - sb;
      const ra = parseFloat(a.signal_strength_dbm) || -999;
      const rb = parseFloat(b.signal_strength_dbm) || -999;
      return rb - ra; // stronger signal first
    });

  // Shape: circle for SHWLAN extenders, rounded-lg for gateway, rounded-lg for others
  const shapeClass = node.is_gateway
    ? "rounded-xl border-2 p-2.5 min-w-[160px] max-w-[200px] shadow-sm border-blue-400 bg-blue-50/80 dark:border-blue-600 dark:bg-blue-950/30"
    : isSHWLAN
      ? "rounded-full border-2 p-3 w-[148px] h-[148px] flex flex-col items-center justify-center shadow-sm border-green-400 bg-green-50/60 dark:border-green-600 dark:bg-green-950/30"
      : "rounded-xl border-2 p-2.5 min-w-[160px] max-w-[200px] shadow-sm border-gray-300 bg-white dark:border-gray-600 dark:bg-gray-900/50";

  return (
    <div className="flex flex-col items-center">
      <div className={`transition-all ${shapeClass}`}>
        {/* Header: icon + role */}
        <div className={`flex items-center gap-2 ${isSHWLAN ? "mb-0.5" : "mb-1.5"}`}>
          {node.is_gateway ? (
            <RouterIcon style={{ fontSize: 20 }} className="text-blue-600 dark:text-blue-400" />
          ) : isSHWLAN ? (
            <WifiIcon style={{ fontSize: 18 }} className="text-green-600 dark:text-green-400" />
          ) : (
            <SettingsInputAntennaIcon style={{ fontSize: 20 }} className="text-gray-600 dark:text-gray-400" />
          )}
          <div className="flex-1 min-w-0">
            <div className={`font-bold truncate ${isSHWLAN ? "text-[10px]" : "text-[11px]"}`}>
              {node.is_gateway ? "Gateway" : "Extender"}
            </div>
            <div className={`text-muted-foreground truncate ${isSHWLAN ? "text-[9px]" : "text-[10px]"}`} title={node.model}>
              {node.model || node.manufacturer || "Unknown"}
            </div>
          </div>
        </div>

        {/* ID */}
        <div className={`font-mono text-muted-foreground ${isSHWLAN ? "text-[8px] mb-0.5" : "text-[9px] mb-1.5"}`} title={node.id}>
          {node.id.toUpperCase()}
          {!isSHWLAN && node.serial_number && <div className="text-[8px]">SN: ...{node.serial_number.slice(-6)}</div>}
        </div>

        {/* Bands */}
        {bands.length > 0 && (
          <div className={`flex flex-wrap gap-1 ${isSHWLAN ? "justify-center mb-0.5" : "mb-1.5"}`}>
            {bands.map((b, i) => (
              <span key={i} className="text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400">
                {b}
              </span>
            ))}
          </div>
        )}

        {/* Stats row */}
        <div className={`flex items-center gap-2 text-[10px] text-muted-foreground flex-wrap ${isSHWLAN ? "justify-center" : ""}`}>
          {totalClients > 0 && (
            <span className="flex items-center gap-0.5" title="Connected clients">
              <WifiIcon style={{ fontSize: 11 }} /> {totalClients}
            </span>
          )}
          {node.cpu.usage && (
            <span className="flex items-center gap-0.5" title="CPU usage">
              <MemoryIcon style={{ fontSize: 11 }} /> {node.cpu.usage}%
            </span>
          )}
          {node.cpu.temperature && (
            <span className="flex items-center gap-0.5" title="CPU temperature">
              <ThermostatIcon style={{ fontSize: 11 }} /> {node.cpu.temperature}C
            </span>
          )}
          {mem !== null && (
            <span className="flex items-center gap-0.5" title={`Memory: ${node.memory.free}/${node.memory.total} KB free`}>
              <StorageIcon style={{ fontSize: 11 }} /> {mem}%
            </span>
          )}
        </div>

        {/* Software version */}
        {node.software_version && !isSHWLAN && (
          <div className="text-[9px] text-muted-foreground mt-1 truncate" title={node.software_version}>
            v{node.software_version}
          </div>
        )}
      </div>

      {/* Collapsible client toggle + panel (outside the shaped card) */}
      {visibleClients.length > 0 && (
        <div>
          <button
            onClick={() => setShowClients((v) => !v)}
            className="mt-1 w-full flex items-center justify-center gap-1 text-[9px] font-medium text-muted-foreground hover:text-foreground transition-colors py-0.5 rounded hover:bg-muted/40"
          >
            <DevicesIcon style={{ fontSize: 11 }} />
            {visibleClients.length} Client{visibleClients.length !== 1 ? "s" : ""}
            {showClients ? <ExpandLessIcon style={{ fontSize: 13 }} /> : <ExpandMoreIcon style={{ fontSize: 13 }} />}
          </button>
          {showClients && (
            <div className="mt-1 border border-border rounded-lg bg-card shadow-sm overflow-x-auto max-w-[380px]">
              <table className="w-full text-[9px] min-w-[340px]">
                <thead>
                  <tr className="bg-muted/40 text-muted-foreground">
                    <th className="px-1.5 py-1 text-left font-semibold">MAC</th>
                    <th className="px-1.5 py-1 text-left font-semibold">Std</th>
                    <th className="px-1.5 py-1 text-right font-semibold">PHY</th>
                    <th className="px-1.5 py-1 text-right font-semibold">RSSI</th>
                    <th className="px-1.5 py-1 text-right font-semibold">TX/RX</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleClients.map((c) => {
                    const badge = stdBadge(c.operating_standard);
                    return (
                      <tr key={c.mac} className="border-t border-border/50 hover:bg-muted/20">
                        <td className="px-1.5 py-0.5 font-mono whitespace-nowrap" title={c.mac}>
                          <MacBold mac={c.mac} />
                          {c.band && <span className="ml-0.5 text-muted-foreground">({c.band.replace("GHz", "G")})</span>}
                        </td>
                        <td className="px-1.5 py-0.5">
                          <span className={`inline-block px-1 py-0 rounded text-[8px] font-bold ${badge.bg} ${badge.text}`} title={badge.label}>
                            {c.operating_standard.toUpperCase()}
                          </span>
                        </td>
                        <td className="px-1.5 py-0.5 text-right whitespace-nowrap" title={`Max: ${formatRate(c.max_phy_rate)} | DL: ${formatRate(c.last_dl_rate)} | UL: ${formatRate(c.last_ul_rate)}`}>
                          {formatRate(c.max_phy_rate)}
                        </td>
                        <td className={`px-1.5 py-0.5 text-right font-bold whitespace-nowrap ${signalColor(c.signal_strength_dbm)}`}>
                          {c.signal_strength_dbm ? `${c.signal_strength_dbm}` : "—"}
                        </td>
                        <td className="px-1.5 py-0.5 text-right whitespace-nowrap text-muted-foreground" title={`TX: ${formatBytes(c.bytes_tx)} | RX: ${formatBytes(c.bytes_rx)} | Uptime: ${formatDuration(c.connect_time)}`}>
                          {formatBytes(c.bytes_tx)}/{formatBytes(c.bytes_rx)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ================================================================ All Extracted Fields Discovery */
function AvailableFieldsPanel({ fields, onClose }: { fields: AvailableFields; onClose: () => void }) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [showMode, setShowMode] = useState<"all" | "configured" | "unconfigured">("all");

  const toggle = (g: string) => setExpandedGroups((prev) => {
    const next = new Set(prev);
    next.has(g) ? next.delete(g) : next.add(g);
    return next;
  });

  const typeBadge = (t: string) => {
    if (t === "numeric") return "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400";
    if (t === "status") return "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400";
    if (t === "configured") return "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400";
    return "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400";
  };

  // Create configured fields in same format as unconfigured
  const configuredAsGroups = { "Configured Fields": fields.configured_keys.map(key => ({
    key,
    type: "configured",
    plottable: false,
    count: 1,
    samples: ["(configured)"]
  })) };

  // Combine all groups based on show mode
  const allGroups = showMode === "configured" ? configuredAsGroups :
                   showMode === "unconfigured" ? fields.unconfigured :
                   { ...configuredAsGroups, ...fields.unconfigured };

  const filterLower = filter.toLowerCase();
  const filteredGroups = Object.entries(allGroups)
    .map(([group, items]) => ({
      group,
      items: filterLower ? items.filter((f) => f.key.toLowerCase().includes(filterLower)) : items,
    }))
    .filter((g) => g.items.length > 0)
    .sort((a, b) => {
      // Sort "Configured Fields" first if present
      if (a.group === "Configured Fields") return -1;
      if (b.group === "Configured Fields") return 1;
      return b.items.length - a.items.length;
    });

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border bg-muted/30 flex items-center gap-2">
        <ExploreIcon style={{ fontSize: 16, color: "#1a73e8" }} />
        <h3 className="text-sm font-semibold flex-1">All Extracted Telemetry Fields</h3>
        <span className="text-[10px] text-muted-foreground">
          {fields.stats.configured} configured / {fields.stats.unconfigured} available / {fields.stats.total_fields} total
        </span>
        <button onClick={onClose} className="text-xs text-muted-foreground hover:text-foreground px-2 py-0.5 rounded border hover:bg-muted">
          Close
        </button>
      </div>

      <div className="px-4 py-2 border-b border-border space-y-2">
        {/* View Mode Toggle */}
        <div className="flex items-center gap-1">
          <span className="text-xs font-medium text-muted-foreground mr-2">View:</span>
          {[
            { key: "all", label: "All Fields" },
            { key: "configured", label: "Configured" },
            { key: "unconfigured", label: "Available" }
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setShowMode(key as any)}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                showMode === key
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted hover:bg-muted/80 text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        
        {/* Search Filter */}
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter fields... (e.g. WiFi, Ethernet, DSL, Temperature, meminfoavailable)"
          className="w-full px-3 py-1.5 text-sm rounded-lg border bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
      </div>

      <div className="max-h-[500px] overflow-y-auto divide-y divide-border">
        {filteredGroups.length === 0 && (
          <p className="text-sm text-muted-foreground p-4 text-center">
            {filterLower ? "No fields match the filter" : "All available fields are already configured"}
          </p>
        )}
        {filteredGroups.map(({ group, items }) => {
          const isOpen = expandedGroups.has(group);
          const numericCount = items.filter((f) => f.type === "numeric").length;
          const statusCount = items.filter((f) => f.type === "status").length;
          const configuredCount = items.filter((f) => f.type === "configured").length;
          return (
            <div key={group}>
              <button
                onClick={() => toggle(group)}
                className="w-full flex items-center gap-2 px-4 py-2 hover:bg-muted/50 transition-colors text-left"
              >
                {isOpen
                  ? <ExpandLessIcon style={{ fontSize: 16 }} />
                  : <ExpandMoreIcon style={{ fontSize: 16 }} />}
                <span className="text-sm font-medium flex-1">{group}</span>
                <span className="text-[10px] text-muted-foreground">{items.length} fields</span>
                {configuredCount > 0 && (
                  <span className="text-[10px] bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 rounded px-1.5 py-0.5">
                    {configuredCount} configured
                  </span>
                )}
                {numericCount > 0 && (
                  <span className="text-[10px] bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 rounded px-1.5 py-0.5">
                    {numericCount} plottable
                  </span>
                )}
                {statusCount > 0 && (
                  <span className="text-[10px] bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 rounded px-1.5 py-0.5">
                    {statusCount} status
                  </span>
                )}
              </button>
              {isOpen && (
                <div className="bg-muted/20 px-4 pb-2">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground">
                        <th className="text-left py-1 font-medium">TR-181 Key</th>
                        <th className="text-left py-1 font-medium w-16">Type</th>
                        <th className="text-center py-1 font-medium w-10">#</th>
                        <th className="text-left py-1 font-medium">Sample Values</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/50">
                      {items.map((f) => (
                        <tr key={f.key} className="hover:bg-muted/30">
                          <td className="py-1.5 font-mono text-[11px] break-all pr-2">{f.key}</td>
                          <td className="py-1.5">
                            <span className={`text-[10px] rounded px-1.5 py-0.5 font-medium ${typeBadge(f.type)}`}>
                              {f.type}
                            </span>
                          </td>
                          <td className="py-1.5 text-center text-muted-foreground">{f.count}</td>
                          <td className="py-1.5 text-muted-foreground max-w-[200px] truncate" title={f.samples.join(", ")}>
                            {f.samples.slice(0, 2).join(", ")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ================================================================ CSV Export Dialog */
function ExportDialog({
  availableProfiles,
  onClose,
  onExport,
  profileCounts,
  hasData,
}: {
  availableProfiles: string[];
  onClose: () => void;
  onExport: (profiles: string[], format: 'combined' | 'separate') => void;
  profileCounts?: Record<string, { parsed: number }>;
  hasData: boolean;
}) {
  // If no profiles available, default to exporting all (empty array means "all")
  const hasProfiles = availableProfiles.length > 0;
  const [selectedProfiles, setSelectedProfiles] = useState<Set<string>>(
    hasProfiles ? new Set(availableProfiles) : new Set()
  );
  // Default to 'separate' format for better organization
  const [format, setFormat] = useState<'combined' | 'separate'>('separate');

  const toggleProfile = (profile: string) => {
    setSelectedProfiles((prev) => {
      const next = new Set(prev);
      next.has(profile) ? next.delete(profile) : next.add(profile);
      return next;
    });
  };

  const handleExport = () => {
    // If no profiles exist (dcmscript case), pass empty array to export all
    if (!hasProfiles) {
      onExport([], format);
      return;
    }
    
    // If profiles exist but none selected, show error
    if (selectedProfiles.size === 0) {
      alert('Please select at least one profile to export');
      return;
    }
    
    onExport(Array.from(selectedProfiles), format);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-card border border-border rounded-xl w-full max-w-md mx-4 shadow-2xl">
        <div className="px-4 py-3 border-b border-border bg-muted/30 flex items-center gap-2">
          <DownloadIcon style={{ fontSize: 16, color: "#1a73e8" }} />
          <h3 className="text-sm font-semibold flex-1">Export Telemetry CSV</h3>
          <button onClick={onClose} className="text-xs text-muted-foreground hover:text-foreground px-2 py-0.5 rounded border hover:bg-muted">
            Close
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* Profile Selection - only show if profiles exist */}
          {hasProfiles ? (
            <div>
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 block">
                Select Profiles to Export
              </label>
              <div className="space-y-1.5">
                {availableProfiles.map((profile) => {
                  const count = profileCounts?.[profile]?.parsed || 0;
                  return (
                    <label
                      key={profile}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg border border-border hover:bg-muted/50 cursor-pointer transition-colors"
                    >
                      <input
                        type="checkbox"
                        checked={selectedProfiles.has(profile)}
                        onChange={() => toggleProfile(profile)}
                        className="w-4 h-4 rounded border-gray-300 text-primary focus:ring-primary"
                      />
                      <span className="text-sm font-medium flex-1">{profile}</span>
                      <span className="text-xs text-muted-foreground">
                        {count} report{count !== 1 ? 's' : ''}
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="px-3 py-2 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 text-xs">
              <p className="font-medium text-blue-800 dark:text-blue-400 mb-1">All Reports Selected</p>
              <p className="text-blue-600 dark:text-blue-300">
                This telemetry data doesn't have separate profiles. All reports will be exported together.
              </p>
            </div>
          )}

          {/* Format Selection - hide "separate" option if no profiles */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 block">
              Export Format
            </label>
            <div className="space-y-1.5">
              {hasProfiles && selectedProfiles.size > 0 && (
                <label className="flex items-center gap-2 px-3 py-2 rounded-lg border border-border hover:bg-muted/50 cursor-pointer transition-colors">
                  <input
                    type="radio"
                    name="format"
                    checked={format === 'separate'}
                    onChange={() => setFormat('separate')}
                    className="w-4 h-4 border-gray-300 text-primary focus:ring-primary"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-medium">Separate Files (Recommended)</div>
                    <div className="text-xs text-muted-foreground">
                      {selectedProfiles.size > 1 ? 'ZIP with one CSV per profile' : 'Single CSV file'}
                    </div>
                  </div>
                </label>
              )}
              <label className="flex items-center gap-2 px-3 py-2 rounded-lg border border-border hover:bg-muted/50 cursor-pointer transition-colors">
                <input
                  type="radio"
                  name="format"
                  checked={format === 'combined'}
                  onChange={() => setFormat('combined')}
                  className="w-4 h-4 border-gray-300 text-primary focus:ring-primary"
                />
                <div className="flex-1">
                  <div className="text-sm font-medium">
                    {hasProfiles ? 'Combined CSV' : 'CSV File'}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {hasProfiles ? 'Single file with Profile column' : 'Single CSV with all telemetry data'}
                  </div>
                </div>
              </label>
            </div>
          </div>

          {/* Export Summary */}
          <div className="px-3 py-2 rounded-lg bg-muted/30 border border-border text-xs">
            <p className="font-medium mb-1">Export Summary:</p>
            <p className="text-muted-foreground">
              {!hasProfiles && 'All telemetry reports (CSV)'}
              {hasProfiles && selectedProfiles.size === 0 && 'No profiles selected'}
              {hasProfiles && selectedProfiles.size === 1 && format === 'separate' && `1 profile → Single CSV`}
              {hasProfiles && selectedProfiles.size === 1 && format === 'combined' && `1 profile → CSV with Profile column`}
              {hasProfiles && selectedProfiles.size > 1 && format === 'separate' && `${selectedProfiles.size} profiles → ZIP with ${selectedProfiles.size} CSVs`}
              {hasProfiles && selectedProfiles.size > 1 && format === 'combined' && `${selectedProfiles.size} profiles → Combined CSV`}
            </p>
          </div>
        </div>

        <div className="px-4 py-3 border-t border-border bg-muted/20 flex items-center gap-2 justify-end">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-lg border hover:bg-muted transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleExport}
            disabled={!hasData || (hasProfiles && selectedProfiles.size === 0)}
            className="px-3 py-1.5 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
          >
            <DownloadIcon style={{ fontSize: 14 }} />
            Export
          </button>
        </div>
      </div>
    </div>
  );
}
