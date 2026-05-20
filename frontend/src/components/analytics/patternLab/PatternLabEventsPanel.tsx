import { useMemo, useState } from "react";
import type { PatternLabDoc } from "@/api/endpoints";
import { Button } from "@/components/ui/Button";
import {
  matchersToOrGroups,
  nextCustomEventKey,
  newEmptyEvent,
  normalizePatternLabDoc,
  orGroupsToMatchers,
  renameEventInDoc,
} from "@/lib/patternLabTransforms";
import MatcherGroupEditor from "@/components/analytics/patternLab/MatcherGroupEditor";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";

interface PatternLabEventsPanelProps {
  doc: PatternLabDoc;
  setDoc: (next: PatternLabDoc) => void;
}

export default function PatternLabEventsPanel({ doc, setDoc }: PatternLabEventsPanelProps) {
  const sortedKeys = useMemo(() => Object.keys(doc.events).sort(), [doc.events]);
  const [openAdvanced, setOpenAdvanced] = useState<Record<string, boolean>>({});

  const setEventRaw = (key: string, body: Record<string, unknown>) => {
    const events = { ...doc.events, [key]: body };
    setDoc(normalizePatternLabDoc({ ...doc, events }));
  };

  const addEvent = () => {
    const key = nextCustomEventKey(doc);
    const events = { ...doc.events, [key]: newEmptyEvent() };
    setDoc(normalizePatternLabDoc({ ...doc, events }));
  };

  const removeEvent = (key: string) => {
    const events = { ...doc.events };
    delete events[key];
    setDoc(normalizePatternLabDoc({ ...doc, events }));
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap justify-between gap-2 items-start">
        <p className="text-xs text-muted-foreground max-w-2xl">
          Each <strong>event code</strong> labels matching log lines so issues can reference them (sequences,
          triggers, bursts).
        </p>
        <Button type="button" variant="outline" size="sm" onClick={addEvent}>
          <AddIcon style={{ fontSize: 18, marginRight: 4 }} />
          Add event
        </Button>
      </div>

      {sortedKeys.length === 0 ? (
        <p className="text-sm text-muted-foreground border border-border rounded-lg p-6 text-center">
          No events defined. Add an event or use Reset to defaults.
        </p>
      ) : (
        <ul className="space-y-3">
          {sortedKeys.map((key) => {
            const raw = doc.events[key];
            const body =
              raw && typeof raw === "object" && !Array.isArray(raw)
                ? (raw as Record<string, unknown>)
                : {};
            const groups = matchersToOrGroups(body.matchers);
            const advOpen = !!openAdvanced[key];

            const sta = body.sta_mac;
            const staMac =
              sta && typeof sta === "object" && !Array.isArray(sta)
                ? (sta as Record<string, unknown>)
                : {};
            const ifname =
              body.ifname && typeof body.ifname === "object" && !Array.isArray(body.ifname)
                ? (body.ifname as Record<string, unknown>)
                : {};
            const wcid =
              body.wcid && typeof body.wcid === "object" && !Array.isArray(body.wcid)
                ? (body.wcid as Record<string, unknown>)
                : {};

            return (
              <li key={key} className="rounded-lg border border-border bg-card overflow-hidden">
                <div className="px-3 py-2 bg-muted/40 border-b border-border flex flex-wrap gap-2 items-center">
                    <label className="flex flex-col gap-0.5 flex-1 min-w-[12rem]">
                      <span className="text-[10px] uppercase text-muted-foreground">Event code</span>
                      <input
                        type="text"
                        className="px-2 py-1 border border-input rounded-md text-sm font-mono bg-background"
                        key={key}
                        defaultValue={key}
                        onBlur={(e) => {
                          const nk = e.target.value.trim().replace(/\s+/g, "_");
                          if (nk && nk !== key) setDoc(renameEventInDoc(doc, key, nk));
                        }}
                      />
                    </label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-destructive"
                    onClick={() => removeEvent(key)}
                  >
                    <DeleteOutlineIcon style={{ fontSize: 18 }} />
                  </Button>
                </div>
                <div className="p-3 space-y-4">
                  <MatcherGroupEditor
                    groups={groups}
                    onChange={(g) =>
                      setEventRaw(key, {
                        ...body,
                        matchers: orGroupsToMatchers(g),
                      })
                    }
                  />
                  <div>
                    <button
                      type="button"
                      className="flex items-center gap-1 text-xs font-medium text-primary"
                      onClick={() => setOpenAdvanced((m) => ({ ...m, [key]: !m[key] }))}
                    >
                      {advOpen ? (
                        <ExpandLessIcon style={{ fontSize: 18 }} />
                      ) : (
                        <ExpandMoreIcon style={{ fontSize: 18 }} />
                      )}
                      Field extraction (optional)
                    </button>
                    {advOpen ? (
                      <div className="mt-3 space-y-3 pl-2 border-l-2 border-border">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <label className="flex flex-col gap-0.5">
                            <span className="text-xs text-muted-foreground">STA MAC regex (capture)</span>
                            <input
                              type="text"
                              className="px-2 py-1 border border-input rounded-md text-xs font-mono bg-background"
                              placeholder="(?i)from (...mac...)"
                              value={staMac.logline_regex != null ? String(staMac.logline_regex) : ""}
                              onChange={(e) => {
                                const rx = e.target.value;
                                const nextSta: Record<string, unknown> = {};
                                if (rx.trim()) nextSta.logline_regex = rx;
                                if (staMac.param_index !== undefined && typeof staMac.param_index === "number")
                                  nextSta.param_index = staMac.param_index;
                                const nextBody: Record<string, unknown> = {
                                  ...body,
                                  matchers: orGroupsToMatchers(groups),
                                };
                                if (Object.keys(nextSta).length > 0) nextBody.sta_mac = nextSta;
                                else delete nextBody.sta_mac;
                                setEventRaw(key, nextBody);
                              }}
                            />
                          </label>
                          <label className="flex flex-col gap-0.5">
                            <span className="text-xs text-muted-foreground">
                              Drain param index <span className="tabular-nums">(optional)</span>
                            </span>
                            <input
                              type="number"
                              min={0}
                              step={1}
                              className="px-2 py-1 border border-input rounded-md text-xs bg-background"
                              value={staMac.param_index !== undefined ? Number(staMac.param_index) : ""}
                              placeholder="e.g. 3"
                              onChange={(e) => {
                                const v = e.target.value;
                                const n = v === "" ? undefined : parseInt(v, 10);
                                const nextSta: Record<string, unknown> = {};
                                if (staMac.logline_regex) nextSta.logline_regex = staMac.logline_regex;
                                if (n !== undefined && !Number.isNaN(n)) nextSta.param_index = n;
                                const nextBody: Record<string, unknown> = {
                                  ...body,
                                  matchers: orGroupsToMatchers(groups),
                                };
                                if (Object.keys(nextSta).length > 0) nextBody.sta_mac = nextSta;
                                else delete nextBody.sta_mac;
                                setEventRaw(key, nextBody);
                              }}
                            />
                          </label>
                        </div>
                        <label className="flex flex-col gap-0.5 max-w-xl">
                          <span className="text-xs text-muted-foreground">Interface name regex</span>
                          <input
                            type="text"
                            className="px-2 py-1 border border-input rounded-md text-xs font-mono bg-background"
                            value={ifname.logline_regex != null ? String(ifname.logline_regex) : ""}
                            onChange={(e) => {
                              const nextBody: Record<string, unknown> = {
                                ...body,
                                matchers: orGroupsToMatchers(groups),
                              };
                              if (e.target.value.trim()) nextBody.ifname = { logline_regex: e.target.value };
                              else delete nextBody.ifname;
                              setEventRaw(key, nextBody);
                            }}
                          />
                        </label>
                        <label className="flex flex-col gap-0.5 max-w-xl">
                          <span className="text-xs text-muted-foreground">WCID regex</span>
                          <input
                            type="text"
                            className="px-2 py-1 border border-input rounded-md text-xs font-mono bg-background"
                            value={wcid.logline_regex != null ? String(wcid.logline_regex) : ""}
                            onChange={(e) => {
                              const nextBody: Record<string, unknown> = {
                                ...body,
                                matchers: orGroupsToMatchers(groups),
                              };
                              if (e.target.value.trim()) nextBody.wcid = { logline_regex: e.target.value };
                              else delete nextBody.wcid;
                              setEventRaw(key, nextBody);
                            }}
                          />
                        </label>
                      </div>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
