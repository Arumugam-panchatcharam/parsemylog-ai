import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { analyticsApi, type AnalyticsStaIssueGroup } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { cn, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { FullPageLoading } from "@/components/ui/Loading";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
// Using basic components and custom styling instead of advanced UI components
import AssessmentIcon from "@mui/icons-material/Assessment";
import DevicesIcon from "@mui/icons-material/Devices";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import ErrorIcon from "@mui/icons-material/Error";
import SignalWifiIcon from "@mui/icons-material/SignalWifi4Bar";
import RefreshIcon from "@mui/icons-material/Refresh";
import WifiTetheringIcon from "@mui/icons-material/WifiTethering";

/** Axios body from Flask: jsonify({ success, data }) */
interface AnalyticsEnvelope<T> {
  success: boolean;
  data?: T;
  error?: string;
}

interface FleetSummary {
  generation_date: string;
  fleet_statistics: {
    total_devices: number;
    devices_with_analytics?: number;
    total_reboots: number;
    average_reboots_per_device: number;
  };
  reboot_analysis: {
    reasons_distribution: Record<string, number>;
    most_common_reason: string;
  };
  firmware_analysis: {
    version_distribution: Record<string, number>;
    unique_versions: number;
  };
  error_analysis: {
    top_templates_by_domain: Record<string, Array<{ template: string; count: number }>>;
    total_error_instances: number;
  };
  device_health: {
    high_risk_devices: Array<{
      serial: string;
      model: string;
      firmware_version: string;
      peak_memory_pct: number;
      peak_cpu_pct: number;
    }>;
    high_risk_count: number;
  };
  module_graph_version: string;
}

interface DeviceHealth {
  device_serial: string;
  model: string;
  manufacturer: string;
  firmware_version: string;
  last_reboot_reason: string;
  peak_memory_usage_pct: number | null;
  avg_memory_usage_pct: number | null;
  peak_cpu_usage_pct: number | null;
  avg_cpu_usage_pct: number | null;
  processing_date: string;
  analytics_status?: "ready" | "pending";
}

interface ErrorTemplate {
  domain: string;
  template: string;
  occurrence_count: number;
  first_seen: string;
  last_seen: string;
  module_enrichment: string;
}

interface Signal {
  timestamp: string;
  signal_type: string;
  signal_value: number;
  processing_date: string;
}

interface RebootAnalysisPayload {
  reason_distribution: Array<{
    reason: string;
    count: number;
    avg_errors_before: number;
  }>;
  recent_reboots: Array<{
    timestamp: string;
    device_serial: string;
    reason: string;
    reboot_type: string;
    errors_before_reboot: number;
  }>;
  error?: string;
}

function AnalyticsPage() {
  const { projectId } = useProject();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<string>("overview");
  const [selectedDomain, setSelectedDomain] = useState<string>("");
  const [selectedSignalType, setSelectedSignalType] = useState<string>("");
  const [rebootSerialFilter, setRebootSerialFilter] = useState<string>("");
  /** Wi‑Fi STA tab: substring search (CPE serial or STA MAC hex) and issue type */
  const [staCpeSearch, setStaCpeSearch] = useState<string>("");
  const [staIssueSearch, setStaIssueSearch] = useState<string>("");

  const invalidateProjectAnalytics = () => {
    void queryClient.invalidateQueries({
      predicate: (q) =>
        Array.isArray(q.queryKey) &&
        q.queryKey[0] === "analytics" &&
        q.queryKey.includes(projectId),
    });
  };

  const regenerateFleetMutation = useMutation({
    mutationFn: async () => (await analyticsApi.regenerateFleet(projectId!)).data,
    onSettled: () => {
      invalidateProjectAnalytics();
    },
  });

  /** Full Polars ETL for every CPE with RG parquet (refreshes sta_issues, not only backfill). */
  const forcePolarsEtlMutation = useMutation({
    mutationFn: async () =>
      (await analyticsApi.regenerateFleet(projectId!, { force_polars_etl: true })).data,
    onSettled: () => {
      invalidateProjectAnalytics();
    },
  });

  // Fleet Summary Query
  const fleetQuery = useQuery({
    queryKey: ["analytics", "fleet-summary", projectId],
    queryFn: async () =>
      (await analyticsApi.getFleetSummary(projectId!)).data as unknown as AnalyticsEnvelope<FleetSummary>,
    enabled: !!projectId,
    refetchInterval: 30000, // Refresh every 30 seconds
  });

  // Device Health Query
  const deviceHealthQuery = useQuery({
    queryKey: ["analytics", "device-health", projectId],
    queryFn: async () =>
      (await analyticsApi.getDeviceHealth(projectId!)).data as unknown as AnalyticsEnvelope<DeviceHealth[]>,
    enabled: !!projectId,
  });

  // Error Templates Query
  const errorTemplatesQuery = useQuery({
    queryKey: ["analytics", "error-templates", projectId, selectedDomain],
    queryFn: async () =>
      (await analyticsApi.getErrorTemplates(projectId!, { domain: selectedDomain || undefined }))
        .data as unknown as AnalyticsEnvelope<ErrorTemplate[]>,
    enabled: !!projectId,
  });

  // Signals Query
  const signalsQuery = useQuery({
    queryKey: ["analytics", "signals", projectId, selectedSignalType],
    queryFn: async () =>
      (await analyticsApi.getSignals(projectId!, { signal_type: selectedSignalType || undefined }))
        .data as unknown as AnalyticsEnvelope<Signal[]>,
    enabled: !!projectId,
  });

  // Available Domains Query
  const domainsQuery = useQuery({
    queryKey: ["analytics", "domains", projectId],
    queryFn: async () =>
      (await analyticsApi.getDomains(projectId!)).data as unknown as AnalyticsEnvelope<{
        domains: string[];
        available_views: string[];
      }>,
    enabled: !!projectId,
  });

  // Signal Types Query
  const signalTypesQuery = useQuery({
    queryKey: ["analytics", "signal-types", projectId],
    queryFn: async () =>
      (await analyticsApi.getSignalTypes(projectId!)).data as unknown as AnalyticsEnvelope<{
        signal_types: string[];
      }>,
    enabled: !!projectId,
  });

  const rebootAnalysisQuery = useQuery({
    queryKey: ["analytics", "reboots", projectId, rebootSerialFilter],
    queryFn: async () =>
      (await analyticsApi.getRebootAnalysis(projectId!, {
        serial: rebootSerialFilter || undefined,
      })).data as unknown as AnalyticsEnvelope<RebootAnalysisPayload>,
    enabled: !!projectId,
  });

  const staIssuesGroupedQuery = useQuery({
    queryKey: ["analytics", "sta-issues-grouped", projectId],
    queryFn: async () =>
      (await analyticsApi.getStaIssuesGrouped(projectId!, {
        limit: 2000,
      })).data as unknown as AnalyticsEnvelope<AnalyticsStaIssueGroup[]>,
    enabled: !!projectId && activeTab === "wifi-sta",
  });

  const fleetData = fleetQuery.data?.data as FleetSummary | undefined;
  const deviceHealth = deviceHealthQuery.data?.data as DeviceHealth[] | undefined;
  const errorTemplates = errorTemplatesQuery.data?.data as ErrorTemplate[] | undefined;
  const signals = signalsQuery.data?.data as Signal[] | undefined;
  const domains = domainsQuery.data?.data?.domains as string[] | undefined;
  const signalTypes = signalTypesQuery.data?.data?.signal_types as string[] | undefined;
  const rebootAnalysis = rebootAnalysisQuery.data?.data as RebootAnalysisPayload | undefined;
  const staIssuesGrouped = staIssuesGroupedQuery.data?.data as AnalyticsStaIssueGroup[] | undefined;

  const staIssuesByDevice = useMemo(() => {
    const macHexOnly = (s: string) => s.toLowerCase().replace(/[^a-f0-9]/g, "");

    let rows = staIssuesGrouped ?? [];

    const issueQ = staIssueSearch.trim().toLowerCase();
    if (issueQ) {
      const issueUnderscore = issueQ.replace(/\s+/g, "_");
      rows = rows.filter((r) => {
        const key = (r.issue_key || "").toLowerCase();
        const keySpaced = key.replace(/_/g, " ");
        return (
          key.includes(issueUnderscore) ||
          keySpaced.includes(issueQ) ||
          key.includes(issueQ.replace(/\s/g, ""))
        );
      });
    }

    const m = new Map<string, AnalyticsStaIssueGroup[]>();
    for (const row of rows) {
      const serial = row.device_serial || "";
      if (!m.has(serial)) m.set(serial, []);
      m.get(serial)!.push(row);
    }

    let entries = Array.from(m.entries());

    const cpeQ = staCpeSearch.trim().toLowerCase();
    const cpeMacHex = macHexOnly(staCpeSearch);
    if (cpeQ || cpeMacHex.length >= 6) {
      entries = entries.filter(([serial, issues]) => {
        if (cpeQ && serial.toLowerCase().includes(cpeQ)) return true;
        if (cpeMacHex.length >= 6) {
          if (macHexOnly(serial).includes(cpeMacHex)) return true;
          for (const iss of issues) {
            for (const st of iss.sta_list) {
              if (macHexOnly(st.sta_mac).includes(cpeMacHex)) return true;
            }
          }
        }
        return false;
      });
    }

    entries.sort((a, b) => {
      const sumA = a[1].reduce((acc, x) => acc + (Number(x.total_occurrence_count) || 0), 0);
      const sumB = b[1].reduce((acc, x) => acc + (Number(x.total_occurrence_count) || 0), 0);
      if (sumB !== sumA) return sumB - sumA;
      if (b[1].length !== a[1].length) return b[1].length - a[1].length;
      return a[0].localeCompare(b[0]);
    });

    return entries.map(([serial, iss]) => {
      const sorted = [...iss].sort((x, y) => {
        const cx = Number(x.total_occurrence_count) || 0;
        const cy = Number(y.total_occurrence_count) || 0;
        if (cy !== cx) return cy - cx;
        return (x.issue_key || "").localeCompare(y.issue_key || "");
      });
      return [serial, sorted] as [string, AnalyticsStaIssueGroup[]];
    });
  }, [staIssuesGrouped, staCpeSearch, staIssueSearch]);

  if (!projectId) {
    return (
      <PageContainer>
        <div className="bg-white rounded-lg shadow p-8">
          <div className="flex flex-col items-center justify-center py-12">
            <AssessmentIcon className="text-6xl text-gray-400 mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No Project Selected</h3>
            <p className="text-gray-500 text-center max-w-md">
              Please select a project from the dashboard to view analytics data.
            </p>
          </div>
        </div>
      </PageContainer>
    );
  }

  if (fleetQuery.isLoading) {
    return <FullPageLoading />;
  }

  if (fleetQuery.error) {
    return (
      <PageContainer>
        <div className="text-red-600">
          Error loading analytics data: {String(fleetQuery.error)}
        </div>
      </PageContainer>
    );
  }

  if (
    !fleetData ||
    !fleetData.fleet_statistics ||
    ("error" in fleetData && (fleetData as { error?: string }).error)
  ) {
    return (
      <PageContainer>
        <div className="bg-white rounded-lg shadow p-8">
          <div className="flex flex-col items-center justify-center py-12">
            <AssessmentIcon className="text-6xl text-gray-400 mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No Analytics Data</h3>
            <p className="text-gray-500 text-center max-w-md">
              No analytics data is available for this project yet. 
              Analytics will be generated after CPE processing is complete.
            </p>
          </div>
        </div>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <AssessmentIcon className="!text-2xl" />
            CPE Analytics
          </span>
        }
        description="Fleet-level insights and performance analysis"
        actions={
          <Button
            variant="outline"
            size="sm"
            disabled={regenerateFleetMutation.isPending}
            onClick={() => regenerateFleetMutation.mutate()}
          >
            <RefreshIcon className="w-4 h-4 mr-1" />
            {regenerateFleetMutation.isPending ? "Refreshing…" : "Force refresh"}
          </Button>
        }
      />

      <div className="space-y-6">
        {fleetData.fleet_statistics.total_devices >
          (fleetData.fleet_statistics.devices_with_analytics ?? 0) && (
          <div
            className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950"
            role="status"
          >
            <span className="font-medium">Partial fleet analytics.</span>{" "}
            {fleetData.fleet_statistics.devices_with_analytics ?? 0} of{" "}
            {fleetData.fleet_statistics.total_devices} devices have per-CPE analytics written under{" "}
            <code className="rounded bg-amber-100/80 px-1">issue_analysis</code>. Use{" "}
            <strong>Force refresh</strong> to run Polars ETL for any device that already has
            processed logs (<code className="rounded bg-amber-100/80 px-1">*_rg.parquet</code>) but
            is missing analytics artifacts.
          </div>
        )}

        {/* Fleet Overview Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex flex-row items-center justify-between space-y-0 pb-2">
              <h3 className="text-sm font-medium">Total Devices</h3>
              <DevicesIcon className="h-4 w-4 text-gray-500" />
            </div>
            <div className="text-2xl font-bold">{fleetData.fleet_statistics.total_devices}</div>
            <p className="text-xs text-gray-500">
              CPEs with processed logs (<code className="text-[10px]">*_rg.parquet</code>)
              {fleetData.fleet_statistics.devices_with_analytics != null ? (
                <> · {fleetData.fleet_statistics.devices_with_analytics} with analytics Parquet</>
              ) : null}
            </p>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex flex-row items-center justify-between space-y-0 pb-2">
              <h3 className="text-sm font-medium">Total Reboots</h3>
              <RestartAltIcon className="h-4 w-4 text-gray-500" />
            </div>
            <div className="text-2xl font-bold">{fleetData.fleet_statistics.total_reboots}</div>
            <p className="text-xs text-gray-500">
              Avg: {fleetData.fleet_statistics.average_reboots_per_device.toFixed(1)} per device
            </p>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex flex-row items-center justify-between space-y-0 pb-2">
              <h3 className="text-sm font-medium">Error Instances</h3>
              <ErrorIcon className="h-4 w-4 text-gray-500" />
            </div>
            <div className="text-2xl font-bold">
              {fleetData.error_analysis.total_error_instances.toLocaleString()}
            </div>
            <p className="text-xs text-gray-500">
              Across all domains
            </p>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex flex-row items-center justify-between space-y-0 pb-2">
              <h3 className="text-sm font-medium">High Risk Devices</h3>
              <ErrorIcon className="h-4 w-4 text-red-500" />
            </div>
            <div className="text-2xl font-bold text-red-600">
              {fleetData.device_health.high_risk_count}
            </div>
            <p className="text-xs text-gray-500">
              Need attention
            </p>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="bg-white rounded-lg shadow">
          <div className="border-b border-gray-200">
            <nav className="-mb-px flex space-x-8 px-6" aria-label="Tabs">
              {[
                { id: "overview", name: "Fleet Overview" },
                { id: "devices", name: "Device Health" },
                { id: "reboots", name: "Reboot Analysis" },
                { id: "errors", name: "Error Templates" },
                { id: "wifi-sta", name: "WiFi STA issues" },
                { id: "signals", name: "Performance Signals" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    "whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium",
                    activeTab === tab.id
                      ? "border-blue-500 text-blue-600"
                      : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
                  )}
                >
                  {tab.name}
                </button>
              ))}
            </nav>
          </div>

          <div className="p-6">
            {activeTab === "overview" && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Reboot Reasons */}
                <div className="bg-gray-50 rounded-lg p-6">
                  <h3 className="text-lg font-medium mb-4">Reboot Reasons Distribution</h3>
                  <div className="space-y-3">
                    {Object.entries(fleetData.reboot_analysis.reasons_distribution)
                      .sort(([,a], [,b]) => b - a)
                      .slice(0, 5)
                      .map(([reason, count]) => (
                        <div key={reason} className="flex items-center justify-between">
                          <span className="text-sm font-medium">
                            {reason || "Unknown"}
                          </span>
                          <div className="flex items-center gap-2">
                            <div className="w-24 bg-gray-200 rounded-full h-2">
                              <div 
                                className="bg-blue-500 h-2 rounded-full" 
                                style={{ 
                                  width: `${(count / Math.max(...Object.values(fleetData.reboot_analysis.reasons_distribution))) * 100}%` 
                                }}
                              />
                            </div>
                            <span className="text-sm text-gray-600">{count}</span>
                          </div>
                        </div>
                      ))}
                  </div>
                </div>

                {/* Firmware Distribution */}
                <div className="bg-gray-50 rounded-lg p-6">
                  <h3 className="text-lg font-medium mb-4">Firmware Versions</h3>
                  <div className="space-y-3">
                    {Object.entries(fleetData.firmware_analysis.version_distribution)
                      .sort(([,a], [,b]) => b - a)
                      .slice(0, 5)
                      .map(([version, count]) => (
                        <div key={version} className="flex items-center justify-between">
                          <span className="text-sm font-mono">{version}</span>
                          <div className="flex items-center gap-2">
                            <div className="w-24 bg-gray-200 rounded-full h-2">
                              <div 
                                className="bg-green-500 h-2 rounded-full" 
                                style={{ 
                                  width: `${(count / Math.max(...Object.values(fleetData.firmware_analysis.version_distribution))) * 100}%` 
                                }}
                              />
                            </div>
                            <span className="text-sm text-gray-600">{count}</span>
                          </div>
                        </div>
                      ))}
                  </div>
                </div>
              </div>
            )}

            {activeTab === "devices" && (
              <div>
                <h3 className="text-lg font-medium mb-4">Device Health Overview</h3>
                {deviceHealthQuery.isLoading ? (
                  <div className="text-center py-8">Loading device health data...</div>
                ) : deviceHealth && deviceHealth.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Device
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Model
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Firmware
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Memory Peak
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            CPU Peak
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Last Reboot
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {deviceHealth.map((device, rowIndex) => {
                          const pending = device.analytics_status === "pending";
                          const mem = device.peak_memory_usage_pct;
                          const cpu = device.peak_cpu_usage_pct;
                          const rowKey = `${pending ? "p" : "r"}-${device.device_serial || "na"}-${rowIndex}`;
                          return (
                          <tr
                            key={rowKey}
                            className={cn("hover:bg-gray-50", pending && "bg-gray-50/80")}
                          >
                            <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                              <span className="inline-flex flex-col gap-0.5">
                                <span>{device.device_serial}</span>
                                {pending ? (
                                  <span className="text-xs font-normal text-amber-800 rounded px-1.5 py-0.5 bg-amber-100 w-fit">
                                    Analytics pending — use Force refresh
                                  </span>
                                ) : null}
                              </span>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                              {device.model}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-900">
                              {device.firmware_version}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                              {pending || mem == null ? (
                                <span className="text-gray-400">—</span>
                              ) : (
                                <div className="flex items-center">
                                  <div
                                    className={cn(
                                      "w-2 h-2 rounded-full mr-2",
                                      mem > 90
                                        ? "bg-red-500"
                                        : mem > 75
                                          ? "bg-yellow-500"
                                          : "bg-green-500",
                                    )}
                                  />
                                  {mem.toFixed(1)}%
                                </div>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                              {pending || cpu == null ? (
                                <span className="text-gray-400">—</span>
                              ) : (
                                <div className="flex items-center">
                                  <div
                                    className={cn(
                                      "w-2 h-2 rounded-full mr-2",
                                      cpu > 90
                                        ? "bg-red-500"
                                        : cpu > 75
                                          ? "bg-yellow-500"
                                          : "bg-green-500",
                                    )}
                                  />
                                  {cpu.toFixed(1)}%
                                </div>
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {pending ? "—" : device.last_reboot_reason || "Unknown"}
                            </td>
                          </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="text-center py-8 text-gray-500">
                    No device health data available
                  </div>
                )}
              </div>
            )}

            {activeTab === "reboots" && (
              <div className="space-y-6">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <h3 className="text-lg font-medium">Reboot analysis</h3>
                  <select
                    value={rebootSerialFilter}
                    onChange={(e) => setRebootSerialFilter(e.target.value)}
                    className="max-w-xs px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">All devices</option>
                    {(deviceHealth ?? []).map((d) => (
                      <option key={d.device_serial} value={d.device_serial}>
                        {d.device_serial}
                      </option>
                    ))}
                  </select>
                </div>
                {rebootAnalysisQuery.isLoading ? (
                  <div className="text-center py-8 text-gray-500">Loading reboot data…</div>
                ) : rebootAnalysis?.error ? (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                    {rebootAnalysis.error}
                  </div>
                ) : (
                  <>
                    <div>
                      <h4 className="text-sm font-medium text-gray-700 mb-2">By reason</h4>
                      {rebootAnalysis?.reason_distribution &&
                      rebootAnalysis.reason_distribution.length > 0 ? (
                        <div className="overflow-x-auto rounded-lg border border-gray-200">
                          <table className="min-w-full divide-y divide-gray-200 text-sm">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-2 text-left font-medium text-gray-600">Reason</th>
                                <th className="px-4 py-2 text-right font-medium text-gray-600">Count</th>
                                <th className="px-4 py-2 text-right font-medium text-gray-600">
                                  Avg errors before
                                </th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100 bg-white">
                              {rebootAnalysis.reason_distribution.map((row) => (
                                <tr key={row.reason || "__empty__"}>
                                  <td className="px-4 py-2 text-gray-900">
                                    {row.reason?.trim() ? row.reason : "—"}
                                  </td>
                                  <td className="px-4 py-2 text-right tabular-nums">{row.count}</td>
                                  <td className="px-4 py-2 text-right tabular-nums">
                                    {Number(row.avg_errors_before).toFixed(1)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <p className="text-sm text-gray-500">No reboot rows for this filter.</p>
                      )}
                    </div>
                    <div>
                      <h4 className="text-sm font-medium text-gray-700 mb-2">Recent reboots</h4>
                      {rebootAnalysis?.recent_reboots && rebootAnalysis.recent_reboots.length > 0 ? (
                        <div className="overflow-x-auto rounded-lg border border-gray-200">
                          <table className="min-w-full divide-y divide-gray-200 text-sm">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-2 text-left font-medium text-gray-600">Time</th>
                                <th className="px-4 py-2 text-left font-medium text-gray-600">Device</th>
                                <th className="px-4 py-2 text-left font-medium text-gray-600">Reason</th>
                                <th className="px-4 py-2 text-left font-medium text-gray-600">Type</th>
                                <th className="px-4 py-2 text-right font-medium text-gray-600">
                                  Errors before
                                </th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100 bg-white">
                              {rebootAnalysis.recent_reboots.map((r, i) => (
                                <tr key={`${r.device_serial}-${r.timestamp}-${i}`}>
                                  <td className="px-4 py-2 whitespace-nowrap text-gray-700">
                                    {formatDate(r.timestamp)}
                                  </td>
                                  <td className="px-4 py-2 font-mono text-xs text-gray-900">
                                    {r.device_serial}
                                  </td>
                                  <td className="px-4 py-2 text-gray-900">
                                    {r.reason?.trim() ? r.reason : "—"}
                                  </td>
                                  <td className="px-4 py-2 text-gray-600">{r.reboot_type || "—"}</td>
                                  <td className="px-4 py-2 text-right tabular-nums">
                                    {r.errors_before_reboot}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <p className="text-sm text-gray-500">No recent reboots for this filter.</p>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}

            {activeTab === "errors" && (
              <div>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-medium">Error Templates Analysis</h3>
                  <select 
                    value={selectedDomain} 
                    onChange={(e) => setSelectedDomain(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">All Domains</option>
                    {domains?.map((domain) => (
                      <option key={domain} value={domain}>
                        {domain}
                      </option>
                    ))}
                  </select>
                </div>
                {errorTemplatesQuery.isLoading ? (
                  <div className="text-center py-8">Loading error templates...</div>
                ) : errorTemplates && errorTemplates.length > 0 ? (
                  <div className="space-y-3 max-h-96 overflow-y-auto">
                    {errorTemplates.map((template, index) => (
                      <div key={index} className="border rounded-lg p-4">
                        <div className="flex items-center justify-between mb-2">
                          <span className="inline-block px-2 py-1 text-xs font-medium bg-gray-200 text-gray-800 rounded">
                            {template.domain}
                          </span>
                          <span className="text-sm text-gray-500">
                            {template.occurrence_count.toLocaleString()} occurrences
                          </span>
                        </div>
                        <p className="text-sm font-mono text-gray-800 mb-2">
                          {template.template}
                        </p>
                        <div className="flex items-center gap-4 text-xs text-gray-500">
                          <span>First: {formatDate(template.first_seen)}</span>
                          <span>Last: {formatDate(template.last_seen)}</span>
                          {template.module_enrichment && (
                            <span>Modules: {template.module_enrichment}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center py-8 text-gray-500">
                    No error templates found for selected filters
                  </div>
                )}
              </div>
            )}

            {activeTab === "wifi-sta" && (
              <div className="space-y-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h3 className="text-lg font-medium flex items-center gap-2">
                      <WifiTetheringIcon className="h-5 w-5 text-blue-600" />
                      WiFi STA protocol issues
                    </h3>
                    <p className="text-sm text-gray-500 mt-1 max-w-3xl">
                      Issues grouped by CPE and issue type; expand an issue to see STA MACs with{" "}
                      <strong>local OUI</strong> vendor labels. <strong>Near reboot</strong> means the issue
                      time window overlaps a device reboot (± window) so events such as deauth may be radio
                      reset noise rather than client-specific. Use <strong>Re-run Polars ETL</strong> to
                      refresh <code className="text-xs bg-gray-100 px-1 rounded">sta_issues.parquet</code>.
                    </p>
                  </div>
                  <div className="flex flex-col items-stretch sm:items-end gap-1 shrink-0">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={forcePolarsEtlMutation.isPending}
                      onClick={() => forcePolarsEtlMutation.mutate()}
                    >
                      <RefreshIcon className="w-4 h-4 mr-1" />
                      {forcePolarsEtlMutation.isPending ? "Re-running ETL…" : "Re-run Polars ETL"}
                    </Button>
                    <span className="text-xs text-gray-500 text-right max-w-[14rem]">
                      Recomputes consolidated Parquet (including STA issues) for every device with RG output.
                    </span>
                  </div>
                </div>
                {forcePolarsEtlMutation.isError ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
                    {String(forcePolarsEtlMutation.error)}
                  </div>
                ) : null}
                {forcePolarsEtlMutation.isSuccess &&
                forcePolarsEtlMutation.data &&
                typeof forcePolarsEtlMutation.data === "object" &&
                "backfill" in forcePolarsEtlMutation.data &&
                forcePolarsEtlMutation.data.backfill ? (
                  <div
                    className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-950"
                    role="status"
                  >
                    Polars ETL completed:{" "}
                    <span className="font-medium tabular-nums">
                      {Number(forcePolarsEtlMutation.data.backfill.backfilled_count ?? 0)}
                    </span>{" "}
                    device(s) processed
                    {Number(forcePolarsEtlMutation.data.backfill.failed_count ?? 0) > 0 ? (
                      <>
                        ,{" "}
                        <span className="font-medium text-red-800 tabular-nums">
                          {Number(forcePolarsEtlMutation.data.backfill.failed_count)} failed
                        </span>
                      </>
                    ) : null}
                    .
                  </div>
                ) : null}
                <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
                  <label className="flex flex-col gap-1 min-w-[14rem] flex-1 max-w-md">
                    <span className="text-xs font-medium text-gray-600">CPE serial or STA MAC</span>
                    <input
                      type="search"
                      value={staCpeSearch}
                      onChange={(e) => setStaCpeSearch(e.target.value)}
                      placeholder="e.g. 901A… or 34:3e:a4…"
                      autoComplete="off"
                      className="px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                      aria-label="Search by CPE serial or STA MAC"
                    />
                  </label>
                  <label className="flex flex-col gap-1 min-w-[12rem] flex-1 max-w-md">
                    <span className="text-xs font-medium text-gray-600">Issue type</span>
                    <input
                      type="search"
                      value={staIssueSearch}
                      onChange={(e) => setStaIssueSearch(e.target.value)}
                      placeholder="e.g. deauth, assoc loop…"
                      autoComplete="off"
                      className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      aria-label="Search by issue type"
                    />
                  </label>
                </div>
                <p className="text-xs text-gray-500">
                  CPEs are sorted by total issue activity (highest first). Search is case-insensitive; STA MAC
                  match uses hex digits (colons optional).
                </p>
                {staIssuesGroupedQuery.isLoading ? (
                  <div className="text-center py-8 text-gray-500">Loading STA issues…</div>
                ) : staIssuesGroupedQuery.isError ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
                    {String(staIssuesGroupedQuery.error)}
                  </div>
                ) : staIssuesGrouped && staIssuesGrouped.length > 0 && staIssuesByDevice.length === 0 ? (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
                    No issue groups match your search. Clear the filters or try a shorter MAC prefix (at least 6
                    hex digits).
                  </div>
                ) : staIssuesGrouped && staIssuesGrouped.length > 0 ? (
                  <div className="space-y-4">
                    {staIssuesByDevice.map(([deviceSerial, issues]) => {
                      const deviceIssueSum = issues.reduce(
                        (acc, x) => acc + (Number(x.total_occurrence_count) || 0),
                        0,
                      );
                      return (
                      <div
                        key={deviceSerial}
                        className="rounded-lg border border-gray-200 bg-white overflow-hidden"
                      >
                        <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 flex flex-wrap items-baseline justify-between gap-2">
                          <div>
                            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                              Device
                            </span>
                            <div className="font-mono text-sm text-gray-900">{deviceSerial}</div>
                          </div>
                          <span className="text-xs text-gray-600 tabular-nums">
                            {issues.length} issue type{issues.length === 1 ? "" : "s"} · {deviceIssueSum}{" "}
                            event{deviceIssueSum === 1 ? "" : "s"}
                          </span>
                        </div>
                        <ul className="divide-y divide-gray-100">
                          {issues.map((issue) => {
                            const sev = (issue.severity || "").toLowerCase();
                            const sevClass =
                              sev === "high"
                                ? "bg-red-100 text-red-900"
                                : sev === "medium"
                                  ? "bg-amber-100 text-amber-900"
                                  : "bg-gray-100 text-gray-800";
                            return (
                              <li key={`${issue.device_serial}-${issue.issue_key}`}>
                                <details className="group px-3 py-2">
                                  <summary className="cursor-pointer list-none flex flex-wrap items-center gap-2 py-1 [&::-webkit-details-marker]:hidden">
                                    <span
                                      className={cn(
                                        "inline-block rounded px-2 py-0.5 text-xs font-medium capitalize shrink-0",
                                        sevClass,
                                      )}
                                    >
                                      {issue.severity || "—"}
                                    </span>
                                    <span className="font-mono text-sm text-gray-900">
                                      {issue.issue_key.replace(/_/g, " ")}
                                    </span>
                                    <span className="text-xs text-gray-500 tabular-nums">
                                      {issue.sta_count} STA{issue.sta_count === 1 ? "" : "s"}
                                    </span>
                                    {issue.may_overlap_reboot ? (
                                      <span
                                        className="text-xs font-medium text-amber-800 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5"
                                        title={
                                          issue.overlapping_reboot_times?.length
                                            ? `Reboot times (UTC): ${issue.overlapping_reboot_times.join(", ")}`
                                            : "Issue window overlaps reboot margin"
                                        }
                                      >
                                        Near reboot
                                      </span>
                                    ) : null}
                                  </summary>
                                  <ul className="mt-2 mb-1 pl-2 border-l-2 border-gray-200 space-y-1.5">
                                    {issue.sta_list.map((s) => (
                                      <li
                                        key={s.sta_mac}
                                        className="text-xs font-mono text-gray-800 flex flex-wrap gap-x-2 gap-y-0.5"
                                      >
                                        <span>{s.sta_mac}</span>
                                        {s.vendor ? (
                                          <span className="text-gray-600 font-sans">{s.vendor}</span>
                                        ) : (
                                          <span className="text-gray-400 font-sans">—</span>
                                        )}
                                      </li>
                                    ))}
                                  </ul>
                                </details>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                      );
                    })}
                    <p className="text-xs text-gray-500">
                      Showing {staIssuesByDevice.length} device
                      {staIssuesByDevice.length === 1 ? "" : "s"} (
                      {staIssuesByDevice.reduce((n, [, iss]) => n + iss.length, 0)} issue groups) from{" "}
                      {staIssuesGrouped.length} loaded (max 2000). Vendors from local{" "}
                      <code className="bg-gray-100 px-1 rounded">oui.txt</code> only.
                    </p>
                  </div>
                ) : (
                  <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-600 space-y-4">
                    <p>
                      No STA protocol issues found for this project. If you recently added WiFi analytics, run
                      a full Polars ETL so{" "}
                      <code className="text-xs bg-white px-1 rounded">sta_issues.parquet</code> is
                      regenerated for every CPE with{" "}
                      <code className="text-xs bg-white px-1 rounded">*_rg.parquet</code>.
                    </p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={forcePolarsEtlMutation.isPending}
                      onClick={() => forcePolarsEtlMutation.mutate()}
                    >
                      <RefreshIcon className="w-4 h-4 mr-1" />
                      {forcePolarsEtlMutation.isPending ? "Re-running ETL…" : "Re-run Polars ETL"}
                    </Button>
                  </div>
                )}
              </div>
            )}

            {activeTab === "signals" && (
              <div>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-medium">Performance Signals</h3>
                  <select 
                    value={selectedSignalType} 
                    onChange={(e) => setSelectedSignalType(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">All Signal Types</option>
                    {signalTypes?.map((type) => (
                      <option key={type} value={type}>
                        {type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                      </option>
                    ))}
                  </select>
                </div>
                {signalsQuery.isLoading ? (
                  <div className="text-center py-8">Loading performance signals...</div>
                ) : signals && signals.length > 0 ? (
                  <div className="space-y-3 max-h-96 overflow-y-auto">
                    {signals.slice(0, 100).map((signal, index) => (
                      <div key={index} className="flex items-center justify-between border-b pb-2">
                        <div className="flex items-center gap-3">
                          <SignalWifiIcon className="w-4 h-4 text-blue-500" />
                          <span className="text-sm font-medium">
                            {signal.signal_type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-mono">
                            {signal.signal_value.toFixed(2)}
                          </span>
                          <span className="text-xs text-gray-500">
                            {formatDate(signal.timestamp)}
                          </span>
                        </div>
                      </div>
                    ))}
                    {signals.length > 100 && (
                      <div className="text-center text-sm text-gray-500 pt-2">
                        Showing first 100 of {signals.length.toLocaleString()} signals
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-center py-8 text-gray-500">
                    No performance signals found for selected filters
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </PageContainer>
  );
}

export default AnalyticsPage;