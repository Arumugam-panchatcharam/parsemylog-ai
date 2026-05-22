import { useMemo } from "react";
import type { PatternLabPreviewData, PatternLabPreviewStats } from "@/api/endpoints";
import PatternDistributionDetailTable, {
  type PatternDistributionRow,
} from "@/components/patternAnalyzer/PatternDistributionDetailTable";

interface PatternLabResultsPanelProps {
  result: PatternLabPreviewData | null;
  stats: PatternLabPreviewStats | null;
  error: string | null;
  cpeSerial?: string;
  /** Total CPEs in scope (1 for single-CPE preview; fleet size for fleet scan). */
  totalCpes?: number;
}

export default function PatternLabResultsPanel({
  result,
  stats,
  error,
  cpeSerial,
  totalCpes = 1,
}: PatternLabResultsPanelProps) {
  const summary = result?.summary ?? stats;

  const tableRows: PatternDistributionRow[] = useMemo(() => {
    const rules = result?.rule_rows ?? [];
    const domains =
      (summary?.domains_scanned as string[] | undefined)?.join(", ") || "pattern-lab";
    return rules.map((r) => {
      const matches = Number(r.total_matches ?? 0);
      const perCpe = r.per_cpe ?? [];
      const affected =
        perCpe.filter((c) => c.count > 0).length || (matches > 0 && totalCpes === 1 ? 1 : 0);
      const pct =
        totalCpes > 0 ? Math.round((affected / totalCpes) * 100) : matches > 0 ? 100 : 0;
      return {
        key: r.rule_key,
        domain: domains,
        name: r.rule_key,
        subtitle: r.detect_type ? String(r.detect_type).replace(/_/g, " ") : undefined,
        cpesAffected: affected,
        pctAffected: pct,
        totalMatches: matches,
        perCpeCounts: perCpe.length > 0 ? perCpe : cpeSerial ? [{ serial: cpeSerial, count: matches }] : [],
        samples: r.samples,
      };
    });
  }, [result, summary, cpeSerial, totalCpes]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {error}
      </div>
    );
  }

  if (!result && !stats) return null;

  const total = Number(summary?.total_log_lines ?? summary?.wireless_rows ?? 0);
  const labeled = Number(summary?.labeled_log_lines ?? summary?.labeled_events ?? 0);
  const unlabeled = Number(summary?.unlabeled_log_lines ?? Math.max(0, total - labeled));
  const rulesMatched = summary?.rules_with_matches ?? tableRows.filter((r) => r.totalMatches > 0).length;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        {[
          { label: "Total log lines", value: total },
          { label: "Labeled", value: labeled },
          { label: "Unlabeled", value: unlabeled },
          { label: "Rules matched", value: rulesMatched },
          {
            label: "Raw lines",
            value: summary?.raw_log_lines ?? 0,
            hint:
              (summary?.raw_files_scanned as string[] | undefined)?.length
                ? String((summary?.raw_files_scanned as string[]).join(", "))
                : undefined,
          },
        ].map((item) => (
          <div
            key={item.label}
            className="rounded-md border border-border bg-muted/20 px-3 py-2"
            title={item.hint}
          >
            <div className="text-[10px] uppercase text-muted-foreground">{item.label}</div>
            <div className="text-lg font-semibold tabular-nums">{Number(item.value)}</div>
          </div>
        ))}
      </div>

      {summary?.skipped ? (
        <p className="text-sm text-amber-700 dark:text-amber-300">
          Skipped: {String(summary.reason ?? "no data")}
        </p>
      ) : null}

      {summary?.cpes_scanned != null && Number(summary.cpes_scanned) > 1 ? (
        <p className="text-[11px] text-muted-foreground">
          Fleet scan: {String(summary.cpes_scanned)} CPEs with RG data
          {summary.cpes_failed != null && Number(summary.cpes_failed) > 0
            ? ` · ${String(summary.cpes_failed)} skipped (no data or error)`
            : null}
        </p>
      ) : null}

      <PatternDistributionDetailTable
        rows={tableRows}
        totalCpes={totalCpes}
        title="Rule matches"
        emptyMessage="No rules matched. Adjust events, rules, or group-by fields."
      />

      {totalCpes === 1 && (result?.event_breakdown?.length ?? 0) > 0 ? (
        <PatternDistributionDetailTable
          rows={(result?.event_breakdown ?? []).map((ev) => ({
            key: ev.event_code,
            domain: "events",
            name: ev.event_code,
            cpesAffected: Number(ev.match_count) > 0 ? 1 : 0,
            pctAffected:
              labeled > 0 ? Math.round((Number(ev.match_count) / labeled) * 100) : 0,
            totalMatches: Number(ev.match_count),
            perCpeCounts: cpeSerial
              ? [{ serial: cpeSerial, count: Number(ev.match_count) }]
              : [],
            samples: ev.samples?.map((s) => ({
              timestamp: s.timestamp,
              source_file: s.source_file,
              logline: s.logline,
            })),
          }))}
          totalCpes={totalCpes}
          title="Event labels"
          showDomainColumn={false}
          emptyMessage="No events matched."
        />
      ) : null}
    </div>
  );
}
