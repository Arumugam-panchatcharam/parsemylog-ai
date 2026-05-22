import { useMemo, useState } from "react";
import type { PatternLabDoc } from "@/api/endpoints";
import PatternLabIconButton from "@/components/analytics/patternLab/PatternLabIconButton";
import { cn } from "@/lib/utils";
import {
  applyFieldExtractsToBody,
  collectMatcherRegexOptions,
  eventSourceFileGlob,
  matchersToOrGroups,
  nextCustomEventKey,
  newEmptyEvent,
  normalizePatternLabDoc,
  orGroupsToMatchers,
  parseFieldExtracts,
  renameEventInDoc,
  serializeFieldExtracts,
  summarizeEventBodyLines,
} from "@/lib/patternLabTransforms";
import FieldExtractEditor from "@/components/analytics/patternLab/FieldExtractEditor";
import MatcherGroupEditor from "@/components/analytics/patternLab/MatcherGroupEditor";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";

interface PatternLabEventsPanelProps {
  doc: PatternLabDoc;
  setDoc: (next: PatternLabDoc) => void;
}

export default function PatternLabEventsPanel({ doc, setDoc }: PatternLabEventsPanelProps) {
  const sortedKeys = useMemo(() => Object.keys(doc.events).sort(), [doc.events]);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const setEventRaw = (key: string, body: Record<string, unknown>) => {
    const events = { ...doc.events, [key]: body };
    setDoc(normalizePatternLabDoc({ ...doc, events }));
  };

  const addEvent = () => {
    const key = nextCustomEventKey(doc);
    const events = { ...doc.events, [key]: newEmptyEvent() };
    setDoc(normalizePatternLabDoc({ ...doc, events }));
    setExpandedKey(key);
  };

  const removeEvent = (key: string) => {
    const events = { ...doc.events };
    delete events[key];
    setDoc(normalizePatternLabDoc({ ...doc, events }));
    if (expandedKey === key) setExpandedKey(null);
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {sortedKeys.map((key) => {
          const raw = doc.events[key];
          const body =
            raw && typeof raw === "object" && !Array.isArray(raw)
              ? (raw as Record<string, unknown>)
              : {};
          const isOpen = expandedKey === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setExpandedKey((prev) => (prev === key ? null : key))}
              className={cn(
                "text-left rounded-lg border p-3 transition-colors min-h-[6.5rem] flex flex-col gap-1",
                isOpen
                  ? "border-primary bg-primary/5 ring-1 ring-primary/30"
                  : "border-border bg-card hover:bg-muted/30",
              )}
            >
              <span className="font-mono text-sm font-medium truncate">{key}</span>
              <div className="flex flex-col gap-0.5 min-w-0">
                {summarizeEventBodyLines(body).map((line, i) => (
                  <span
                    key={i}
                    className="text-[11px] text-muted-foreground line-clamp-2 leading-snug"
                    title={line}
                  >
                    {line}
                  </span>
                ))}
              </div>
            </button>
          );
        })}
        <button
          type="button"
          onClick={addEvent}
          className="rounded-lg border border-dashed border-border bg-transparent hover:bg-muted/30 transition-colors min-h-[5.5rem] flex flex-col items-center justify-center gap-1 text-muted-foreground hover:text-foreground"
        >
          <AddIcon style={{ fontSize: 24 }} />
          <span className="text-sm font-medium">Add event</span>
        </button>
      </div>

      {expandedKey && doc.events[expandedKey] ? (
        <EventEditor
          key={expandedKey}
          eventKey={expandedKey}
              body={
                doc.events[expandedKey] &&
                typeof doc.events[expandedKey] === "object" &&
                !Array.isArray(doc.events[expandedKey])
                  ? (doc.events[expandedKey] as Record<string, unknown>)
                  : {}
              }
              onRemove={() => removeEvent(expandedKey)}
              onRename={(nk) => {
            if (nk && nk !== expandedKey) {
              setDoc(renameEventInDoc(doc, expandedKey, nk));
              setExpandedKey(nk);
            }
          }}
          onChange={(nextBody) => setEventRaw(expandedKey, nextBody)}
        />
      ) : null}
    </div>
  );
}

function EventEditor({
  eventKey,
  body,
  onRemove,
  onRename,
  onChange,
}: {
  eventKey: string;
  body: Record<string, unknown>;
  onRemove: () => void;
  onRename: (newKey: string) => void;
  onChange: (body: Record<string, unknown>) => void;
}) {
  const groups = matchersToOrGroups(body.matchers);
  const fieldRules = parseFieldExtracts(body);
  const fileGlob = eventSourceFileGlob(body);
  const regexOptions = collectMatcherRegexOptions(groups);

  const persistMatchers = (g: ReturnType<typeof matchersToOrGroups>) => {
    const opts = collectMatcherRegexOptions(g);
    onChange({
      ...body,
      source_file_glob: fileGlob,
      matchers: orGroupsToMatchers(g),
      field_extracts: serializeFieldExtracts(fieldRules, opts),
    });
  };

  return (
    <div className="rounded-lg border border-primary/40 bg-card overflow-hidden flex flex-col lg:flex-row">
      <div className="resize-x overflow-auto min-w-[20rem] lg:w-[60%] flex flex-col border-b lg:border-b-0 lg:border-r border-border bg-card pb-2">
        <div className="px-3 py-2 bg-muted/40 border-b border-border space-y-1.5">
          <div className="flex flex-wrap gap-2 items-end">
            <label className="flex flex-col gap-0.5 flex-1 min-w-[10rem]">
              <span className="text-[10px] uppercase text-muted-foreground">Event code</span>
              <input
                type="text"
                className="px-2 py-1 border border-input rounded-md text-sm font-mono bg-background h-8"
                defaultValue={eventKey}
                onBlur={(e) => {
                  const nk = e.target.value.trim().replace(/\s+/g, "_");
                  if (nk) onRename(nk);
                }}
              />
            </label>
            <label className="flex flex-col gap-0.5 flex-[2] min-w-[12rem]">
              <span className="text-[10px] uppercase text-muted-foreground">Log filename (glob)</span>
              <input
                type="text"
                className="px-2 py-1 border border-input rounded-md text-xs font-mono bg-background h-8"
                value={fileGlob}
                placeholder="e.g. *wireless* or syslog*.txt"
                onChange={(e) =>
                  onChange({
                    ...body,
                    source_file_glob: e.target.value,
                    matchers: orGroupsToMatchers(groups),
                    field_extracts: serializeFieldExtracts(fieldRules, regexOptions),
                  })
                }
              />
            </label>
            <div className="flex shrink-0 ml-auto">
              <PatternLabIconButton label="Delete event" variant="destructive" onClick={onRemove}>
                <DeleteOutlineIcon style={{ fontSize: 18 }} />
              </PatternLabIconButton>
            </div>
          </div>
        </div>

        <div className="p-3 space-y-4">
          <section>
            <h4 className="text-xs font-medium text-foreground mb-2">Match conditions</h4>
            <MatcherGroupEditor groups={groups} onChange={persistMatchers} />
          </section>

          <section>
            <h4 className="text-xs font-medium text-foreground mb-2">Field extraction</h4>
            <FieldExtractEditor
              rules={fieldRules}
              regexOptions={regexOptions}
              onChange={(rules) => onChange(applyFieldExtractsToBody(body, rules))}
            />
          </section>
        </div>
      </div>
      <div className="flex-1 min-w-[15rem] flex flex-col bg-muted/10">
        <div className="px-3 py-2 bg-muted/40 border-b border-border">
          <span className="text-[10px] uppercase text-muted-foreground">Raw JSON</span>
        </div>
        <div className="p-3 overflow-auto">
          <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-all">
            {JSON.stringify(body, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}
