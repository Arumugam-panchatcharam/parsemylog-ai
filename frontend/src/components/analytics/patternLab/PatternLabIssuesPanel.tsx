import type { PatternLabDoc } from "@/api/endpoints";
import { Button } from "@/components/ui/Button";
import {
  defaultGroupBy,
  type DetectType,
  eventCodes,
  getIssueDetect,
  groupByFromDetect,
  newEmptyIssue,
  nextCustomIssueKey,
  normalizePatternLabDoc,
  partsFromGroupBy,
  setDetectGroupBy,
  switchDetectType,
} from "@/lib/patternLabTransforms";
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
  const issueKeys = Object.keys(doc.issues).sort();

  const setIssue = (ik: string, meta: Record<string, unknown>) => {
    const issues = { ...doc.issues, [ik]: meta };
    setDoc(normalizePatternLabDoc({ ...doc, issues }));
  };

  const removeIssue = (ik: string) => {
    const issues = { ...doc.issues };
    delete issues[ik];
    setDoc(normalizePatternLabDoc({ ...doc, issues }));
  };

  const addIssue = () => {
    const ik = nextCustomIssueKey(doc);
    const issues = { ...doc.issues, [ik]: newEmptyIssue() };
    setDoc(normalizePatternLabDoc({ ...doc, issues }));
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap justify-between gap-2 items-start">
        <div className="text-xs text-muted-foreground max-w-2xl space-y-1">
          <p>
            <strong>Rules</strong> describe problems to detect from labeled events. Use event codes from the{" "}
            <strong>Events</strong> tab in dropdowns.
          </p>
          <p>
            <strong>Max gap (sequence)</strong> is the maximum seconds between <em>each pair</em> of consecutive
            events in the chain—not the total span from first to last.
          </p>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={addIssue}>
          <AddIcon style={{ fontSize: 18, marginRight: 4 }} />
          Add rule
        </Button>
      </div>

      {issueKeys.length === 0 ? (
        <p className="text-sm text-muted-foreground border border-border rounded-lg p-6 text-center">
          No rules defined. Add a rule or use Reset to defaults.
        </p>
      ) : (
        <ul className="space-y-4">
          {issueKeys.map((ik) => {
            const raw = doc.issues[ik];
            const meta =
              raw && typeof raw === "object" && !Array.isArray(raw)
                ? (raw as Record<string, unknown>)
                : {};
            const detect = getIssueDetect(meta);
            const dtype = (detect.type as DetectType) || "ordered_sequence";
            const gb = groupByFromDetect(detect);
            const gbParts = partsFromGroupBy(gb.length ? gb : defaultGroupBy());

            return (
              <li key={ik} className="rounded-lg border border-border bg-card p-4 space-y-4">
                <div className="flex flex-wrap gap-3 items-start justify-between">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 flex-1 min-w-0">
                    <label className="flex flex-col gap-0.5">
                      <span className="text-xs font-medium text-muted-foreground">Rule id</span>
                      <input
                        type="text"
                        key={ik}
                        className="px-2 py-1.5 border border-input rounded-md text-sm font-mono bg-background"
                        defaultValue={ik}
                        onBlur={(e) => {
                          const nk = e.target.value.trim().replace(/\s+/g, "_");
                          if (!nk || nk === ik) return;
                          const issues = { ...doc.issues };
                          issues[nk] = issues[ik];
                          delete issues[ik];
                          setDoc(normalizePatternLabDoc({ ...doc, issues }));
                        }}
                      />
                    </label>
                    <label className="flex flex-col gap-0.5">
                      <span className="text-xs font-medium text-muted-foreground">Category</span>
                      <input
                        type="text"
                        className="px-2 py-1.5 border border-input rounded-md text-sm bg-background"
                        placeholder="e.g. association"
                        value={meta.category != null ? String(meta.category) : ""}
                        onChange={(e) =>
                          setIssue(ik, { ...meta, category: e.target.value, detect })
                        }
                      />
                    </label>
                    <label className="flex flex-col gap-0.5">
                      <span className="text-xs font-medium text-muted-foreground">Severity</span>
                      <select
                        className="px-2 py-1.5 border border-input rounded-md text-sm bg-background"
                        value={meta.severity != null ? String(meta.severity) : "medium"}
                        onChange={(e) =>
                          setIssue(ik, { ...meta, severity: e.target.value, detect })
                        }
                      >
                        <option value="high">high</option>
                        <option value="medium">medium</option>
                        <option value="low">low</option>
                      </select>
                    </label>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-destructive shrink-0"
                    onClick={() => removeIssue(ik)}
                  >
                    <DeleteOutlineIcon style={{ fontSize: 18 }} />
                  </Button>
                </div>

                <label className="flex flex-col gap-0.5">
                  <span className="text-xs font-medium text-muted-foreground">Description for operators</span>
                  <textarea
                    className="px-2 py-1.5 border border-input rounded-md text-sm bg-background min-h-[3rem]"
                    value={meta.rca_hint != null ? String(meta.rca_hint) : ""}
                    onChange={(e) =>
                      setIssue(ik, { ...meta, rca_hint: e.target.value, detect })
                    }
                  />
                </label>

                <fieldset className="space-y-2">
                  <legend className="text-xs font-medium text-foreground mb-2">Pattern type</legend>
                  <select
                    className="w-full max-w-md px-2 py-1.5 border border-input rounded-md text-sm bg-background"
                    value={dtype}
                    onChange={(e) => {
                      const next = e.target.value as DetectType;
                      setIssue(ik, { ...meta, detect: switchDetectType(detect, next) });
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

                <div className="flex flex-wrap gap-4 text-xs">
                  <span className="font-medium text-muted-foreground self-center">Group by:</span>
                  {(
                    [
                      ["sta_mac", "STA MAC"],
                      ["ifname", "Interface"],
                      ["wcid", "WCID"],
                    ] as const
                  ).map(([gk, label]) => (
                    <label key={gk} className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={Boolean(gbParts[gk])}
                        onChange={(e) => {
                          const next = { ...gbParts, [gk]: e.target.checked };
                          setIssue(ik, {
                            ...meta,
                            detect: setDetectGroupBy(detect, next),
                          });
                        }}
                      />
                      {label}
                    </label>
                  ))}
                </div>

                {dtype === "missing_followup" ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
                    <label className="flex flex-col gap-0.5">
                      <span className="text-xs text-muted-foreground">After event</span>
                      <select
                        className="px-2 py-1.5 border border-input rounded-md text-xs font-mono bg-background"
                        value={String(detect.trigger ?? "")}
                        onChange={(e) =>
                          setIssue(ik, {
                            ...meta,
                            detect: { ...detect, trigger: e.target.value },
                          })
                        }
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
                        onChange={(e) =>
                          setIssue(ik, {
                            ...meta,
                            detect: { ...detect, expect: e.target.value },
                          })
                        }
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
                          setIssue(ik, {
                            ...meta,
                            detect: { ...detect, within_sec: parseFloat(e.target.value) || 0 },
                          })
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
                        onChange={(e) =>
                          setIssue(ik, {
                            ...meta,
                            detect: { ...detect, event: e.target.value },
                          })
                        }
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
                          setIssue(ik, {
                            ...meta,
                            detect: {
                              ...detect,
                              min_occurrence: parseInt(e.target.value, 10) || 2,
                            },
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
                          setIssue(ik, {
                            ...meta,
                            detect: { ...detect, window_sec: parseFloat(e.target.value) || 0 },
                          })
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
                          setIssue(ik, {
                            ...meta,
                            detect: { ...detect, max_gap_sec: parseFloat(e.target.value) || 0 },
                          })
                        }
                      />
                    </label>
                    <div>
                      <div className="text-xs font-medium text-muted-foreground mb-2">Event order</div>
                      <ul className="space-y-2">
                        {(Array.isArray(detect.sequence) ? detect.sequence : []).map((step, si) => (
                          <li
                            key={`${ik}-seq-${si}`}
                            className="flex flex-wrap gap-2 items-center border border-border rounded-md p-2 bg-muted/20"
                          >
                            <span className="text-xs text-muted-foreground w-6">{si + 1}.</span>
                            <select
                              className="flex-1 min-w-[10rem] px-2 py-1 border border-input rounded-md text-xs font-mono bg-background"
                              value={typeof step === "string" ? step : ""}
                              onChange={(e) => {
                                const seq = [...(detect.sequence as string[])];
                                seq[si] = e.target.value;
                                setIssue(ik, { ...meta, detect: { ...detect, sequence: seq } });
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
                                setIssue(ik, { ...meta, detect: { ...detect, sequence: seq } });
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
                                setIssue(ik, { ...meta, detect: { ...detect, sequence: seq } });
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
                                setIssue(ik, { ...meta, detect: { ...detect, sequence: seq } });
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
                          setIssue(ik, { ...meta, detect: { ...detect, sequence: seq } });
                        }}
                      >
                        <AddIcon style={{ fontSize: 16, marginRight: 4 }} />
                        Add step
                      </Button>
                    </div>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
