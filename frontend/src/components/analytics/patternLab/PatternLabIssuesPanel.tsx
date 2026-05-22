import { useEffect, useMemo, useState } from "react";
import type { PatternLabDoc } from "@/api/endpoints";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import {
  type DetectType,
  collectFieldExtractNames,
  eventCodes,
  getGroupByFromDetect,
  getIssueDetect,
  newEmptyIssue,
  nextCustomIssueKey,
  normalizePatternLabDoc,
  setDetectGroupBy,
  summarizeIssue,
  switchDetectType,
} from "@/lib/patternLabTransforms";
import PatternLabIconButton from "@/components/analytics/patternLab/PatternLabIconButton";
import AddIcon from "@mui/icons-material/Add";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";

interface PatternLabIssuesPanelProps {
  doc: PatternLabDoc;
  setDoc: (next: PatternLabDoc) => void;
}

const DETECT_OPTIONS: { value: DetectType; label: string; hint: string }[] = [
  {
    value: "ordered_sequence",
    label: "Ordered sequence",
    hint: "Events must occur in order with a max gap between consecutive steps.",
  },
  {
    value: "missing_followup",
    label: "Missing follow-up",
    hint: "After event A, expect event B within a time window.",
  },
  {
    value: "burst_count",
    label: "Burst count",
    hint: "Same event repeats at least N times within a window.",
  },
];

export default function PatternLabIssuesPanel({ doc, setDoc }: PatternLabIssuesPanelProps) {
  const codes = eventCodes(doc);
  const groupByOptions = useMemo(() => collectFieldExtractNames(doc), [doc.events]);
  const issueKeys = useMemo(() => Object.keys(doc.issues).sort(), [doc.issues]);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const setIssue = (ik: string, meta: Record<string, unknown>) => {
    const issues = { ...doc.issues, [ik]: meta };
    setDoc(normalizePatternLabDoc({ ...doc, issues }));
  };

  const removeIssue = (ik: string) => {
    const issues = { ...doc.issues };
    delete issues[ik];
    setDoc(normalizePatternLabDoc({ ...doc, issues }));
    if (expandedKey === ik) setExpandedKey(null);
  };

  const addIssue = () => {
    const ik = nextCustomIssueKey(doc);
    const issues = { ...doc.issues, [ik]: newEmptyIssue() };
    setDoc(normalizePatternLabDoc({ ...doc, issues }));
    setExpandedKey(ik);
  };

  return (
    <div className="space-y-4">
      <div className="text-xs text-muted-foreground max-w-2xl space-y-1">
        <p>
          <strong>Rules</strong> detect problems from labeled events. Use event codes from the{" "}
          <strong>Events</strong> tab in dropdowns.
        </p>
        <p>
          <strong>Max gap (sequence)</strong> is the maximum seconds between each pair of consecutive events—not the
          total span from first to last.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {issueKeys.map((ik) => {
          const raw = doc.issues[ik];
          const meta =
            raw && typeof raw === "object" && !Array.isArray(raw)
              ? (raw as Record<string, unknown>)
              : {};
          const dtype = String(getIssueDetect(meta).type ?? "rule");
          const label = DETECT_OPTIONS.find((o) => o.value === dtype)?.label ?? dtype;
          const isOpen = expandedKey === ik;
          return (
            <button
              key={ik}
              type="button"
              onClick={() => setExpandedKey((prev) => (prev === ik ? null : ik))}
              className={cn(
                "text-left rounded-lg border p-3 transition-colors min-h-[5.5rem] flex flex-col gap-1",
                isOpen
                  ? "border-primary bg-primary/5 ring-1 ring-primary/30"
                  : "border-border bg-card hover:bg-muted/30",
              )}
            >
              <span className="font-mono text-sm font-medium truncate">{ik}</span>
              <span className="text-[10px] uppercase text-muted-foreground">{label}</span>
              <span className="text-[11px] text-muted-foreground line-clamp-2">{summarizeIssue(meta)}</span>
              {meta.category ? (
                <span className="text-[10px] text-muted-foreground truncate">
                  {String(meta.category)} · {String(meta.severity ?? "medium")}
                </span>
              ) : null}
            </button>
          );
        })}
        <button
          type="button"
          onClick={addIssue}
          className="rounded-lg border border-dashed border-border bg-transparent hover:bg-muted/30 transition-colors min-h-[5.5rem] flex flex-col items-center justify-center gap-1 text-muted-foreground hover:text-foreground"
        >
          <AddIcon style={{ fontSize: 24 }} />
          <span className="text-sm font-medium">Add rule</span>
        </button>
      </div>

      {expandedKey && doc.issues[expandedKey] ? (
        <IssueEditor
          issueKey={expandedKey}
          meta={
            doc.issues[expandedKey] && typeof doc.issues[expandedKey] === "object" && !Array.isArray(doc.issues[expandedKey])
              ? (doc.issues[expandedKey] as Record<string, unknown>)
              : {}
          }
              codes={codes}
              groupByOptions={groupByOptions}
              onRemove={() => removeIssue(expandedKey)}
              onRename={(nk) => {
            if (!nk || nk === expandedKey) return;
            const issues = { ...doc.issues };
            issues[nk] = issues[expandedKey];
            delete issues[expandedKey];
            setDoc(normalizePatternLabDoc({ ...doc, issues }));
            setExpandedKey(nk);
          }}
          onChange={(m) => setIssue(expandedKey, m)}
        />
      ) : null}
    </div>
  );
}

function IssueEditor({
  issueKey,
  meta,
  codes,
  groupByOptions,
  onRemove,
  onRename,
  onChange,
}: {
  issueKey: string;
  meta: Record<string, unknown>;
  codes: string[];
  groupByOptions: string[];
  onRemove: () => void;
  onRename: (newKey: string) => void;
  onChange: (meta: Record<string, unknown>) => void;
}) {
  const detect = getIssueDetect(meta);
  const dtype = (detect.type as DetectType) || "ordered_sequence";
  const groupByRaw = getGroupByFromDetect(detect);
  const validNames = new Set(groupByOptions);
  const staleGroupBy = groupByRaw.filter((g) => !validNames.has(g));
  const groupBy = groupByRaw.filter((g) => validNames.has(g));

  useEffect(() => {
    if (staleGroupBy.length > 0) {
      onChange({ ...meta, detect: setDetectGroupBy(detect, groupBy) });
    }
  }, [issueKey, groupByOptions.join("\0"), staleGroupBy.join("\0")]);

  const toggleGroupBy = (name: string) => {
    const next = groupBy.includes(name)
      ? groupBy.filter((g) => g !== name)
      : [...groupBy, name];
    onChange({ ...meta, detect: setDetectGroupBy(detect, next) });
  };

  const clearGrouping = () => {
    onChange({ ...meta, detect: setDetectGroupBy(detect, []) });
  };

  return (
    <div className="rounded-lg border border-primary/40 bg-card overflow-hidden flex flex-col lg:flex-row">
      <div className="resize-x overflow-auto min-w-[20rem] lg:w-[60%] flex flex-col border-b lg:border-b-0 lg:border-r border-border bg-card pb-2">
        <div className="px-3 py-2 bg-muted/40 border-b border-border flex flex-wrap gap-2 items-end">
        <label className="flex flex-col gap-0.5 flex-1 min-w-[8rem]">
          <span className="text-[10px] uppercase text-muted-foreground">Rule id</span>
          <input
            type="text"
            className="px-2 py-1 border border-input rounded-md text-sm font-mono bg-background h-8"
            defaultValue={issueKey}
            onBlur={(e) => {
              const nk = e.target.value.trim().replace(/\s+/g, "_");
              if (nk) onRename(nk);
            }}
          />
        </label>
        <label className="flex flex-col gap-0.5 flex-1 min-w-[8rem]">
          <span className="text-[10px] uppercase text-muted-foreground">Category</span>
          <input
            type="text"
            className="px-2 py-1 border border-input rounded-md text-sm bg-background h-8"
            placeholder="e.g. lifecycle"
            value={meta.category != null ? String(meta.category) : ""}
            onChange={(e) => onChange({ ...meta, category: e.target.value, detect })}
          />
        </label>
        <label className="flex flex-col gap-0.5 w-[7rem]">
          <span className="text-[10px] uppercase text-muted-foreground">Severity</span>
          <select
            className="px-2 py-1 border border-input rounded-md text-sm bg-background h-8"
            value={meta.severity != null ? String(meta.severity) : "medium"}
            onChange={(e) => onChange({ ...meta, severity: e.target.value, detect })}
          >
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="low">low</option>
          </select>
        </label>
        <div className="flex shrink-0 ml-auto">
          <PatternLabIconButton label="Delete rule" variant="destructive" onClick={onRemove}>
            <DeleteOutlineIcon style={{ fontSize: 18 }} />
          </PatternLabIconButton>
        </div>
      </div>

      <div className="p-3 space-y-3">
      <label className="flex flex-col gap-0.5">
        <span className="text-[10px] uppercase text-muted-foreground">Description</span>
        <textarea
          className="px-2 py-1.5 border border-input rounded-md text-sm bg-background min-h-[2.5rem]"
          value={meta.rca_hint != null ? String(meta.rca_hint) : ""}
          onChange={(e) => onChange({ ...meta, rca_hint: e.target.value, detect })}
        />
      </label>

      <fieldset className="space-y-1">
        <legend className="text-xs font-medium text-foreground">Pattern type</legend>
        <select
          className="w-full max-w-md px-2 py-1.5 border border-input rounded-md text-sm bg-background"
          value={dtype}
          onChange={(e) => {
            const next = e.target.value as DetectType;
            onChange({ ...meta, detect: switchDetectType(detect, next) });
          }}
        >
          {DETECT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">
          {DETECT_OPTIONS.find((o) => o.value === dtype)?.hint}
        </p>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium text-foreground">Group by</legend>
        <p className="text-[10px] text-muted-foreground">
          Leave empty for device-level rules (one timeline per CPE). Select field extract names to partition timelines.
        </p>
        {groupByOptions.length === 0 ? (
          <p className="text-xs text-amber-700 dark:text-amber-300">
            Add field extracts on the <strong>Events</strong> tab to enable grouping.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {groupByOptions.map((name) => {
              const checked = groupBy.includes(name);
              return (
                <label
                  key={name}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-mono cursor-pointer",
                    checked
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border bg-background text-muted-foreground hover:bg-muted/30",
                  )}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={checked}
                    onChange={() => toggleGroupBy(name)}
                  />
                  {name}
                </label>
              );
            })}
          </div>
        )}
        {staleGroupBy.length > 0 ? (
          <p className="text-[10px] text-amber-700 dark:text-amber-300">
            Removed stale grouping (field extracts no longer defined):{" "}
            <span className="font-mono">{staleGroupBy.join(", ")}</span>
          </p>
        ) : null}
        {groupBy.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[10px] text-muted-foreground">
              Grouping: <span className="font-mono">{groupBy.join(", ")}</span>
            </p>
            <button
              type="button"
              className="text-[10px] text-primary hover:underline"
              onClick={clearGrouping}
            >
              Clear grouping
            </button>
          </div>
        ) : (
          <p className="text-[10px] text-muted-foreground italic">Device-level (no partition fields)</p>
        )}
      </fieldset>

      {dtype === "missing_followup" ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
          <label className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">After event</span>
            <select
              className="px-2 py-1.5 border border-input rounded-md text-xs font-mono bg-background"
              value={String(detect.trigger ?? "")}
              onChange={(e) => onChange({ ...meta, detect: { ...detect, trigger: e.target.value } })}
            >
              <option value="">—</option>
              {codes.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">Expect event</span>
            <select
              className="px-2 py-1.5 border border-input rounded-md text-xs font-mono bg-background"
              value={String(detect.expect ?? "")}
              onChange={(e) => onChange({ ...meta, detect: { ...detect, expect: e.target.value } })}
            >
              <option value="">—</option>
              {codes.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 sm:col-span-2">
            <span className="text-xs text-muted-foreground">Within (seconds)</span>
            <input
              type="number"
              min={0}
              step={0.1}
              className="px-2 py-1.5 border border-input rounded-md text-sm bg-background"
              value={detect.within_sec != null ? Number(detect.within_sec) : 5}
              onChange={(e) =>
                onChange({ ...meta, detect: { ...detect, within_sec: parseFloat(e.target.value) || 0 } })
              }
            />
          </label>
        </div>
      ) : null}

      {dtype === "burst_count" ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
          <label className="flex flex-col gap-0.5 md:col-span-2">
            <span className="text-xs text-muted-foreground">Event</span>
            <select
              className="px-2 py-1.5 border border-input rounded-md text-xs font-mono bg-background"
              value={String(detect.event ?? "")}
              onChange={(e) => onChange({ ...meta, detect: { ...detect, event: e.target.value } })}
            >
              <option value="">—</option>
              {codes.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">Min occurrences</span>
            <input
              type="number"
              min={2}
              step={1}
              className="px-2 py-1.5 border border-input rounded-md text-sm bg-background"
              value={detect.min_occurrence != null ? Number(detect.min_occurrence) : 3}
              onChange={(e) =>
                onChange({
                  ...meta,
                  detect: { ...detect, min_occurrence: parseInt(e.target.value, 10) || 2 },
                })
              }
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">Window (seconds)</span>
            <input
              type="number"
              min={0}
              step={0.1}
              className="px-2 py-1.5 border border-input rounded-md text-sm bg-background"
              value={detect.window_sec != null ? Number(detect.window_sec) : 10}
              onChange={(e) =>
                onChange({ ...meta, detect: { ...detect, window_sec: parseFloat(e.target.value) || 0 } })
              }
            />
          </label>
        </div>
      ) : null}

      {dtype === "ordered_sequence" ? (
        <div className="space-y-3">
          <label className="flex flex-col gap-0.5 max-w-xs">
            <span className="text-xs text-muted-foreground">Max gap between steps (seconds)</span>
            <input
              type="number"
              min={0}
              step={0.1}
              className="px-2 py-1.5 border border-input rounded-md text-sm bg-background"
              value={detect.max_gap_sec != null ? Number(detect.max_gap_sec) : 60}
              onChange={(e) =>
                onChange({ ...meta, detect: { ...detect, max_gap_sec: parseFloat(e.target.value) || 0 } })
              }
            />
          </label>
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-2">Event order</div>
            <ul className="space-y-2">
              {(Array.isArray(detect.sequence) ? detect.sequence : []).map((step, si) => (
                <li
                  key={`${issueKey}-seq-${si}`}
                  className="flex flex-wrap gap-2 items-center border border-border rounded-md p-2 bg-muted/20"
                >
                  <span className="text-xs text-muted-foreground w-6">{si + 1}.</span>
                  <select
                    className="flex-1 min-w-[10rem] px-2 py-1 border border-input rounded-md text-xs font-mono bg-background"
                    value={typeof step === "string" ? step : ""}
                    onChange={(e) => {
                      const seq = [...(detect.sequence as string[])];
                      seq[si] = e.target.value;
                      onChange({ ...meta, detect: { ...detect, sequence: seq } });
                    }}
                  >
                    <option value="">—</option>
                    {codes.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 px-2"
                    disabled={si === 0}
                    onClick={() => {
                      const seq = [...(detect.sequence as string[])];
                      [seq[si - 1], seq[si]] = [seq[si], seq[si - 1]];
                      onChange({ ...meta, detect: { ...detect, sequence: seq } });
                    }}
                    aria-label="Move up"
                  >
                    <ArrowUpwardIcon style={{ fontSize: 16 }} />
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 px-2"
                    disabled={si >= (detect.sequence as string[]).length - 1}
                    onClick={() => {
                      const seq = [...(detect.sequence as string[])];
                      [seq[si], seq[si + 1]] = [seq[si + 1], seq[si]];
                      onChange({ ...meta, detect: { ...detect, sequence: seq } });
                    }}
                    aria-label="Move down"
                  >
                    <ArrowDownwardIcon style={{ fontSize: 16 }} />
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 px-2 text-destructive"
                    onClick={() => {
                      const seq = (detect.sequence as string[]).filter((_, j) => j !== si);
                      onChange({ ...meta, detect: { ...detect, sequence: seq } });
                    }}
                    aria-label="Remove step"
                  >
                    <DeleteOutlineIcon style={{ fontSize: 16 }} />
                  </Button>
                </li>
              ))}
            </ul>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => {
                const seq = [...(Array.isArray(detect.sequence) ? detect.sequence : []), ""];
                onChange({ ...meta, detect: { ...detect, sequence: seq } });
              }}
            >
              <AddIcon style={{ fontSize: 16, marginRight: 4 }} />
              Add step
            </Button>
          </div>
        </div>
      ) : null}
      </div>
      </div>
      <div className="flex-1 min-w-[15rem] flex flex-col bg-muted/10">
        <div className="px-3 py-2 bg-muted/40 border-b border-border">
          <span className="text-[10px] uppercase text-muted-foreground">Raw JSON</span>
        </div>
        <div className="p-3 overflow-auto">
          <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-all">
            {JSON.stringify(meta, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}
