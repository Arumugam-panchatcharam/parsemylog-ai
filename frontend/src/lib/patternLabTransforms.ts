import type { PatternLabDoc } from "@/api/endpoints";

export type MatcherConditionKind = "logline_contains" | "logline_regex" | "template_contains";

export interface MatcherAndRow {
  kind: MatcherConditionKind;
  value: string;
}

/** One YAML matchers[] element: AND of conditions → one object with multiple keys. */
export interface MatcherOrGroup {
  andRows: MatcherAndRow[];
}

export type DetectType = "missing_followup" | "burst_count" | "ordered_sequence";

const MATCHER_KEYS: MatcherConditionKind[] = [
  "logline_contains",
  "logline_regex",
  "template_contains",
];

export function normalizePatternLabDoc(raw: unknown): PatternLabDoc {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { events: {}, issues: {} };
  }
  const o = raw as Record<string, unknown>;
  const events = o.events;
  const issues = o.issues;
  return {
    events:
      events && typeof events === "object" && !Array.isArray(events)
        ? { ...(events as Record<string, unknown>) }
        : {},
    issues:
      issues && typeof issues === "object" && !Array.isArray(issues)
        ? { ...(issues as Record<string, unknown>) }
        : {},
  };
}

export function eventCodes(doc: PatternLabDoc): string[] {
  return Object.keys(doc.events || {}).sort();
}

export function nextCustomIssueKey(doc: PatternLabDoc): string {
  const prefix = "custom_rule_";
  let n = 1;
  const keys = new Set(Object.keys(doc.issues || {}));
  while (keys.has(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

export function nextCustomEventKey(doc: PatternLabDoc): string {
  const prefix = "CUSTOM_EVENT_";
  let n = 1;
  const keys = new Set(Object.keys(doc.events || {}));
  while (keys.has(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

export function defaultGroupBy(): string[] {
  return ["sta_mac", "ifname"];
}

export function newEmptyIssue(): Record<string, unknown> {
  return {
    category: "",
    severity: "medium",
    rca_hint: "",
    detect: {
      type: "ordered_sequence" as DetectType,
      sequence: [] as string[],
      max_gap_sec: 60,
      group_by: defaultGroupBy(),
    },
  };
}

export function newEmptyEvent(): Record<string, unknown> {
  return {
    matchers: orGroupsToMatchers([{ andRows: [{ kind: "logline_contains", value: "" }] }]),
  };
}

export function groupByFromDetect(detect: Record<string, unknown> | undefined): string[] {
  const g = detect?.group_by;
  if (Array.isArray(g) && g.every((x) => typeof x === "string")) return [...g];
  return defaultGroupBy();
}

export function setDetectGroupBy(
  detect: Record<string, unknown>,
  parts: { sta_mac: boolean; ifname: boolean; wcid: boolean },
): Record<string, unknown> {
  const next: string[] = [];
  if (parts.sta_mac) next.push("sta_mac");
  if (parts.ifname) next.push("ifname");
  if (parts.wcid) next.push("wcid");
  if (next.length === 0) next.push(...defaultGroupBy());
  return { ...detect, group_by: next };
}

export function partsFromGroupBy(groupBy: string[]): {
  sta_mac: boolean;
  ifname: boolean;
  wcid: boolean;
} {
  return {
    sta_mac: groupBy.includes("sta_mac"),
    ifname: groupBy.includes("ifname"),
    wcid: groupBy.includes("wcid"),
  };
}

export function orGroupsToMatchers(groups: MatcherOrGroup[]): unknown[] {
  return groups
    .map((g) => {
      const o: Record<string, string> = {};
      for (const row of g.andRows) {
        const v = row.value.trim();
        if (v) o[row.kind] = v;
      }
      return o;
    })
    .filter((o) => Object.keys(o).length > 0);
}

export function matchersToOrGroups(matchers: unknown): MatcherOrGroup[] {
  if (!Array.isArray(matchers) || matchers.length === 0) {
    return [{ andRows: [{ kind: "logline_contains", value: "" }] }];
  }
  return matchers.map((m) => {
    if (!m || typeof m !== "object" || Array.isArray(m)) {
      return { andRows: [{ kind: "logline_contains", value: "" }] };
    }
    const rec = m as Record<string, unknown>;
    const andRows: MatcherAndRow[] = [];
    for (const k of MATCHER_KEYS) {
      if (k in rec && rec[k] != null && String(rec[k]).length > 0) {
        andRows.push({ kind: k, value: String(rec[k]) });
      }
    }
    if (andRows.length === 0) {
      andRows.push({ kind: "logline_contains", value: "" });
    }
    return { andRows };
  });
}

export function getIssueDetect(issue: Record<string, unknown> | undefined): Record<string, unknown> {
  const d = issue?.detect;
  if (d && typeof d === "object" && !Array.isArray(d)) return { ...(d as Record<string, unknown>) };
  return { type: "ordered_sequence", sequence: [], max_gap_sec: 60, group_by: defaultGroupBy() };
}

export function replaceEventCodeInIssues(
  issues: Record<string, unknown>,
  oldCode: string,
  newCode: string,
): Record<string, unknown> {
  if (oldCode === newCode) return issues;
  const out: Record<string, unknown> = {};
  for (const [ik, meta] of Object.entries(issues)) {
    if (!meta || typeof meta !== "object" || Array.isArray(meta)) {
      out[ik] = meta;
      continue;
    }
    const m = { ...(meta as Record<string, unknown>) };
    const det = m.detect;
    if (det && typeof det === "object" && !Array.isArray(det)) {
      const d = { ...(det as Record<string, unknown>) };
      const rep = (v: unknown) => (typeof v === "string" && v === oldCode ? newCode : v);
      if (d.type === "missing_followup") {
        d.trigger = rep(d.trigger);
        d.expect = rep(d.expect);
      } else if (d.type === "burst_count") {
        d.event = rep(d.event);
      } else if (d.type === "ordered_sequence" && Array.isArray(d.sequence)) {
        d.sequence = d.sequence.map((x) => (x === oldCode ? newCode : x));
      }
      m.detect = d;
    }
    out[ik] = m;
  }
  return out;
}

export function renameEventInDoc(doc: PatternLabDoc, oldKey: string, newKey: string): PatternLabDoc {
  const nk = newKey.trim();
  if (!nk || oldKey === nk) return doc;
  const body = doc.events[oldKey];
  if (body === undefined) return doc;
  const events = { ...doc.events };
  delete events[oldKey];
  events[nk] = body;
  return {
    events,
    issues: replaceEventCodeInIssues(doc.issues, oldKey, nk) as Record<string, unknown>,
  };
}

export function deleteEventFromDoc(doc: PatternLabDoc, key: string): PatternLabDoc {
  const events = { ...doc.events };
  delete events[key];
  return { events, issues: doc.issues };
}

export function switchDetectType(prev: Record<string, unknown>, next: DetectType): Record<string, unknown> {
  const gb = groupByFromDetect(prev);
  if (next === "missing_followup") {
    return {
      type: next,
      trigger: String(prev.trigger ?? ""),
      expect: String(prev.expect ?? ""),
      within_sec: Number(prev.within_sec ?? 5) || 5,
      group_by: [...gb],
    };
  }
  if (next === "burst_count") {
    return {
      type: next,
      event: String(prev.event ?? ""),
      min_occurrence: Number(prev.min_occurrence ?? 3) || 3,
      window_sec: Number(prev.window_sec ?? 10) || 10,
      group_by: [...gb],
    };
  }
  const seq = Array.isArray(prev.sequence) ? prev.sequence.filter((x) => typeof x === "string") : [];
  return {
    type: "ordered_sequence",
    sequence: [...seq],
    max_gap_sec: Number(prev.max_gap_sec ?? 60) || 60,
    group_by: [...gb],
  };
}
