import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  analyticsApi,
  type AnalyticsSelfHealInsight,
  type AnalyticsStaIssueGroup,
} from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { FullPageLoading } from "@/components/ui/Loading";
import { PageHeader } from "@/components/ui/PageHeader";

/** Match Syslog/Telemetry: full content width (no max-w-7xl). */
const ANALYTICS_LAYOUT_CLASS =
  "p-4 space-y-6 w-full max-w-full min-w-0 overflow-y-auto sm:p-6";
import AssessmentIcon from "@mui/icons-material/Assessment";
import DevicesIcon from "@mui/icons-material/Devices";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import RefreshIcon from "@mui/icons-material/Refresh";
import WifiTetheringIcon from "@mui/icons-material/WifiTethering";
import TroubleshootIcon from "@mui/icons-material/Troubleshoot";

/** Axios body from Flask: jsonify({ success, data }) */
interface AnalyticsEnvelope<T> {
  success: boolean;
  data?: T;
  error?: string;
}

const SELFHEAL_TAG_LABELS: Record<string, string> = {
  high_cpu: "High CPU",
  application_restarting: "Process restarting (PID churn)",
  leakage: "RSS leakage",
  slab_unreclaim: "SUnreclaim / slab pressure",
  overcommit_risk: "Overcommit risk",
};

const RESTART_LINE_RE = /^(.+?) process restarting/;
const LEAK_LINE_RE = /^(.+?) process leaking/;

/** IEEE 802 U/L bit: second-least-significant bit of first octet set → locally administered (LAA). */
function isLocallyAdministeredStaMac(macRaw: string): boolean {
  const hex = macRaw.replace(/[^a-fA-F0-9]/g, "");
  if (hex.length < 2) return false;
  const first = Number.parseInt(hex.slice(0, 2), 16);
  if (Number.isNaN(first)) return false;
  return (first & 0x02) !== 0;
}

function aggregateSelfHealDetailProcesses(
  insights: AnalyticsSelfHealInsight[],
  tag: string,
  lineRe: RegExp,
): Array<{ name: string; mentions: number }> {
  const m = new Map<string, number>();
  for (const row of insights) {
    if (!(row.tags || []).includes(tag)) continue;
    for (const line of row.detail_lines || []) {
      const mm = line.match(lineRe);
      if (mm?.[1]) {
        const name = mm[1].trim();
        if (name) m.set(name, (m.get(name) || 0) + 1);
      }
    }
  }
  return [...m.entries()]
    .map(([name, mentions]) => ({ name, mentions }))
    .sort((a, b) => b.mentions - a.mentions)
    .slice(0, 12);
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
  module_graph_version: string;
}

function AnalyticsPage() {
  const { projectId } = useProject();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<"overview" | "wifi-sta" | "self-heal">("overview");
  /** Shared CPE serial filter for both WiFi STA and SelfHeal lists (substring match on serial). */
  const [fleetSignalsCpeSearch, setFleetSignalsCpeSearch] = useState<string>("");
  /** Wi‑Fi STA: substring search on issue type */
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

  const forcePolarsEtlMutation = useMutation({
    mutationFn: async () =>
      (await analyticsApi.regenerateFleet(projectId!, { force_polars_etl: true })).data,
    onSettled: () => {
      invalidateProjectAnalytics();
    },
  });

  const fleetQuery = useQuery({
    queryKey: ["analytics", "fleet-summary", projectId],
    queryFn: async () =>
      (await analyticsApi.getFleetSummary(projectId!)).data as unknown as AnalyticsEnvelope<FleetSummary>,
    enabled: !!projectId,
    refetchInterval: 30000,
  });

  const staIssuesGroupedQuery = useQuery({
    queryKey: ["analytics", "sta-issues-grouped", projectId],
    queryFn: async () =>
      (await analyticsApi.getStaIssuesGrouped(projectId!, {
        limit: 2000,
      })).data as unknown as AnalyticsEnvelope<AnalyticsStaIssueGroup[]>,
    enabled: !!projectId,
  });

  const selfHealInsightsQuery = useQuery({
    queryKey: ["analytics", "selfheal-insights", projectId],
    queryFn: async () =>
      (await analyticsApi.getSelfHealInsights(projectId!, { limit: 2000 })).data as unknown as AnalyticsEnvelope<
        AnalyticsSelfHealInsight[]
      >,
    enabled: !!projectId,
  });

  const fleetData = fleetQuery.data?.data as FleetSummary | undefined;
  const staIssuesGrouped = staIssuesGroupedQuery.data?.data as AnalyticsStaIssueGroup[] | undefined;
  const selfHealInsights = selfHealInsightsQuery.data?.data as AnalyticsSelfHealInsight[] | undefined;

  const cpeSerialFilter = fleetSignalsCpeSearch.trim().toLowerCase();

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

    const cpeMacHex = macHexOnly(fleetSignalsCpeSearch);
    if (cpeSerialFilter || cpeMacHex.length >= 6) {
      entries = entries.filter(([serial, issues]) => {
        if (cpeSerialFilter && serial.toLowerCase().includes(cpeSerialFilter)) return true;
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
  }, [staIssuesGrouped, fleetSignalsCpeSearch, cpeSerialFilter, staIssueSearch]);

  const selfHealFiltered = useMemo(() => {
    let rows = selfHealInsights ?? [];
    if (cpeSerialFilter) {
      rows = rows.filter((r) => (r.device_serial || "").toLowerCase().includes(cpeSerialFilter));
    }
    return [...rows].sort((a, b) => {
      const rank = (s: string) => (s.toLowerCase() === "high" ? 0 : s.toLowerCase() === "medium" ? 1 : 2);
      const d = rank(a.severity || "") - rank(b.severity || "");
      if (d !== 0) return d;
      return (b.tags?.length || 0) - (a.tags?.length || 0);
    });
  }, [selfHealInsights, cpeSerialFilter]);

  const staSignalCpeCount = useMemo(() => {
    const s = new Set<string>();
    for (const row of staIssuesGrouped ?? []) {
      const serial = (row.device_serial || "").trim();
      if (serial) s.add(serial);
    }
    return s.size;
  }, [staIssuesGrouped]);

  const selfHealSignalCpeCount = useMemo(() => {
    const s = new Set<string>();
    for (const row of selfHealInsights ?? []) {
      const serial = (row.device_serial || "").trim();
      if (serial) s.add(serial);
    }
    return s.size;
  }, [selfHealInsights]);

  /** Fleet-wide WiFi STA aggregates for overview cards (not filtered by CPE search). */
  const fleetWifiStaSummary = useMemo(() => {
    const rows = staIssuesGrouped ?? [];
    const issueTotals = new Map<string, number>();
    const uniqueMacs = new Set<string>();
    type StaAgg = {
      total: number;
      byIssue: Map<string, number>;
      displayMac: string;
      vendor: string | null;
      isLaa: boolean;
    };
    const staAgg = new Map<string, StaAgg>();

    const bumpSta = (
      macRaw: string,
      issueKey: string,
      add: number,
      vendor: string | null | undefined,
    ) => {
      const trimmed = macRaw.trim();
      const mac = trimmed.toLowerCase();
      if (!mac) return;
      uniqueMacs.add(mac);
      if (!staAgg.has(mac)) {
        staAgg.set(mac, {
          total: 0,
          byIssue: new Map(),
          displayMac: trimmed || mac,
          vendor: vendor?.trim() || null,
          isLaa: isLocallyAdministeredStaMac(trimmed || macRaw),
        });
      }
      const e = staAgg.get(mac)!;
      e.total += add;
      e.byIssue.set(issueKey, (e.byIssue.get(issueKey) || 0) + add);
      if (!e.vendor && vendor?.trim()) e.vendor = vendor.trim();
    };

    for (const g of rows) {
      const key = g.issue_key || "unknown";
      const occ = Number(g.total_occurrence_count) || 0;
      issueTotals.set(key, (issueTotals.get(key) || 0) + occ);
      const list = g.sta_list || [];
      const n = list.length || 1;
      const perSta = occ / n;
      for (const st of list) {
        bumpSta(st.sta_mac, key, perSta, st.vendor);
      }
    }

    const issueDistribution = [...issueTotals.entries()]
      .map(([issue_key, count]) => ({ issue_key, count }))
      .sort((a, b) => b.count - a.count);

    const laaCount = [...staAgg.values()].filter((v) => v.isLaa).length;

    const topStas = [...staAgg.entries()]
      .map(([mac, agg]) => {
        const issues = [...agg.byIssue.entries()]
          .map(([issue_key, v]) => ({ issue_key, count: v }))
          .sort((a, b) => b.count - a.count);
        return {
          mac,
          displayMac: agg.displayMac,
          vendor: agg.vendor,
          isLaa: agg.isLaa,
          total: agg.total,
          issues,
        };
      })
      .sort((a, b) => b.total - a.total)
      .slice(0, 8);

    return {
      issueDistribution,
      uniqueStaCount: uniqueMacs.size,
      laaStaCount: laaCount,
      topStas,
    };
  }, [staIssuesGrouped]);

  /** Fleet-wide SelfHeal tag + process aggregates for overview. */
  const fleetSelfHealSummary = useMemo(() => {
    const insights = selfHealInsights ?? [];
    const tagCounts = new Map<string, number>();
    for (const row of insights) {
      for (const t of row.tags || []) {
        if (!t) continue;
        tagCounts.set(t, (tagCounts.get(t) || 0) + 1);
      }
    }
    const tagDistribution = [...tagCounts.entries()]
      .map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => b.count - a.count);

    const restartingProcesses = aggregateSelfHealDetailProcesses(
      insights,
      "application_restarting",
      RESTART_LINE_RE,
    );
    const leakingProcesses = aggregateSelfHealDetailProcesses(insights, "leakage", LEAK_LINE_RE);

    return { tagDistribution, restartingProcesses, leakingProcesses };
  }, [selfHealInsights]);

  const renderSignalsEtlBanner = () => (
    <div className="border-b border-border px-6 py-4">
      <h2 className="text-lg font-medium text-foreground">Polars ETL &amp; signal extracts</h2>
      <p className="text-sm text-muted-foreground mt-1 max-w-4xl">
        Refreshes <code className="text-xs bg-muted px-1 rounded">sta_issues.parquet</code> and{" "}
        <code className="text-xs bg-muted px-1 rounded">selfheal_insights.parquet</code> for devices with
        RG output.
      </p>
      <div className="mt-3 flex flex-col sm:flex-row sm:items-center gap-2">
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
        <span className="text-xs text-muted-foreground">
          Recomputes consolidated Parquet for every device with RG output.
        </span>
      </div>
      {forcePolarsEtlMutation.isError ? (
        <div className="mt-3 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {String(forcePolarsEtlMutation.error)}
        </div>
      ) : null}
      {forcePolarsEtlMutation.isSuccess &&
      forcePolarsEtlMutation.data &&
      typeof forcePolarsEtlMutation.data === "object" &&
      "backfill" in forcePolarsEtlMutation.data &&
      forcePolarsEtlMutation.data.backfill ? (
        <div
          className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-900 dark:text-emerald-100"
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
              <span className="font-medium text-destructive tabular-nums">
                {Number(forcePolarsEtlMutation.data.backfill.failed_count)} failed
              </span>
            </>
          ) : null}
          .
        </div>
      ) : null}
    </div>
  );

  if (!projectId) {
    return (
      <div className={ANALYTICS_LAYOUT_CLASS}>
        <div className="bg-card rounded-lg border border-border shadow-sm p-8">
          <div className="flex flex-col items-center justify-center py-12">
            <AssessmentIcon className="text-6xl text-muted-foreground/70 mb-4" />
            <h3 className="text-lg font-medium text-foreground mb-2">No Project Selected</h3>
            <p className="text-muted-foreground text-center max-w-md">
              Please select a project from the dashboard to view analytics data.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (fleetQuery.isLoading) {
    return <FullPageLoading />;
  }

  if (fleetQuery.error) {
    return (
      <div className={ANALYTICS_LAYOUT_CLASS}>
        <div className="text-destructive">
          Error loading analytics data: {String(fleetQuery.error)}
        </div>
      </div>
    );
  }

  if (
    !fleetData ||
    !fleetData.fleet_statistics ||
    ("error" in fleetData && (fleetData as { error?: string }).error)
  ) {
    return (
      <div className={ANALYTICS_LAYOUT_CLASS}>
        <div className="bg-card rounded-lg border border-border shadow-sm p-8">
          <div className="flex flex-col items-center justify-center py-12">
            <AssessmentIcon className="text-6xl text-muted-foreground/70 mb-4" />
            <h3 className="text-lg font-medium text-foreground mb-2">No Analytics Data</h3>
            <p className="text-muted-foreground text-center max-w-md">
              No analytics data is available for this project yet. Analytics will be generated after CPE
              processing is complete.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={ANALYTICS_LAYOUT_CLASS}>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <AssessmentIcon className="!text-2xl" />
            CPE Analytics
          </span>
        }
        description="Fleet overview, WiFi STA detail, and SelfHeal detail"
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
            className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-sm text-amber-950 dark:text-amber-100"
            role="status"
          >
            <span className="font-medium">Partial fleet analytics.</span>{" "}
            {fleetData.fleet_statistics.devices_with_analytics ?? 0} of{" "}
            {fleetData.fleet_statistics.total_devices} devices have per-CPE analytics written under{" "}
            <code className="rounded bg-amber-500/15 dark:bg-amber-500/20 px-1">issue_analysis</code>. Use{" "}
            <strong>Force refresh</strong> to run Polars ETL for any device that already has processed logs (
            <code className="rounded bg-amber-500/15 dark:bg-amber-500/20 px-1">*_rg.parquet</code>) but is missing analytics
            artifacts.
          </div>
        )}

        <div
          className="flex flex-wrap gap-1 border-b border-border"
          role="tablist"
          aria-label="Analytics sections"
        >
          {(
            [
              ["overview", "Overview"],
              ["wifi-sta", "WiFi STA"],
              ["self-heal", "SelfHeal"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={activeTab === id}
              onClick={() => setActiveTab(id)}
              className={cn(
                "px-4 py-2.5 text-sm font-medium rounded-t-md border border-b-0 -mb-px transition-colors",
                activeTab === id
                  ? "bg-card border-border text-primary z-[1]"
                  : "bg-muted/40 border-transparent text-muted-foreground hover:text-foreground hover:bg-muted",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {activeTab === "overview" ? (
          <>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-card rounded-lg border border-border shadow-sm p-6">
            <div className="flex flex-row items-center justify-between space-y-0 pb-2">
              <h3 className="text-sm font-medium">Total Devices</h3>
              <DevicesIcon className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="text-2xl font-bold">{fleetData.fleet_statistics.total_devices}</div>
            <p className="text-xs text-muted-foreground">
              CPEs with processed logs (<code className="text-[10px]">*_rg.parquet</code>)
              {fleetData.fleet_statistics.devices_with_analytics != null ? (
                <> · {fleetData.fleet_statistics.devices_with_analytics} with analytics Parquet</>
              ) : null}
            </p>
          </div>

          <div className="bg-card rounded-lg border border-border shadow-sm p-6">
            <div className="flex flex-row items-center justify-between space-y-0 pb-2">
              <h3 className="text-sm font-medium">Total Reboots</h3>
              <RestartAltIcon className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="text-2xl font-bold">{fleetData.fleet_statistics.total_reboots}</div>
            <p className="text-xs text-muted-foreground">
              Avg: {fleetData.fleet_statistics.average_reboots_per_device.toFixed(1)} per device
            </p>
          </div>

          <div className="bg-card rounded-lg border border-border shadow-sm p-6">
            <div className="flex flex-row items-center justify-between space-y-0 pb-2">
              <h3 className="text-sm font-medium">WiFi STA signals</h3>
              <WifiTetheringIcon className="h-4 w-4 text-primary" />
            </div>
            <div className="text-2xl font-bold">{staSignalCpeCount}</div>
            <p className="text-xs text-muted-foreground">CPEs with STA protocol issue groups</p>
          </div>

          <div className="bg-card rounded-lg border border-border shadow-sm p-6">
            <div className="flex flex-row items-center justify-between space-y-0 pb-2">
              <h3 className="text-sm font-medium">SelfHeal signals</h3>
              <TroubleshootIcon className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="text-2xl font-bold">{selfHealSignalCpeCount}</div>
            <p className="text-xs text-muted-foreground">CPEs with SelfHeal insight rows</p>
          </div>
        </div>

        <div className="bg-card rounded-lg border border-border shadow-sm p-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-muted/50 rounded-lg p-6">
              <h3 className="text-lg font-medium mb-4">Reboot Reasons Distribution</h3>
              <div className="space-y-3">
                {Object.entries(fleetData.reboot_analysis.reasons_distribution)
                  .sort(([, a], [, b]) => b - a)
                  .slice(0, 5)
                  .map(([reason, count]) => (
                    <div key={reason} className="flex items-center justify-between">
                      <span className="text-sm font-medium">{reason || "Unknown"}</span>
                      <div className="flex items-center gap-2">
                        <div className="w-24 bg-muted rounded-full h-2">
                          <div
                            className="bg-primary h-2 rounded-full"
                            style={{
                              width: `${(count / Math.max(...Object.values(fleetData.reboot_analysis.reasons_distribution))) * 100}%`,
                            }}
                          />
                        </div>
                        <span className="text-sm text-muted-foreground">{count}</span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>

            <div className="bg-muted/50 rounded-lg p-6">
              <h3 className="text-lg font-medium mb-4">Firmware Versions</h3>
              <div className="space-y-3">
                {Object.entries(fleetData.firmware_analysis.version_distribution)
                  .sort(([, a], [, b]) => b - a)
                  .slice(0, 5)
                  .map(([version, count]) => (
                    <div key={version} className="flex items-center justify-between">
                      <span className="text-sm font-mono">{version}</span>
                      <div className="flex items-center gap-2">
                        <div className="w-24 bg-muted rounded-full h-2">
                          <div
                            className="bg-emerald-600 dark:bg-emerald-500 h-2 rounded-full"
                            style={{
                              width: `${(count / Math.max(...Object.values(fleetData.firmware_analysis.version_distribution))) * 100}%`,
                            }}
                          />
                        </div>
                        <span className="text-sm text-muted-foreground">{count}</span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        </div>

        <div className="bg-card rounded-lg border border-border shadow-sm p-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-muted/50 rounded-lg p-6">
              <h3 className="text-lg font-medium mb-2 flex items-center gap-2">
                <WifiTetheringIcon className="h-5 w-5 text-primary shrink-0" />
                WiFi STA signals (fleet)
              </h3>
              <p className="text-xs text-muted-foreground mb-4">
                <span className="font-medium tabular-nums">{fleetWifiStaSummary.uniqueStaCount}</span> unique
                STA MACs
                {fleetWifiStaSummary.laaStaCount > 0 ? (
                  <>
                    {" "}
                    (<span className="font-medium tabular-nums">{fleetWifiStaSummary.laaStaCount}</span>{" "}
                    locally administered / LAA)
                  </>
                ) : null}
                {" · "}
                <span className="font-medium tabular-nums">{staSignalCpeCount}</span> CPEs with issue groups
                (loaded max 2000 rows). Vendor from local{" "}
                <code className="rounded bg-muted px-1">oui.txt</code> when available.
              </p>
              {staIssuesGroupedQuery.isLoading ? (
                <div className="text-center py-6 text-sm text-muted-foreground">Loading STA analytics…</div>
              ) : staIssuesGroupedQuery.isError ? (
                <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  {String(staIssuesGroupedQuery.error)}
                </div>
              ) : fleetWifiStaSummary.issueDistribution.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No STA protocol issues in loaded data. Use the WiFi STA tab to re-run ETL or inspect
                  per-CPE detail.
                </p>
              ) : (
                <>
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                    Issue type distribution (events)
                  </h4>
                  <div className="space-y-3">
                    {fleetWifiStaSummary.issueDistribution.slice(0, 5).map(({ issue_key, count }) => {
                      const top = fleetWifiStaSummary.issueDistribution[0]?.count ?? 1;
                      const wMax = Math.max(1, top);
                      return (
                        <div key={issue_key} className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium text-foreground line-clamp-2">
                            {(issue_key || "unknown").replace(/_/g, " ")}
                          </span>
                          <div className="flex items-center gap-2 shrink-0">
                            <div className="w-24 bg-muted rounded-full h-2">
                              <div
                                className="bg-primary h-2 rounded-full"
                                style={{ width: `${(count / wMax) * 100}%` }}
                              />
                            </div>
                            <span className="text-sm text-muted-foreground tabular-nums">{count}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mt-5 mb-2">
                    STAs most affected (estimated events per MAC)
                  </h4>
                  <ul className="space-y-2.5 text-sm">
                    {fleetWifiStaSummary.topStas.slice(0, 5).map((row) => {
                      const breakdown = row.issues
                        .slice(0, 3)
                        .map(
                          (i) =>
                            `${(i.issue_key || "").replace(/_/g, " ")} (${i.count >= 10 ? Math.round(i.count) : i.count.toFixed(1)})`,
                        )
                        .join(" · ");
                      const vendorLabel = row.vendor?.trim() || null;
                      return (
                        <li
                          key={row.mac}
                          className="border-b border-border/80 pb-2 last:border-0 last:pb-0"
                        >
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-xs text-foreground">
                            <span>{row.displayMac}</span>
                            {vendorLabel ? (
                              <span className="font-sans text-[11px] font-normal text-muted-foreground">
                                · {vendorLabel}
                              </span>
                            ) : (
                              <span className="font-sans text-[11px] font-normal text-muted-foreground/70">
                                · unknown OUI
                              </span>
                            )}
                            {row.isLaa ? (
                              <span
                                className="font-sans text-[10px] font-medium uppercase tracking-wide rounded px-1 py-px border border-yellow-600/40 bg-yellow-100 text-yellow-950 dark:border-yellow-200/80 dark:bg-yellow-400/18 dark:text-yellow-100"
                                title="Locally administered address (U/L bit set)"
                              >
                                LAA
                              </span>
                            ) : null}
                          </div>
                          <div className="text-xs text-muted-foreground mt-0.5">
                            ~{row.total >= 10 ? Math.round(row.total) : row.total.toFixed(1)} events ·{" "}
                            {breakdown}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}
            </div>

            <div className="bg-muted/50 rounded-lg p-6">
              <h3 className="text-lg font-medium mb-2 flex items-center gap-2">
                <TroubleshootIcon className="h-5 w-5 text-muted-foreground shrink-0" />
                SelfHeal signals (fleet)
              </h3>
              <p className="text-xs text-muted-foreground mb-4">
                Tag counts are per insight row (a row may include multiple tags). Process lists are parsed from
                detail lines for restart and RSS-leak signals.
              </p>
              {selfHealInsightsQuery.isLoading ? (
                <div className="text-center py-6 text-sm text-muted-foreground">Loading SelfHeal analytics…</div>
              ) : selfHealInsightsQuery.isError ? (
                <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  {String(selfHealInsightsQuery.error)}
                </div>
              ) : fleetSelfHealSummary.tagDistribution.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No SelfHeal insights in loaded data. Use the SelfHeal tab to re-run ETL or inspect per-CPE
                  detail.
                </p>
              ) : (
                <>
                  <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                    Tag distribution (insight rows)
                  </h4>
                  <div className="space-y-3">
                    {fleetSelfHealSummary.tagDistribution.slice(0, 6).map(({ tag, count }) => {
                      const top = fleetSelfHealSummary.tagDistribution[0]?.count ?? 1;
                      const wMax = Math.max(1, top);
                      const label = SELFHEAL_TAG_LABELS[tag] ?? tag.replace(/_/g, " ");
                      return (
                        <div key={tag} className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium text-foreground line-clamp-2">{label}</span>
                          <div className="flex items-center gap-2 shrink-0">
                            <div className="w-24 bg-muted rounded-full h-2">
                              <div
                                className="bg-violet-600 dark:bg-violet-400 h-2 rounded-full"
                                style={{ width: `${(count / wMax) * 100}%` }}
                              />
                            </div>
                            <span className="text-sm text-muted-foreground tabular-nums">{count}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  {fleetSelfHealSummary.restartingProcesses.length > 0 ? (
                    <div className="mt-5">
                      <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                        Processes restarting (mentions)
                      </h4>
                      <ul className="text-xs text-foreground space-y-1 font-mono">
                        {fleetSelfHealSummary.restartingProcesses.slice(0, 6).map((p) => (
                          <li key={p.name} className="flex justify-between gap-2">
                            <span className="truncate">{p.name}</span>
                            <span className="tabular-nums text-muted-foreground shrink-0">{p.mentions}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {fleetSelfHealSummary.leakingProcesses.length > 0 ? (
                    <div className="mt-4">
                      <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                        Processes leaking RSS (mentions)
                      </h4>
                      <ul className="text-xs text-foreground space-y-1 font-mono">
                        {fleetSelfHealSummary.leakingProcesses.slice(0, 6).map((p) => (
                          <li key={p.name} className="flex justify-between gap-2">
                            <span className="truncate">{p.name}</span>
                            <span className="tabular-nums text-muted-foreground shrink-0">{p.mentions}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </div>
        </div>

        <p className="text-sm text-muted-foreground">
          Open <span className="font-medium">WiFi STA</span> or <span className="font-medium">SelfHeal</span>{" "}
          for Polars ETL, filters, and per-CPE detail.
        </p>
          </>
        ) : activeTab === "wifi-sta" ? (
          <div className="bg-card rounded-lg border border-border shadow-sm">
            {renderSignalsEtlBanner()}
            <div className="p-6 space-y-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
                <label className="flex flex-col gap-1 min-w-[14rem] flex-1 max-w-md">
                  <span className="text-xs font-medium text-muted-foreground">CPE serial or STA MAC</span>
                  <input
                    type="search"
                    value={fleetSignalsCpeSearch}
                    onChange={(e) => setFleetSignalsCpeSearch(e.target.value)}
                    placeholder="Substring on serial; paste STA MAC to match"
                    autoComplete="off"
                    className="px-3 py-2 border border-input rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
                    aria-label="Filter by CPE serial or STA MAC"
                  />
                </label>
                <label className="flex flex-col gap-1 min-w-[12rem] flex-1 max-w-md">
                  <span className="text-xs font-medium text-muted-foreground">WiFi issue type</span>
                  <input
                    type="search"
                    value={staIssueSearch}
                    onChange={(e) => setStaIssueSearch(e.target.value)}
                    placeholder="e.g. deauth, assoc loop…"
                    autoComplete="off"
                    className="px-3 py-2 border border-input rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    aria-label="Search STA issues by issue type"
                  />
                </label>
              </div>

              <section aria-labelledby="sta-signals-heading" className="space-y-3">
                <h3 id="sta-signals-heading" className="text-base font-medium flex items-center gap-2">
                  <WifiTetheringIcon className="h-5 w-5 text-primary" />
                  WiFi STA protocol issues
                </h3>
                <p className="text-xs text-muted-foreground">
                  <strong>Near reboot</strong> means the issue window overlaps a device reboot (± margin).
                  Vendors from local <code className="bg-muted px-1 rounded">oui.txt</code> only.
                </p>
                {staIssuesGroupedQuery.isLoading ? (
                  <div className="text-center py-8 text-muted-foreground">Loading STA issues…</div>
                ) : staIssuesGroupedQuery.isError ? (
                  <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                    {String(staIssuesGroupedQuery.error)}
                  </div>
                ) : staIssuesGrouped && staIssuesGrouped.length > 0 && staIssuesByDevice.length === 0 ? (
                  <div className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-sm text-amber-950 dark:text-amber-100">
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
                          className="rounded-lg border border-border bg-card overflow-hidden"
                        >
                          <div className="px-3 py-2 bg-muted/50 border-b border-border flex flex-wrap items-baseline justify-between gap-2">
                            <div>
                              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                                Device
                              </span>
                              <div className="font-mono text-sm text-foreground">{deviceSerial}</div>
                            </div>
                            <span className="text-xs text-muted-foreground tabular-nums">
                              {issues.length} issue type{issues.length === 1 ? "" : "s"} · {deviceIssueSum}{" "}
                              event{deviceIssueSum === 1 ? "" : "s"}
                            </span>
                          </div>
                          <ul className="divide-y divide-border">
                            {issues.map((issue) => {
                              const sev = (issue.severity || "").toLowerCase();
                              const sevClass =
                                sev === "high"
                                  ? "border border-destructive/40 bg-destructive/15 text-destructive dark:bg-destructive/30 dark:text-red-100"
                                  : sev === "medium"
                                    ? "border border-yellow-600/35 bg-yellow-100 text-yellow-950 dark:border-yellow-200/75 dark:bg-yellow-400/20 dark:text-yellow-100"
                                    : "border border-border bg-muted text-foreground";
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
                                      <span className="font-mono text-sm text-foreground">
                                        {issue.issue_key.replace(/_/g, " ")}
                                      </span>
                                      <span className="text-xs text-muted-foreground tabular-nums">
                                        {issue.sta_count} STA{issue.sta_count === 1 ? "" : "s"}
                                      </span>
                                      {issue.may_overlap_reboot ? (
                                        <span
                                          className="text-xs font-medium rounded px-1.5 py-0.5 border border-yellow-600/40 bg-yellow-100 text-yellow-950 dark:border-yellow-200/80 dark:bg-yellow-400/18 dark:text-yellow-100"
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
                                    <ul className="mt-2 mb-1 pl-2 border-l-2 border-border space-y-1.5">
                                      {issue.sta_list.map((s) => (
                                        <li
                                          key={s.sta_mac}
                                          className="text-xs font-mono text-foreground flex flex-wrap gap-x-2 gap-y-0.5"
                                        >
                                          <span>{s.sta_mac}</span>
                                          {s.vendor ? (
                                            <span className="text-muted-foreground font-sans">{s.vendor}</span>
                                          ) : (
                                            <span className="text-muted-foreground/70 font-sans">—</span>
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
                    <p className="text-xs text-muted-foreground">
                      Showing {staIssuesByDevice.length} device
                      {staIssuesByDevice.length === 1 ? "" : "s"} (
                      {staIssuesByDevice.reduce((n, [, iss]) => n + iss.length, 0)} issue groups) from{" "}
                      {staIssuesGrouped.length} loaded (max 2000).
                    </p>
                  </div>
                ) : (
                  <div className="rounded-lg border border-border bg-muted/50 px-4 py-8 text-center text-sm text-muted-foreground space-y-4">
                    <p>
                      No STA protocol issues found for this project. Run Polars ETL so{" "}
                      <code className="text-xs bg-muted px-1 rounded">sta_issues.parquet</code> is regenerated.
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
              </section>
            </div>
          </div>
        ) : (
          <div className="bg-card rounded-lg border border-border shadow-sm">
            {renderSignalsEtlBanner()}
            <div className="p-6 space-y-4">
              <label className="flex flex-col gap-1 min-w-[14rem] max-w-md">
                <span className="text-xs font-medium text-muted-foreground">CPE serial</span>
                <input
                  type="search"
                  value={fleetSignalsCpeSearch}
                  onChange={(e) => setFleetSignalsCpeSearch(e.target.value)}
                  placeholder="Substring on device serial"
                  autoComplete="off"
                  className="px-3 py-2 border border-input rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
                  aria-label="Filter SelfHeal list by CPE serial"
                />
              </label>

              <section aria-labelledby="selfheal-signals-heading" className="space-y-3">
                <h3 id="selfheal-signals-heading" className="text-base font-medium flex items-center gap-2">
                  <TroubleshootIcon className="h-5 w-5 text-muted-foreground" />
                  SelfHeal-based signals
                </h3>
                <p className="text-xs text-muted-foreground">
                  From periodic <code className="bg-muted px-1 rounded">top</code> and{" "}
                  <code className="bg-muted px-1 rounded">/proc/meminfo</code> captures.
                </p>
                {selfHealInsightsQuery.isLoading ? (
                  <div className="text-center py-8 text-muted-foreground">Loading SelfHeal insights…</div>
                ) : selfHealInsightsQuery.isError ? (
                  <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                    {String(selfHealInsightsQuery.error)}
                  </div>
                ) : selfHealFiltered.length > 0 ? (
                  <div className="space-y-3">
                    {selfHealFiltered.map((row) => {
                      const sev = (row.severity || "").toLowerCase();
                      const sevClass =
                        sev === "high"
                          ? "border border-destructive/40 bg-destructive/15 text-destructive dark:bg-destructive/30 dark:text-red-100"
                          : sev === "medium"
                            ? "border border-yellow-600/35 bg-yellow-100 text-yellow-950 dark:border-yellow-200/75 dark:bg-yellow-400/20 dark:text-yellow-100"
                            : "border border-border bg-muted text-foreground";
                      const tagLine = (row.tags || [])
                        .map((t) => t.replace(/_/g, " "))
                        .join(" · ");
                      return (
                        <div
                          key={`${row.device_serial}-${row.processing_date || ""}`}
                          className="rounded-lg border border-border bg-card overflow-hidden"
                        >
                          <details className="group">
                            <summary className="cursor-pointer list-none px-3 py-2 bg-muted/50 border-b border-border flex flex-wrap items-center gap-2 [&::-webkit-details-marker]:hidden">
                              <span className="font-mono text-sm text-foreground">{row.device_serial}</span>
                              <span
                                className={cn(
                                  "inline-block rounded px-2 py-0.5 text-xs font-medium capitalize shrink-0",
                                  sevClass,
                                )}
                              >
                                {row.severity || "—"}
                              </span>
                              <span className="text-xs text-foreground/90">{tagLine}</span>
                            </summary>
                            <ul className="px-4 py-3 text-sm text-foreground space-y-1.5 list-disc list-inside">
                              {(row.detail_lines || []).map((line, i) => (
                                <li key={i}>{line}</li>
                              ))}
                            </ul>
                          </details>
                        </div>
                      );
                    })}
                    <p className="text-xs text-muted-foreground">
                      Showing {selfHealFiltered.length} CPE
                      {selfHealFiltered.length === 1 ? "" : "s"} with SelfHeal signals (loaded max 2000).
                    </p>
                  </div>
                ) : (
                  <div className="rounded-lg border border-border bg-muted/50 px-4 py-8 text-center text-sm text-muted-foreground">
                    <p>
                      No SelfHeal insights for this project yet. Ensure{" "}
                      <code className="text-xs bg-muted px-1 rounded">SelfHeal.txt</code> is parsed, then run
                      Polars ETL so{" "}
                      <code className="text-xs bg-muted px-1 rounded">selfheal_insights.parquet</code> is
                      generated.
                    </p>
                  </div>
                )}
              </section>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default AnalyticsPage;
