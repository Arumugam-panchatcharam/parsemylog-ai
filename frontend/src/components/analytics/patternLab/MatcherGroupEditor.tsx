import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import type { MatcherConditionKind, MatcherOrGroup } from "@/lib/patternLabTransforms";

const KIND_LABELS: Record<MatcherConditionKind, string> = {
  logline_contains: "Line contains",
  logline_regex: "Line matches regex",
  template_contains: "Template contains",
};

interface MatcherGroupEditorProps {
  groups: MatcherOrGroup[];
  onChange: (groups: MatcherOrGroup[]) => void;
  disabled?: boolean;
}

export default function MatcherGroupEditor({ groups, onChange, disabled }: MatcherGroupEditorProps) {
  const updateGroup = (gi: number, next: MatcherOrGroup) => {
    const copy = groups.map((g, i) => (i === gi ? next : g));
    onChange(copy);
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
      <p className="text-xs text-muted-foreground">
        Log lines are matched if <strong>any</strong> group below matches. Inside a group, <strong>all</strong>{" "}
        conditions must match (AND).
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
              {gi === 0 ? "Primary match" : `OR group ${gi + 1}`}
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
          <div className="space-y-2 pl-1 border-l-2 border-border ml-1">
            {group.andRows.map((row, ri) => (
              <div key={ri} className="flex flex-wrap gap-2 items-end">
                <label className="flex flex-col gap-0.5 min-w-[10rem] flex-1">
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Condition</span>
                  <select
                    className="px-2 py-1.5 border border-input rounded-md text-xs bg-background"
                    value={row.kind}
                    disabled={disabled}
                    onChange={(e) => {
                      const kind = e.target.value as MatcherConditionKind;
                      const andRows = group.andRows.map((r, j) =>
                        j === ri ? { ...r, kind } : r,
                      );
                      updateGroup(gi, { andRows });
                    }}
                  >
                    {(Object.keys(KIND_LABELS) as MatcherConditionKind[]).map((k) => (
                      <option key={k} value={k}>
                        {KIND_LABELS[k]}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-0.5 flex-[2] min-w-[12rem]">
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Value</span>
                  <input
                    type="text"
                    className="px-2 py-1.5 border border-input rounded-md text-xs font-mono bg-background"
                    value={row.value}
                    disabled={disabled}
                    onChange={(e) => {
                      const andRows = group.andRows.map((r, j) =>
                        j === ri ? { ...r, value: e.target.value } : r,
                      );
                      updateGroup(gi, { andRows });
                    }}
                    placeholder="Substring or regex pattern"
                  />
                </label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-8 shrink-0"
                  disabled={disabled}
                  onClick={() => {
                    const andRows = group.andRows.filter((_, j) => j !== ri);
                    updateGroup(gi, {
                      andRows:
                        andRows.length > 0
                          ? andRows
                          : [{ kind: "logline_contains" as MatcherConditionKind, value: "" }],
                    });
                  }}
                  aria-label="Remove condition"
                >
                  <DeleteOutlineIcon style={{ fontSize: 16 }} />
                </Button>
              </div>
            ))}
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
              Add AND condition
            </Button>
          </div>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={addOrGroup}>
        <AddIcon style={{ fontSize: 16, marginRight: 4 }} />
        Add OR group
      </Button>
    </div>
  );
}
