import { Fragment, type ReactNode, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";

export interface PatternDistributionRow {
  key: string;
  domain: string;
  name: string;
  cpesAffected: number;
  pctAffected: number;
  totalMatches: number;
  perCpeCounts: { serial: string; count: number }[];
  /** Optional subtitle under name (e.g. detect type). */
  subtitle?: string;
  /** Numeric threshold pattern: 0/1 pass per CPE. */
  valueComparePattern?: boolean;
  /** Small badges under Matches (e.g. freq, reboot filters). */
  matchFilterHints?: string[];
  /** Expandable sample lines. */
  samples?: Array<{ timestamp?: string; source_file?: string; logline?: string }>;
}

export type PatternDistributionSortKey = "name" | "cpesAffected" | "pctAffected" | "totalMatches";

interface PatternDistributionDetailTableProps {
  rows: PatternDistributionRow[];
  totalCpes: number;
  title?: string;
  emptyMessage?: string;
  showDomainColumn?: boolean;
  domainColors?: string[];
  headerActions?: ReactNode;
  matchesColumnTitle?: string;
}

const DEFAULT_DOMAIN_COLORS = [
  "#93C5FD",
  "#A5B4FC",
  "#C4B5FD",
  "#7DD3FC",
  "#67E8F9",
];

function severityClass(pct: number): string {
  if (pct >= 50) return "bg-destructive/10";
  if (pct >= 20) return "bg-amber-500/10";
  return "";
}

function severityBadge(pct: number): string {
  if (pct >= 50) return "bg-destructive/15 text-destructive";
  if (pct >= 20) return "bg-amber-500/15 text-amber-800 dark:text-amber-200";
  return "bg-muted text-muted-foreground";
}

export default function PatternDistributionDetailTable({
  rows,
  totalCpes,
  title = "Pattern Distribution Detail",
  emptyMessage = "No patterns with matches found.",
  showDomainColumn = true,
  domainColors = DEFAULT_DOMAIN_COLORS,
  headerActions,
  matchesColumnTitle,
}: PatternDistributionDetailTableProps) {
  const [sortKey, setSortKey] = useState<PatternDistributionSortKey>("totalMatches");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const domainNames = useMemo(() => [...new Set(rows.map((r) => r.domain))], [rows]);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "string" && typeof bv === "string") {
        return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      const na = Number(av);
      const nb = Number(bv);
      return sortDir === "asc" ? na - nb : nb - na;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const handleSort = (col: PatternDistributionSortKey) => {
    if (sortKey === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(col);
      setSortDir("desc");
    }
  };

  const SortIcon = ({ col }: { col: PatternDistributionSortKey }) =>
    sortKey === col ? (
      sortDir === "asc" ? (
        <ArrowUpwardIcon style={{ fontSize: 12 }} />
      ) : (
        <ArrowDownwardIcon style={{ fontSize: 12 }} />
      )
    ) : null;

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-3 py-1 border-b border-border bg-muted/30 flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </h3>
        {headerActions}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] border-collapse">
          <colgroup>
            {showDomainColumn ? <col style={{ width: "120px" }} /> : null}
            <col />
            <col style={{ width: "80px" }} />
            <col style={{ width: "64px" }} />
            <col style={{ width: "88px" }} />
            <col style={{ width: "24px" }} />
          </colgroup>
          <thead>
            <tr className="border-b border-border bg-muted/20">
              {showDomainColumn ? (
                <th className="text-left px-2 py-1 font-semibold text-muted-foreground">Domain</th>
              ) : null}
              <th
                className="text-left px-2 py-1 font-semibold text-muted-foreground cursor-pointer select-none"
                onClick={() => handleSort("name")}
              >
                Pattern <SortIcon col="name" />
              </th>
              <th
                className="text-right px-2 py-1 font-semibold text-muted-foreground cursor-pointer select-none"
                onClick={() => handleSort("cpesAffected")}
              >
                CPEs <SortIcon col="cpesAffected" />
              </th>
              <th
                className="text-right px-2 py-1 font-semibold text-muted-foreground cursor-pointer select-none"
                onClick={() => handleSort("pctAffected")}
              >
                % <SortIcon col="pctAffected" />
              </th>
              <th
                className="text-right px-2 py-1 font-semibold text-muted-foreground cursor-pointer select-none"
                onClick={() => handleSort("totalMatches")}
                title={matchesColumnTitle}
              >
                Matches <SortIcon col="totalMatches" />
              </th>
              <th className="px-0 py-1" />
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td
                  colSpan={showDomainColumn ? 6 : 5}
                  className="px-2 py-6 text-center text-muted-foreground"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              sorted.map((row) => {
                const isOpen = expandedKey === row.key;
                const domainColor =
                  domainColors[domainNames.indexOf(row.domain) % domainColors.length];
                return (
                  <Fragment key={row.key}>
                    <tr
                      className={cn(
                        "border-b cursor-pointer hover:bg-muted/30 transition-colors",
                        severityClass(row.pctAffected),
                      )}
                      onClick={() => setExpandedKey(isOpen ? null : row.key)}
                    >
                      {showDomainColumn ? (
                        <td className="px-2 py-1 align-top">
                          <span
                            className="inline-block px-1.5 py-px rounded text-[10px] font-medium truncate max-w-[110px] border-l-[3px]"
                            style={{
                              backgroundColor: `${domainColor}33`,
                              borderLeftColor: domainColor,
                            }}
                          >
                            {row.domain}
                          </span>
                        </td>
                      ) : null}
                      <td className="px-2 py-1 font-medium text-foreground">
                        <div className="flex items-center gap-1 min-w-0">
                          {row.valueComparePattern ? (
                            <span
                              className="shrink-0 text-[9px] font-bold px-1 py-px rounded bg-violet-100 dark:bg-violet-900/40 text-violet-800 dark:text-violet-200"
                              title="Numeric threshold: cell counts are 0 or 1 per CPE"
                            >
                              #
                            </span>
                          ) : null}
                          <div className="truncate" title={row.name}>
                            {row.name}
                          </div>
                        </div>
                        {row.subtitle ? (
                          <div className="text-[10px] text-muted-foreground font-normal">
                            {row.subtitle}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-2 py-1 text-right tabular-nums whitespace-nowrap align-top">
                        {row.cpesAffected}/{totalCpes}
                      </td>
                      <td className="px-2 py-1 text-right align-top">
                        <span
                          className={cn(
                            "inline-block px-1.5 py-px rounded text-[10px] font-semibold",
                            severityBadge(row.pctAffected),
                          )}
                        >
                          {row.pctAffected}%
                        </span>
                      </td>
                      <td className="px-2 py-1 text-right tabular-nums font-medium align-top">
                        <div className="flex flex-col items-end">
                          <span className="font-semibold">{row.totalMatches.toLocaleString()}</span>
                          {row.matchFilterHints && row.matchFilterHints.length > 0 ? (
                            <div className="flex gap-1 flex-wrap justify-end">
                              {row.matchFilterHints.map((hint) => (
                                <span
                                  key={hint}
                                  className="text-[9px] text-muted-foreground bg-muted px-1 rounded"
                                >
                                  {hint}
                                </span>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      </td>
                      <td className="px-0 py-1 text-muted-foreground align-top">
                        {isOpen ? (
                          <ExpandLessIcon style={{ fontSize: 14 }} />
                        ) : (
                          <ExpandMoreIcon style={{ fontSize: 14 }} />
                        )}
                      </td>
                    </tr>
                    {isOpen ? (
                      <tr className="border-b bg-muted/10" onClick={(e) => e.stopPropagation()}>
                        <td colSpan={showDomainColumn ? 6 : 5} className="px-3 py-2">
                          <div className="bg-muted/30 rounded-lg p-2 max-h-[240px] overflow-y-auto space-y-2">
                            {row.perCpeCounts.filter((c) => c.count > 0).length > 0 ? (
                              <div>
                                <div className="flex items-center justify-between mb-1">
                                  <p className="text-[10px] font-semibold uppercase text-muted-foreground">
                                    {row.valueComparePattern
                                      ? "CPE pass list (numeric)"
                                      : "Per-CPE breakdown"}
                                  </p>
                                  <div className="text-[9px] text-muted-foreground bg-background px-2 py-0.5 rounded border">
                                    {row.valueComparePattern ? (
                                      <>
                                        {row.totalMatches.toLocaleString()} CPEs passed • cap 1/CPE
                                      </>
                                    ) : (
                                      <>
                                        {row.perCpeCounts.filter((c) => c.count > 0).length} CPEs •{" "}
                                        {row.totalMatches.toLocaleString()} total matches
                                      </>
                                    )}
                                  </div>
                                </div>
                                <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-1">
                                  {row.perCpeCounts
                                    .filter((c) => c.count > 0)
                                    .map((c) => (
                                      <div
                                        key={c.serial}
                                        className="flex items-center justify-between px-1.5 py-0.5 rounded bg-background border border-border text-[10px]"
                                      >
                                        <span className="font-mono truncate mr-1">{c.serial}</span>
                                        <span className="font-semibold tabular-nums">
                                          {c.count.toLocaleString()}
                                        </span>
                                      </div>
                                    ))}
                                </div>
                              </div>
                            ) : null}
                            {row.samples && row.samples.length > 0 ? (
                              <div>
                                <p className="text-[10px] font-semibold uppercase text-muted-foreground mb-1">
                                  Sample log lines
                                </p>
                                <ul className="space-y-1">
                                  {row.samples.map((s, i) => (
                                    <li
                                      key={i}
                                      className="rounded border border-border bg-background p-2 font-mono text-[10px] break-all"
                                    >
                                      {s.source_file ? (
                                        <div className="text-muted-foreground">{s.source_file}</div>
                                      ) : null}
                                      {s.timestamp ? (
                                        <div className="text-muted-foreground">{s.timestamp}</div>
                                      ) : null}
                                      <div>{s.logline || "—"}</div>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
