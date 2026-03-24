import { useState, useMemo, Fragment } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { cpeOverviewApi, cpesApi } from "@/api/endpoints";
import type { PatternScanResult, PatternScanDomain } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import Plot from "react-plotly.js";
import CircularProgress from "@mui/material/CircularProgress";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";

/* ---------------------------------------------------------------- Types */

interface PatternRow {
  domain: string;
  name: string;
  /** Regex used for the scan; undefined if cache predates API support. */
  regex?: string;
  cpesAffected: number;
  pctAffected: number;
  totalMatches: number;
  perCpeCounts: { serial: string; count: number }[];
}

type SortKey = "name" | "cpesAffected" | "pctAffected" | "totalMatches";

/* ---------------------------------------------------------------- Constants */

/**
 * Light categorical domain colors: pastel blues / indigos / violets / cyans.
 * Avoids status-like hues (red, green, orange, brown) and their shades.
 */
const DOMAIN_COLORS: string[] = [
  "#93C5FD",
  "#A5B4FC",
  "#C4B5FD",
  "#7DD3FC",
  "#67E8F9",
  "#D8B4FE",
  "#99B9F1",
  "#A8C5DA",
  "#C9B8E8",
  "#BFDBFE",
];

const NO_TOOLBAR = { displayModeBar: false } as const;

function escapeHtmlForPlotlyHover(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function severityClass(pct: number): string {
  if (pct >= 80) return "bg-red-50 dark:bg-red-900/15 border-red-200 dark:border-red-800";
  if (pct >= 50) return "bg-orange-50 dark:bg-orange-900/10 border-orange-200 dark:border-orange-800";
  if (pct >= 25) return "bg-yellow-50 dark:bg-yellow-900/10 border-yellow-200 dark:border-yellow-800";
  return "border-border";
}

function severityBadge(pct: number): string {
  if (pct >= 80) return "text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-900/30";
  if (pct >= 50) return "text-orange-700 dark:text-orange-400 bg-orange-100 dark:bg-orange-900/30";
  if (pct >= 25) return "text-yellow-700 dark:text-yellow-400 bg-yellow-100 dark:bg-yellow-900/30";
  return "text-muted-foreground bg-muted";
}

/* ---------------------------------------------------------------- Component */

export default function PatternOverviewTab() {
  const { projectId } = useProject();
  const queryClient = useQueryClient();

  const [sortKey, setSortKey] = useState<SortKey>("pctAffected");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [expandedPattern, setExpandedPattern] = useState<string | null>(null);
  const [domainFilter, setDomainFilter] = useState<string>("all");
  const [rebootWindowMinutes, setRebootWindowMinutes] = useState<number>(60); // Default 1 hour
  const [enableRebootFilter, setEnableRebootFilter] = useState<boolean>(true);

  const { data: cpeList } = useQuery<Array<{ serial: string }>>({
    queryKey: ["cpe-list", projectId],
    queryFn: async () => (await cpesApi.list(projectId!)).data,
    enabled: !!projectId,
  });

  const {
    data: scanData,
    isLoading: loadingCache,
  } = useQuery<PatternScanResult>({
    queryKey: ["cpe-overview-pattern-scan", projectId],
    queryFn: async () => (await cpeOverviewApi.getPatternScan(projectId!)).data,
    enabled: !!projectId,
  });

  const scanMutation = useMutation({
    mutationFn: async () => 
      (await cpeOverviewApi.runPatternScan(projectId!, {
        reboot_window_minutes: enableRebootFilter ? rebootWindowMinutes : undefined
      })).data,
    onSuccess: (data) => {
      queryClient.setQueryData(["cpe-overview-pattern-scan", projectId], data);
    },
  });

  const hasCachedData =
    scanData?.cached === true &&
    scanData.domains &&
    Object.keys(scanData.domains).length > 0;

  const totalCpes = useMemo(() => {
    if (!scanData?.domains) return 0;
    const first = Object.values(scanData.domains)[0] as PatternScanDomain | undefined;
    return first?.cpes?.length ?? cpeList?.length ?? 0;
  }, [scanData, cpeList]);

  const { rows, domainNames } = useMemo(() => {
    if (!scanData?.domains) return { rows: [], domainNames: [] as string[] };

    const allRows: PatternRow[] = [];
    const names: string[] = [];

    for (const [domain, domData] of Object.entries(scanData.domains)) {
      names.push(domain);
      const dd = domData as PatternScanDomain;
      dd.patterns.forEach((patName, pIdx) => {
        let affected = 0;
        let total = 0;
        const perCpe: { serial: string; count: number }[] = [];

        for (const cpe of dd.cpes) {
          const cnt = cpe.counts[pIdx] ?? 0;
          total += cnt;
          if (cnt > 0) affected++;
          perCpe.push({ serial: cpe.serial, count: cnt });
        }

        allRows.push({
          domain,
          name: patName,
          regex: dd.pattern_regexes?.[pIdx],
          cpesAffected: affected,
          pctAffected: totalCpes > 0 ? Math.round((affected / totalCpes) * 100) : 0,
          totalMatches: total,
          perCpeCounts: perCpe.sort((a, b) => b.count - a.count),
        });
      });
    }

    return { rows: allRows, domainNames: names };
  }, [scanData, totalCpes]);

  const filteredRows = useMemo(() => {
    let r = domainFilter === "all" ? rows : rows.filter((p) => p.domain === domainFilter);
    r = r.filter((p) => p.totalMatches > 0);
    r = [...r].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "string" && typeof bv === "string") {
        return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return r;
  }, [rows, sortKey, sortDir, domainFilter]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sortKey !== col) return null;
    return sortDir === "asc"
      ? <ArrowUpwardIcon style={{ fontSize: 12 }} />
      : <ArrowDownwardIcon style={{ fontSize: 12 }} />;
  };

  /* ---- Chart data ---- */
  const chartData = useMemo(() => {
    if (filteredRows.length === 0) return null;

    const sorted = [...filteredRows].sort((a, b) => a.pctAffected - b.pctAffected);
    const domainColorMap: Record<string, string> = {};
    domainNames.forEach((d, i) => {
      domainColorMap[d] = DOMAIN_COLORS[i % DOMAIN_COLORS.length];
    });

    return {
      y: sorted.map((r) => r.name),
      x: sorted.map((r) => r.pctAffected),
      colors: sorted.map((r) => domainColorMap[r.domain] ?? "#888"),
      customdata: sorted.map((r) => {
        const trimmed = r.regex?.trim();
        const regexSuffix = trimmed
          ? `<br>Regex: ${escapeHtmlForPlotlyHover(trimmed)}`
          : "";
        return [r.cpesAffected, totalCpes, r.totalMatches, r.domain, regexSuffix] as const;
      }),
    };
  }, [filteredRows, domainNames, totalCpes]);

  /* ---- Render ---- */

  if (!projectId) {
    return (
      <div className="flex items-center justify-center h-40 text-muted-foreground">
        Select a project from the Dashboard.
      </div>
    );
  }

  if (loadingCache) {
    return (
      <div className="bg-card border border-border rounded-xl p-6 flex items-center justify-center gap-2 text-muted-foreground">
        <CircularProgress size={20} />
        <span className="text-sm">Loading cached scan data...</span>
      </div>
    );
  }

  const scanButton = (
    <button
      onClick={() => scanMutation.mutate()}
      disabled={scanMutation.isPending}
      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
    >
      {scanMutation.isPending ? (
        <>
          <CircularProgress size={16} color="inherit" />
          Scanning {totalCpes || "all"} CPEs...
        </>
      ) : (
        <>
          <PlayArrowIcon style={{ fontSize: 18 }} />
          {hasCachedData ? "Re-scan All CPEs" : "Run Pattern Scan"}
        </>
      )}
    </button>
  );

  if (!hasCachedData) {
    return (
      <div className="bg-card border border-border rounded-xl p-8 flex flex-col items-center gap-4 text-center">
        <p className="text-sm text-muted-foreground max-w-md">
          Scan your project&apos;s regex patterns across all CPEs to see distribution and identify widespread issues.
        </p>
        {scanMutation.isError && (
          <p className="text-sm text-destructive">
            {(scanMutation.error as Error)?.message
              || (scanMutation.error as { response?: { data?: { error?: string } } })?.response?.data?.error
              || "Scan failed"}
          </p>
        )}
        {scanButton}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Reboot Timeline Filter */}
      <div className="bg-card border border-border rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Reboot Timeline Filter
          </h3>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={enableRebootFilter}
              onChange={(e) => setEnableRebootFilter(e.target.checked)}
              className="h-4 w-4 accent-blue-600"
            />
            <span className="text-xs">Enable</span>
          </label>
        </div>
        
        {enableRebootFilter && (
          <div>
            <label className="text-xs text-muted-foreground block mb-2">
              Show matches within {rebootWindowMinutes} minutes before each reboot
            </label>
            <input
              type="range"
              min="15"
              max="360"
              step="15"
              value={rebootWindowMinutes}
              onChange={(e) => setRebootWindowMinutes(Number(e.target.value))}
              className="w-full"
            />
            <div className="flex justify-between text-xs text-muted-foreground mt-1">
              <span>15 min</span>
              <span>6 hours</span>
            </div>
          </div>
        )}
      </div>

      {/* Controls bar */}
      <div className="bg-card border border-border rounded-xl px-3 py-2 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>
            <strong className="text-foreground">{totalCpes}</strong> CPEs
          </span>
          <span className="text-border">|</span>
          <span>
            <strong className="text-foreground">{rows.length}</strong> patterns across{" "}
            <strong className="text-foreground">{domainNames.length}</strong> domains
          </span>
          {scanData?.scanned_at && (
            <>
              <span className="text-border">|</span>
              <span>
                Scanned {new Date(scanData.scanned_at).toLocaleString()}
                {scanData.elapsed_ms ? ` (${(scanData.elapsed_ms / 1000).toFixed(1)}s)` : ""}
              </span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <select
            value={domainFilter}
            onChange={(e) => setDomainFilter(e.target.value)}
            className="text-xs px-2 py-1.5 border border-border rounded-lg bg-background focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="all">All Domains</option>
            {domainNames.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          {scanButton}
        </div>
      </div>

      {scanMutation.isError && (
        <p className="text-sm text-destructive px-1">
          {(scanMutation.error as Error)?.message
            || (scanMutation.error as { response?: { data?: { error?: string } } })?.response?.data?.error
            || "Scan failed"}
        </p>
      )}

      {/* Horizontal bar chart */}
      {chartData && chartData.y.length > 0 && (
        <div className="bg-card border border-border rounded-xl">
          <div className="px-3 py-1.5 border-b border-border bg-muted/30">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Pattern Spread Across CPEs
            </h3>
          </div>
          <div className="px-2 py-1">
            <Plot
              data={[
                {
                  type: "bar",
                  orientation: "h",
                  y: chartData.y,
                  x: chartData.x,
                  marker: { color: chartData.colors },
                  customdata: chartData.customdata,
                  hovertemplate:
                    "<b>%{y}</b> (%{customdata[3]})<br>" +
                    "CPEs affected: %{customdata[0]} / %{customdata[1]}<br>" +
                    "Spread: %{x}%<br>" +
                    "Total matches: %{customdata[2]}%{customdata[4]}<extra></extra>",
                  text: chartData.x.map((v) => `${v}%`),
                  textposition: "outside",
                  textfont: { size: 9 },
                  cliponaxis: false,
                } as any,
              ]}
              layout={{
                height: Math.max(200, chartData.y.length * 28 + 60),
                margin: { l: 220, r: 50, t: 10, b: 30 },
                xaxis: {
                  title: { text: "% of CPEs Affected", font: { size: 10 } },
                  range: [0, Math.min(110, Math.max(...chartData.x) + 15)],
                  ticksuffix: "%",
                  tickfont: { size: 9 },
                  gridcolor: "rgba(128,128,128,0.15)",
                },
                yaxis: {
                  automargin: true,
                  tickfont: { size: 9 },
                },
                paper_bgcolor: "transparent",
                plot_bgcolor: "transparent",
                font: { color: "#888", size: 10 },
                bargap: 0.15,
              }}
              config={NO_TOOLBAR}
              useResizeHandler
              style={{ width: "100%" }}
            />
          </div>
        </div>
      )}

      {/* Detail table */}
      <div className="flex justify-center">
        <div className="bg-card border border-border rounded-xl overflow-hidden inline-block">
        <div className="px-3 py-1 border-b border-border bg-muted/30">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Pattern Distribution Detail
          </h3>
        </div>

        <div className="overflow-x-auto">
          <table className="text-[11px] border-collapse">
            <colgroup>
              <col style={{ width: "140px" }} />
              <col style={{ width: "auto" }} />
              <col style={{ width: "120px" }} />
              <col style={{ width: "80px" }} />
              <col style={{ width: "100px" }} />
              <col style={{ width: "60px" }} />
            </colgroup>
            <thead>
              <tr className="border-b border-border bg-muted/20">
                <th className="text-left px-2 py-1 font-semibold text-muted-foreground">Domain</th>
                <th
                  className="text-left px-2 py-1 font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none"
                  onClick={() => handleSort("name")}
                >
                  Pattern <SortIcon col="name" />
                </th>
                <th
                  className="text-right px-2 py-1 font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none whitespace-nowrap"
                  onClick={() => handleSort("cpesAffected")}
                >
                  CPEs <SortIcon col="cpesAffected" />
                </th>
                <th
                  className="text-right px-2 py-1 font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none whitespace-nowrap"
                  onClick={() => handleSort("pctAffected")}
                >
                  % <SortIcon col="pctAffected" />
                </th>
                <th
                  className="text-right px-2 py-1 font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none whitespace-nowrap"
                  onClick={() => handleSort("totalMatches")}
                >
                  Matches <SortIcon col="totalMatches" />
                </th>
                <th className="px-0 py-1"></th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-2 py-6 text-center text-muted-foreground">
                    No patterns with matches found.
                  </td>
                </tr>
              )}
              {filteredRows.map((row) => {
                const key = `${row.domain}::${row.name}`;
                const isExpanded = expandedPattern === key;
                const domainColor = DOMAIN_COLORS[domainNames.indexOf(row.domain) % DOMAIN_COLORS.length];
                return (
                  <Fragment key={key}>
                    <tr
                      className={`border-b cursor-pointer hover:bg-muted/30 transition-colors ${severityClass(row.pctAffected)}`}
                      onClick={() => setExpandedPattern(isExpanded ? null : key)}
                    >
                      <td className="px-2 py-1 align-top">
                        <span
                          className="inline-block px-1.5 py-px rounded text-[10px] font-medium truncate max-w-[110px] text-foreground border-l-[3px]"
                          style={{
                            backgroundColor: `${domainColor}33`,
                            borderLeftColor: domainColor,
                          }}
                        >
                          {row.domain}
                        </span>
                      </td>
                      <td className="px-2 py-1 font-medium text-foreground">
                        <div className="truncate" title={row.name}>
                          {row.name}
                        </div>
                      </td>
                      <td className="px-2 py-1 text-right tabular-nums whitespace-nowrap align-top">
                        {row.cpesAffected}/{totalCpes}
                      </td>
                      <td className="px-2 py-1 text-right align-top">
                        <span className={`inline-block px-1.5 py-px rounded text-[10px] font-semibold ${severityBadge(row.pctAffected)}`}>
                          {row.pctAffected}%
                        </span>
                      </td>
                      <td className="px-2 py-1 text-right tabular-nums font-medium align-top">
                        {row.totalMatches.toLocaleString()}
                      </td>
                      <td className="px-0 py-1 text-muted-foreground align-top">
                        {isExpanded
                          ? <ExpandLessIcon style={{ fontSize: 14 }} />
                          : <ExpandMoreIcon style={{ fontSize: 14 }} />
                        }
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="border-b bg-muted/10" onClick={(e) => e.stopPropagation()}>
                        <td colSpan={6} className="px-3 py-2">
                          <div className="bg-muted/30 rounded-lg p-2 max-h-[240px] overflow-y-auto">
                            <p className="text-[10px] font-semibold uppercase text-muted-foreground mb-1.5 tracking-wide">
                              Per-CPE Breakdown ({row.perCpeCounts.filter((c) => c.count > 0).length} affected)
                            </p>
                            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-1">
                              {row.perCpeCounts
                                .filter((c) => c.count > 0)
                                .map((c) => (
                                  <div
                                    key={c.serial}
                                    className="flex items-center justify-between px-1.5 py-0.5 rounded bg-background border border-border text-[10px]"
                                  >
                                    <span className="font-mono truncate mr-1">{c.serial}</span>
                                    <span className="font-semibold tabular-nums">{c.count.toLocaleString()}</span>
                                  </div>
                                ))}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    </div>
  );
}
