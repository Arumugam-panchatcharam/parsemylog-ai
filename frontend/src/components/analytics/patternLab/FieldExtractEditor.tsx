import { Button } from "@/components/ui/Button";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import type {
  FieldExtractCondition,
  FieldExtractRule,
  FieldExtractType,
  MatcherRegexOption,
} from "@/lib/patternLabTransforms";
import { resolveFieldExtractPattern } from "@/lib/patternLabTransforms";

const CONDITIONS: { value: FieldExtractCondition; label: string }[] = [
  { value: "eq", label: "=" },
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
];

interface FieldExtractEditorProps {
  rules: FieldExtractRule[];
  regexOptions: MatcherRegexOption[];
  onChange: (rules: FieldExtractRule[]) => void;
}

export default function FieldExtractEditor({ rules, regexOptions, onChange }: FieldExtractEditorProps) {
  const updateRule = (idx: number, next: FieldExtractRule) => {
    onChange(rules.map((r, i) => (i === idx ? next : r)));
  };

  const addRule = () => {
    const firstRef = regexOptions[0]?.ref;
    onChange([
      ...rules,
      {
        name: `field_${rules.length + 1}`,
        logline_regex: firstRef ? regexOptions[0].pattern : "(.+)",
        matcherRef: firstRef,
        group: 1,
        type: "string",
      },
    ]);
  };

  return (
    <div className="space-y-2">
      <p className="text-[10px] text-muted-foreground">
        Runs <strong>after</strong> match conditions label the line. Pick a <strong>Line matches regex</strong> from
        above (or custom regex). <strong>Group</strong> is the capture group index (1, 2, …). Optional condition
        can also reject the event label.
      </p>
      {rules.length === 0 ? (
        <p className="text-xs text-muted-foreground italic">No field extracts.</p>
      ) : (
        <ul className="space-y-2">
          {rules.map((rule, idx) => {
            const useMatcher = Boolean(rule.matcherRef);
            const resolved = resolveFieldExtractPattern(rule, regexOptions);
            return (
              <li
                key={`${rule.name}-${idx}`}
                className="border border-border rounded-md p-2 bg-muted/20 space-y-2"
              >
                <div className="flex flex-wrap gap-2 items-end">
                  <label className="flex flex-col gap-0.5 min-w-[7rem]">
                    <span className="text-[10px] uppercase text-muted-foreground">Field name</span>
                    <input
                      type="text"
                      className="px-2 py-1 border border-input rounded-md text-xs font-mono bg-background h-8"
                      value={rule.name}
                      onChange={(e) =>
                        updateRule(idx, { ...rule, name: e.target.value.replace(/\s+/g, "_") })
                      }
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 min-w-[10rem] flex-1">
                    <span className="text-[10px] uppercase text-muted-foreground">Match regex from</span>
                    <select
                      className="px-2 py-1 border border-input rounded-md text-xs bg-background h-8"
                      value={rule.matcherRef ?? ""}
                      onChange={(e) => {
                        const ref = e.target.value;
                        if (!ref) {
                          updateRule(idx, { ...rule, matcherRef: undefined });
                          return;
                        }
                        const hit = regexOptions.find((o) => o.ref === ref);
                        updateRule(idx, {
                          ...rule,
                          matcherRef: ref,
                          logline_regex: hit?.pattern ?? rule.logline_regex,
                        });
                      }}
                    >
                      <option value="">Custom regex…</option>
                      {regexOptions.map((o) => (
                        <option key={o.ref} value={o.ref}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {!useMatcher ? (
                    <label className="flex flex-col gap-0.5 flex-[2] min-w-[10rem]">
                      <span className="text-[10px] uppercase text-muted-foreground">Custom regex</span>
                      <input
                        type="text"
                        className="px-2 py-1 border border-input rounded-md text-xs font-mono bg-background h-8"
                        value={rule.logline_regex}
                        placeholder="e.g. rssi=(-?\\d+)"
                        onChange={(e) =>
                          updateRule(idx, { ...rule, logline_regex: e.target.value, matcherRef: undefined })
                        }
                      />
                    </label>
                  ) : (
                    <label className="flex flex-col gap-0.5 flex-[2] min-w-[10rem]">
                      <span className="text-[10px] uppercase text-muted-foreground">Regex pattern</span>
                      <input
                        type="text"
                        readOnly
                        className="px-2 py-1 border border-input rounded-md text-xs font-mono bg-muted/50 h-8"
                        value={resolved}
                        title="Linked to match condition above"
                      />
                    </label>
                  )}
                  <label className="flex flex-col gap-0.5 w-[4rem]">
                    <span className="text-[10px] uppercase text-muted-foreground">Group</span>
                    <input
                      type="number"
                      min={1}
                      step={1}
                      className="px-2 py-1 border border-input rounded-md text-xs bg-background h-8"
                      value={rule.group}
                      onChange={(e) =>
                        updateRule(idx, {
                          ...rule,
                          group: Math.max(1, parseInt(e.target.value, 10) || 1),
                        })
                      }
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 w-[5.5rem]">
                    <span className="text-[10px] uppercase text-muted-foreground">Type</span>
                    <select
                      className="px-2 py-1 border border-input rounded-md text-xs bg-background h-8"
                      value={rule.type}
                      onChange={(e) =>
                        updateRule(idx, { ...rule, type: e.target.value as FieldExtractType })
                      }
                    >
                      <option value="string">string</option>
                      <option value="number">number</option>
                    </select>
                  </label>
                  <label className="flex flex-col gap-0.5 w-[5rem]">
                    <span className="text-[10px] uppercase text-muted-foreground">Cond.</span>
                    <select
                      className="px-2 py-1 border border-input rounded-md text-xs bg-background h-8"
                      value={rule.condition ?? ""}
                      onChange={(e) => {
                        const v = e.target.value as FieldExtractCondition | "";
                        updateRule(idx, {
                          ...rule,
                          condition: v || undefined,
                          compare: v ? (rule.compare ?? "") : undefined,
                        });
                      }}
                    >
                      <option value="">—</option>
                      {CONDITIONS.map((c) => (
                        <option key={c.value} value={c.value}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex flex-col gap-0.5 min-w-[5rem]">
                    <span className="text-[10px] uppercase text-muted-foreground">Compare</span>
                    <input
                      type="text"
                      className="px-2 py-1 border border-input rounded-md text-xs font-mono bg-background h-8"
                      value={rule.compare ?? ""}
                      disabled={!rule.condition}
                      onChange={(e) => updateRule(idx, { ...rule, compare: e.target.value })}
                    />
                  </label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 text-destructive shrink-0"
                    onClick={() => onChange(rules.filter((_, i) => i !== idx))}
                    aria-label="Remove field extract"
                  >
                    <DeleteOutlineIcon style={{ fontSize: 16 }} />
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {regexOptions.length === 0 ? (
        <p className="text-[10px] text-amber-700 dark:text-amber-300">
          Add a <strong>Line matches regex</strong> condition above to link field extraction to it.
        </p>
      ) : null}
      <Button type="button" variant="outline" size="sm" className="h-8" onClick={addRule}>
        <AddIcon style={{ fontSize: 16, marginRight: 4 }} />
        Add field extract
      </Button>
    </div>
  );
}
