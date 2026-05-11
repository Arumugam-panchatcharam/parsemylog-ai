import { useState, useMemo, Fragment } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  cpeOverviewApi,
  cpesApi,
  patternAnalyzerApi,
  type MaintenanceWindow,
  type PatternScanResult,
  type PatternScanDomain,
  type PatternValueCompare,
  type UserPattern,
} from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { usePlotlyLayoutMerge } from "@/lib/plotlyTheme";
import Plot from "react-plotly.js";
import CircularProgress from "@mui/material/CircularProgress";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import FilterListIcon from "@mui/icons-material/FilterList";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import FileDownloadIcon from "@mui/icons-material/FileDownload";
import ExcelJS from "exceljs";

/* ---------------------------------------------------------------- Types */

const DISTRIBUTION_EXPORT_KEYS = [
  "domain",
  "pattern_name",
  "pattern_regex",
  "cpe_serial",
  "frequency",
  "numeric_threshold_pattern",
  "numeric_compare",
  "scan_log_filename",
  "reboot_proximity_minutes",
  "pattern_min_frequency_threshold",
  "maintenance_window_utc",
] as const;

type DistributionExportRow = {
  domain: string;
  pattern_name: string;
  pattern_regex: string;
  cpe_serial: string;
  frequency: number;
  numeric_threshold_pattern: string;
  numeric_compare: string;
  scan_log_filename: string;
  reboot_proximity_minutes: string | number;
  pattern_min_frequency_threshold: string | number;
  maintenance_window_utc: string;
};

function distributionHeaderLabel(key: string): string {
  return key
    .split("_")
    .map((w) => (w.length ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : ""))
    .join(" ");
}

/** Blend domain plot color toward white for readable row fills in Excel. */
function domainRowFillArgb(cssHex: string, colorWeight = 0.32): string {
  const hex = cssHex.replace("#", "").trim();
  if (hex.length !== 6) return "FFF3F4F6";
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  const mix = (c: number) => Math.round(255 * (1 - colorWeight) + c * colorWeight);
  const rr = mix(r).toString(16).padStart(2, "0");
  const gg = mix(g).toString(16).padStart(2, "0");
  const bb = mix(b).toString(16).padStart(2, "0");
  return `FF${rr}${gg}${bb}`.toUpperCase();
}

interface PatternRow {
  domain: string;
  name: string;
  /** Regex used for the scan; undefined if cache predates API support. */
  regex?: string;
  /** True → overview counts are 0/1 pass-fail per CPE. */
  valueComparePattern?: boolean;
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

function isCpeOverviewDisabledError(e: unknown): boolean {
  if (typeof e !== "object" || e === null || !("response" in e)) return false;
  const r = (e as { response?: { status?: number; data?: { disabled?: boolean } } }).response;
  return r?.status === 503 && r?.data?.disabled === true;
}

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

/** Human-readable numeric rule for export (e.g. "<=200"). */
function formatNumericCompareSummary(vc: PatternValueCompare | null | undefined): string {
  if (!vc?.enabled) return "";
  const opSyms: Record<PatternValueCompare["operator"], string> = {
    lte: "<=",
    lt: "<",
    gte: ">=",
    gt: ">",
    eq: "=",
    neq: "!=",
  };
  let s = `${opSyms[vc.operator] ?? vc.operator}${vc.compare_to}`;
  if (vc.capture_group != null && vc.capture_group !== 1) {
    s += ` (group ${vc.capture_group})`;
  }
  return s;
}

function formatMaintenanceWindowUtc(mw: MaintenanceWindow | null | undefined): string {
  if (!mw?.start?.trim() || !mw?.end?.trim()) return "";
  return `${mw.start}-${mw.end}_UTC`;
}

/* ---------------------------------------------------------------- Component */

export default function PatternOverviewTab() {
  const { projectId } = useProject();
  const queryClient = useQueryClient();
  const mergePlot = usePlotlyLayoutMerge();

  const [sortKey, setSortKey] = useState<SortKey>("pctAffected");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [expandedPattern, setExpandedPattern] = useState<string | null>(null);
  const [domainFilter, setDomainFilter] = useState<string>("all");
  const [rebootWindowMinutes, setRebootWindowMinutes] = useState<number>(60); // Default 1 hour
  const [enableRebootFilter, setEnableRebootFilter] = useState<boolean>(false);
  const [filterShortReboots, setFilterShortReboots] = useState(true);
  const [minFrequencyThreshold, setMinFrequencyThreshold] = useState<number>(1);
  const [enableFrequencyFilter, setEnableFrequencyFilter] = useState<boolean>(false);
  const [isChartCollapsed, setIsChartCollapsed] = useState<boolean>(false);

  const { data: cpeList } = useQuery<Array<{ serial: string }>>({
    queryKey: ["cpe-list", projectId],
    queryFn: async () => (await cpesApi.list(projectId!)).data,
    enabled: !!projectId,
  });

  const { data: patternDomains } = useQuery({
    queryKey: ["regex-patterns", projectId],
    queryFn: async () => (await patternAnalyzerApi.getPatterns(projectId!)).data.domains,
    enabled: !!projectId,
    staleTime: 60_000,
  });

  const patternDefByDomainName = useMemo(() => {
    const map = new Map<string, UserPattern>();
    if (!patternDomains) return map;
    for (const [domain, plist] of Object.entries(patternDomains)) {
      for (const p of plist) {
        map.set(`${domain}\0${p.name}`, p);
      }
    }
    return map;
  }, [patternDomains]);

  const {
    data: scanData,
    isLoading: loadingCache,
    isError: scanCacheError,
    error: scanCacheErr,
  } = useQuery<PatternScanResult>({
    queryKey: ["cpe-overview-pattern-scan", projectId],
    queryFn: async () => (await cpeOverviewApi.getPatternScan(projectId!)).data,
    enabled: !!projectId,
    retry: false,
  });

  const scanMutation = useMutation({
    mutationFn: async () => {
      return (await cpeOverviewApi.runPatternScan(projectId!, {
        reboot_window_minutes: enableRebootFilter ? rebootWindowMinutes : undefined,
        filter_short_reboots: filterShortReboots,
        min_frequency_threshold: enableFrequencyFilter ? minFrequencyThreshold : undefined
      })).data;
    },
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
        const isVc = dd.pattern_value_compare?.[pIdx] === true;
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
          valueComparePattern: isVc,
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

  const downloadDistributionExcel = () => {
    if (!projectId || filteredRows.length === 0) return;

    const lookupPattern = (domain: string, name: string): UserPattern | undefined =>
      patternDefByDomainName.get(`${domain}\0${name}`);

    const data: DistributionExportRow[] = filteredRows.flatMap((row) =>
      row.perCpeCounts.map(({ serial, count }) => {
        const pat = lookupPattern(row.domain, row.name);
        const mw = formatMaintenanceWindowUtc(pat?.maintenance_window ?? undefined);
        const rp = pat?.reboot_proximity_minutes;
        const rpCell = rp != null && Number.isFinite(rp) ? rp : "";
        const pmin = pat?.min_frequency_threshold;
        const minCell = pmin != null && Number.isFinite(pmin) ? pmin : "";
        const scanFn = (pat?.scan_filename ?? "").trim();
        const numCompare =
          row.valueComparePattern || pat?.value_compare?.enabled
            ? formatNumericCompareSummary(pat?.value_compare ?? undefined)
            : "";

        const out: DistributionExportRow = {
          domain: row.domain,
          pattern_name: row.name,
          pattern_regex: row.regex ?? "",
          cpe_serial: serial,
          frequency: count,
          numeric_threshold_pattern: row.valueComparePattern ? "yes" : "no",
          numeric_compare: numCompare,
          scan_log_filename: scanFn,
          reboot_proximity_minutes: rpCell,
          pattern_min_frequency_threshold: minCell,
          maintenance_window_utc: mw,
        };

        return out;
      }),
    );

    void (async () => {
      const workbook = new ExcelJS.Workbook();
      const sheet = workbook.addWorksheet("Pattern distribution", {
        views: [
          {
            state: "frozen",
            xSplit: 0,
            ySplit: 1,
            topLeftCell: "A2",
            activeCell: "A2",
          },
        ],
      });

      const headerLabels = DISTRIBUTION_EXPORT_KEYS.map((k) => distributionHeaderLabel(k));
      sheet.addRow(headerLabels);

      const headerRow = sheet.getRow(1);
      headerRow.font = { bold: true, color: { argb: "FF0F172A" } };
      headerRow.fill = {
        type: "pattern",
        pattern: "solid",
        fgColor: { argb: "FFB8D4F5" },
      };
      headerRow.alignment = { vertical: "middle", horizontal: "left", wrapText: true };
      headerRow.height = 20;
      const gridBorderColor = { argb: "FFCBD5E1" };
      headerRow.eachCell((cell, colNum) => {
        if (colNum <= DISTRIBUTION_EXPORT_KEYS.length) {
          cell.border = {
            top: { style: "thin", color: gridBorderColor },
            left: { style: "thin", color: gridBorderColor },
            bottom: { style: "medium", color: { argb: "FF64748B" } },
            right: { style: "thin", color: gridBorderColor },
          };
        }
      });

      const uniqueDomains = [...new Set(data.map((r) => r.domain))];
      const domainArgb = new Map<string, string>();
      uniqueDomains.forEach((d, i) => {
        const hex = DOMAIN_COLORS[i % DOMAIN_COLORS.length];
        domainArgb.set(d, domainRowFillArgb(hex));
      });

      for (const rec of data) {
        sheet.addRow(DISTRIBUTION_EXPORT_KEYS.map((k) => rec[k]));
        const rnum = sheet.lastRow!.number;
        const dataRow = sheet.getRow(rnum);
        dataRow.alignment = { vertical: "top", horizontal: "left", wrapText: true };
        const fillArgb = domainArgb.get(rec.domain) ?? "FFF8FAFC";
        dataRow.eachCell((cell, colNum) => {
          if (colNum <= DISTRIBUTION_EXPORT_KEYS.length) {
            cell.fill = {
              type: "pattern",
              pattern: "solid",
              fgColor: { argb: fillArgb },
            };
            cell.border = {
              top: { style: "thin", color: gridBorderColor },
              left: { style: "thin", color: gridBorderColor },
              bottom: { style: "thin", color: gridBorderColor },
              right: { style: "thin", color: gridBorderColor },
            };
          }
        });
      }

      const numCols = DISTRIBUTION_EXPORT_KEYS.length;
      for (let col = 1; col <= numCols; col++) {
        let maxLen = headerLabels[col - 1]?.length ?? 10;
        for (let rw = 1; rw <= sheet.rowCount; rw++) {
          const cell = sheet.getCell(rw, col);
          const t =
            typeof cell.text === "string" && cell.text.length > 0
              ? cell.text
              : cell.value == null
                ? ""
                : String(cell.value);
          maxLen = Math.max(maxLen, t.length);
        }
        sheet.getColumn(col).width = Math.min(Math.max(maxLen + 3, 11), 80);
      }

      try {
        const buf = await workbook.xlsx.writeBuffer();
        const stamp = new Date().toISOString().replace(/[:]/g, "-").slice(0, 19);
        const fname = `pattern-distribution_${projectId}_${stamp}.xlsx`;
        const blob = new Blob([buf], {
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = fname;
        a.rel = "noopener";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (err: unknown) {
        // eslint-disable-next-line no-console -- export failure needs a visible breadcrumb for support
        console.error("Pattern distribution Excel export failed", err);
      }
    })();
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
        const vcSuffix = r.valueComparePattern
          ? "<br><i>Numeric threshold: Matches = CPE count passing comparison</i>"
          : "";
        return [r.cpesAffected, totalCpes, r.totalMatches, r.domain, regexSuffix, vcSuffix] as const;
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

  if (scanCacheError && isCpeOverviewDisabledError(scanCacheErr)) {
    return (
      <div className="bg-card border border-border rounded-xl p-6 text-center space-y-2 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">Cross-CPE pattern scan is disabled</p>
        <p>
          The server has turned off CPE Overview / pattern-scan APIs. Enable with{" "}
          <code className="text-xs bg-muted px-1 rounded">CPE_OVERVIEW_ENABLED=1</code> on the API if you need this
          tab.
        </p>
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
      {/* Enhanced Controls bar with integrated filters */}
      <div className="bg-card border border-border rounded-xl p-3 space-y-3">
        {/* Stats and main controls row */}
        <div className="flex items-center justify-between flex-wrap gap-2">
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

        {/* Filter status indicator */}
        {(enableRebootFilter || enableFrequencyFilter) && (
          <div className="text-xs text-primary bg-primary/10 px-3 py-1.5 rounded-lg border border-primary/20">
            <span className="font-medium">Filters Active:</span>
            {enableRebootFilter && (
              <span className="ml-2">Reboot Timeline (±{rebootWindowMinutes}min)</span>
            )}
            {enableFrequencyFilter && (
              <span className="ml-2">Frequency Filter (&gt;{minFrequencyThreshold})</span>
            )}
          </div>
        )}

        {/* Compact filters row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Reboot Timeline Filter - Compact */}
          <div className="bg-muted/50 rounded-lg p-3 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <RestartAltIcon style={{ fontSize: 14 }} className="text-orange-600" />
                <span className="text-xs font-medium">Reboot Timeline</span>
              </div>
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={filterShortReboots}
                    onChange={(e) => setFilterShortReboots(e.target.checked)}
                    className="h-3 w-3 accent-purple-600"
                  />
                  <span className="text-xs text-muted-foreground">Short only</span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enableRebootFilter}
                    onChange={(e) => {
                      setEnableRebootFilter(e.target.checked);
                    }}
                    className="h-3 w-3 accent-orange-600"
                  />
                  <span className="text-xs font-medium">Enable</span>
                </label>
              </div>
            </div>
            {enableRebootFilter && (
              <div className="flex items-center gap-3">
                <span className="text-xs text-muted-foreground whitespace-nowrap">±{rebootWindowMinutes}min</span>
                <input
                  type="range"
                  min="15"
                  max="360"
                  step="15"
                  value={rebootWindowMinutes}
                  onChange={(e) => setRebootWindowMinutes(Number(e.target.value))}
                  className="flex-1 h-2"
                />
                <span className="text-xs text-muted-foreground">6h</span>
              </div>
            )}
          </div>

          {/* CPE Frequency Filter - Compact */}
          <div className="bg-muted/50 rounded-lg p-3 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FilterListIcon style={{ fontSize: 14 }} className="text-blue-600" />
                <span className="text-xs font-medium">Frequency Filter</span>
              </div>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={enableFrequencyFilter}
                  onChange={(e) => {
                    setEnableFrequencyFilter(e.target.checked);
                  }}
                  className="h-3 w-3 accent-blue-600"
                />
                <span className="text-xs font-medium">Enable</span>
              </label>
            </div>
            {enableFrequencyFilter && (
              <div className="flex items-center gap-3">
                <span className="text-xs text-muted-foreground whitespace-nowrap">&gt;{minFrequencyThreshold}</span>
                <input
                  type="range"
                  min="1"
                  max="500"
                  step="10"
                  value={minFrequencyThreshold}
                  onChange={(e) => setMinFrequencyThreshold(Number(e.target.value))}
                  className="flex-1 h-2"
                />
                <span className="text-xs text-muted-foreground">500</span>
              </div>
            )}
            {enableFrequencyFilter && (
              <p className="text-xs text-muted-foreground">
                Excludes CPEs with low occurrence counts
              </p>
            )}
          </div>
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
            <div className="flex items-center justify-between">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Pattern Spread Across CPEs
              </h3>
              <button
                onClick={() => setIsChartCollapsed(!isChartCollapsed)}
                className="p-1 rounded hover:bg-muted transition-colors"
                title={isChartCollapsed ? "Expand chart" : "Collapse chart"}
              >
                {isChartCollapsed 
                  ? <ExpandMoreIcon style={{ fontSize: 16 }} className="text-muted-foreground" />
                  : <ExpandLessIcon style={{ fontSize: 16 }} className="text-muted-foreground" />
                }
              </button>
            </div>
          </div>
          {!isChartCollapsed && (
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
                    "Spread: %{x}<br>" +
                    "Total matches: %{customdata[2]}%{customdata[5]}%{customdata[4]}<extra></extra>",
                  text: chartData.x.map((v) => `${v}%`),
                  textposition: "outside",
                  textfont: { size: 9 },
                  cliponaxis: false,
                } as any,
              ]}
              layout={mergePlot({
                height: Math.max(200, chartData.y.length * 28 + 60),
                margin: { l: 220, r: 50, t: 10, b: 30 },
                xaxis: {
                  title: { text: "% of CPEs Affected", font: { size: 10 } },
                  range: [0, Math.min(110, Math.max(...chartData.x) + 15)],
                  ticksuffix: "%",
                  tickfont: { size: 9 },
                },
                yaxis: {
                  automargin: true,
                  tickfont: { size: 9 },
                },
                font: { size: 10 },
                bargap: 0.15,
              })}
              config={NO_TOOLBAR}
              useResizeHandler
              style={{ width: "100%" }}
            />
            </div>
          )}
        </div>
      )}

      {/* Detail table */}
      <div className="flex justify-center">
        <div className="bg-card border border-border rounded-xl overflow-hidden inline-block">
        <div className="px-3 py-1 border-b border-border bg-muted/30 flex items-center justify-between gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Pattern Distribution Detail
          </h3>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              downloadDistributionExcel();
            }}
            disabled={filteredRows.length === 0}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border border-border bg-background hover:bg-muted/80 disabled:opacity-45 disabled:pointer-events-none text-foreground shrink-0"
            title="Download table as Excel (.xlsx): all CPE rows for visible patterns"
          >
            <FileDownloadIcon style={{ fontSize: 14 }} />
            Excel
          </button>
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
                  title={
                    "For numeric-threshold patterns, totals sum 0/1 pass flags per CPE. " +
                    (enableFrequencyFilter && enableRebootFilter
                      ? "Otherwise: total matches after frequency and reboot filters."
                      : enableFrequencyFilter
                        ? "Otherwise: total matches after frequency filter."
                        : enableRebootFilter
                          ? "Otherwise: total matches after reboot timeline filter."
                          : "Otherwise: total matches across all CPEs.")
                  }
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
                        <div className="flex items-center gap-1 min-w-0">
                          {row.valueComparePattern && (
                            <span
                              className="shrink-0 text-[9px] font-bold px-1 py-px rounded bg-violet-100 dark:bg-violet-900/40 text-violet-800 dark:text-violet-200"
                              title="Numeric threshold: cell counts are 0 or 1 per CPE"
                            >
                              #
                            </span>
                          )}
                          <div className="truncate" title={row.name}>
                            {row.name}
                          </div>
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
                        <div className="flex flex-col items-end">
                          <span className="font-semibold">{row.totalMatches.toLocaleString()}</span>
                          {/* Show specific filter indicators */}
                          <div className="flex gap-1 flex-wrap justify-end">
                            {enableFrequencyFilter && (
                              <span className="text-[9px] text-muted-foreground bg-blue-50 px-1 rounded">freq</span>
                            )}
                            {enableRebootFilter && (
                              <span className="text-[9px] text-muted-foreground bg-orange-50 px-1 rounded">reboot</span>
                            )}
                          </div>
                        </div>
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
                            <div className="flex items-center justify-between mb-2">
                              <p className="text-[10px] font-semibold uppercase text-muted-foreground tracking-wide">
                                {row.valueComparePattern ? "CPE pass list (numeric)" : "Per-CPE Breakdown"}
                              </p>
                              <div className="text-[9px] text-muted-foreground bg-background px-2 py-0.5 rounded border">
                                {row.valueComparePattern ? (
                                  <>
                                    {row.totalMatches.toLocaleString()} CPEs passed • cap 1/CPE
                                  </>
                                ) : (
                                  <>
                                    {row.perCpeCounts.filter((c) => c.count > 0).length} CPEs • {row.totalMatches.toLocaleString()}{" "}
                                    total matches
                                  </>
                                )}
                              </div>
                            </div>
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
