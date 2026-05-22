import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import type { MatcherConditionKind, MatcherOrGroup } from "@/lib/patternLabTransforms";

const MATCHER_KINDS: MatcherConditionKind[] = [
  "logline_contains",
  "logline_regex",
  "template_contains",
];

const KIND_LABELS: Record<MatcherConditionKind, string> = {
  logline_contains: "Line contains",
  logline_regex: "Line matches regex",
  template_contains: "Template contains",
  source_file_glob: "Log filename (glob)",
};

function countCaptureGroups(pattern: string): number | null {
  if (!pattern.trim()) return null;
  try {
    const m = pattern.match(/\((?!\?)/g);
    return m ? m.length : 0;
  } catch {
    return null;
  }
}

interface MatcherGroupEditorProps {
  groups: MatcherOrGroup[];
  onChange: (groups: MatcherOrGroup[]) => void;
  disabled?: boolean;
}

export default function MatcherGroupEditor({ groups, onChange, disabled }: MatcherGroupEditorProps) {
  const updateGroup = (gi: number, next: MatcherOrGroup) => {
    onChange(groups.map((g, i) => (i === gi ? next : g)));
  };

  const addOrGroup = () => {
    onChange([...groups, { andRows: [{ kind: "logline_contains", value: "" }] }]);
  };

  const removeOrGroup = (gi: number) => {
    if (groups.length <= 1) return;
    onChange(groups.filter((_, i) => i !== gi));
  };

  return (
    <div className="space-y-3">
      <p className="text-[10px] text-muted-foreground">
        A line gets this event if <strong>any OR group</strong> matches; inside a group, <strong>all AND</strong>{" "}
        conditions must match. Field extraction (below) runs only after that, using its own regex + capture group.
      </p>
      {groups.map((group, gi) => (
        <div
          key={gi}
          className={cn(
            "rounded-md border border-border p-3 space-y-2",
            gi > 0 ? "border-dashed border-primary/40 bg-muted/20" : "bg-muted/30",
          )}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-foreground">
              {gi === 0 ? "Primary match (OR)" : `OR group ${gi + 1}`}
            </span>
            {groups.length > 1 ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 text-destructive"
                disabled={disabled}
                onClick={() => removeOrGroup(gi)}
                aria-label={`Remove OR group ${gi + 1}`}
              >
                <DeleteOutlineIcon style={{ fontSize: 16 }} />
              </Button>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {group.andRows.map((row, ri) => {
              const groupsHint =
                row.kind === "logline_regex" ? countCaptureGroups(row.value) : null;
              return (
                <div
                  key={`${gi}-and-${ri}`}
                  className="flex flex-wrap items-end gap-2 rounded-md border border-border/80 bg-background px-2 py-2 min-w-[14rem] flex-1"
                >
                  <label className="flex flex-col gap-0.5 min-w-[7.5rem]">
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      Condition
                    </span>
                    <select
                      className="px-2 py-1.5 border border-input rounded-md text-xs bg-background h-8"
                      value={row.kind}
                      disabled={disabled}
                      onChange={(e) => {
                        const kind = e.target.value as MatcherConditionKind;
                        updateGroup(gi, {
                          andRows: group.andRows.map((r, j) => (j === ri ? { ...r, kind } : r)),
                        });
                      }}
                    >
                      {MATCHER_KINDS.map((k) => (
                        <option key={k} value={k}>
                          {KIND_LABELS[k]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex flex-col gap-0.5 flex-1 min-w-[8rem]">
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      Value
                    </span>
                    <input
                      type="text"
                      className="px-2 py-1.5 border border-input rounded-md text-xs font-mono bg-background h-8"
                      value={row.value}
                      disabled={disabled}
                      onChange={(e) => {
                        updateGroup(gi, {
                          andRows: group.andRows.map((r, j) =>
                            j === ri ? { ...r, value: e.target.value } : r,
                          ),
                        });
                      }}
                      placeholder={
                        row.kind === "logline_regex" ? "Regex with (capture groups)" : "Pattern"
                      }
                    />
                  </label>
                  {row.kind === "logline_regex" ? (
                    <label className="flex flex-col gap-0.5 w-[4.5rem]">
                      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                        Groups
                      </span>
                      <span
                        className="h-8 flex items-center justify-center rounded-md border border-input bg-muted/40 text-xs font-mono tabular-nums"
                        title="Number of capture groups in this regex (for field extraction below)"
                      >
                        {groupsHint != null ? groupsHint : "—"}
                      </span>
                    </label>
                  ) : null}
                </div>
              );
            })}
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8"
            disabled={disabled}
            onClick={() => {
              updateGroup(gi, {
                andRows: [...group.andRows, { kind: "logline_contains", value: "" }],
              });
            }}
          >
            <AddIcon style={{ fontSize: 16, marginRight: 4 }} />
            Add AND
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={addOrGroup}>
        <AddIcon style={{ fontSize: 16, marginRight: 4 }} />
        Add OR group
      </Button>
    </div>
  );
}
