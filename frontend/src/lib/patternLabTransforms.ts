import type { PatternLabDoc } from "@/api/endpoints";

export type MatcherConditionKind =
  | "logline_contains"
  | "logline_regex"
  | "template_contains"
  | "source_file_glob";

export interface MatcherAndRow {
  kind: MatcherConditionKind;
  value: string;
}

/** One YAML matchers[] element: AND of conditions → one object with multiple keys. */
export interface MatcherOrGroup {
  andRows: MatcherAndRow[];
}

export type DetectType = "missing_followup" | "burst_count" | "ordered_sequence";

export type FieldExtractType = "string" | "number";
export type FieldExtractCondition = "lt" | "gt" | "lte" | "gte" | "eq";

export interface MatcherRegexOption {
  ref: string;
  label: string;
  pattern: string;
}

export interface FieldExtractRule {
  name: string;
  logline_regex: string;
  group: number;
  type: FieldExtractType;
  /** Links to a ``logline_regex`` row in match conditions (``"orIndex-andIndex"``). */
  matcherRef?: string;
  condition?: FieldExtractCondition;
  compare?: string;
}

export function collectMatcherRegexOptions(groups: MatcherOrGroup[]): MatcherRegexOption[] {
  const out: MatcherRegexOption[] = [];
  groups.forEach((g, gi) => {
    g.andRows.forEach((row, ri) => {
      if (row.kind === "logline_regex" && row.value.trim()) {
        const tag = gi === 0 ? "Primary" : `OR ${gi + 1}`;
        out.push({
          ref: `${gi}-${ri}`,
          label: `${tag} · AND ${ri + 1}`,
          pattern: row.value.trim(),
        });
      }
    });
  });
  return out;
}

export function resolveFieldExtractPattern(
  rule: FieldExtractRule,
  options: MatcherRegexOption[],
): string {
  if (rule.matcherRef) {
    const hit = options.find((o) => o.ref === rule.matcherRef);
    if (hit) return hit.pattern;
  }
  return rule.logline_regex.trim();
}

const MATCHER_KEYS: MatcherConditionKind[] = [
  "logline_contains",
  "logline_regex",
  "template_contains",
  "source_file_glob",
];

export function normalizePatternLabDoc(raw: unknown): PatternLabDoc {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { events: {}, issues: {} };
  }
  const o = raw as Record<string, unknown>;
  const events = o.events;
  const issues = o.issues;
  const base: PatternLabDoc = {
    events:
      events && typeof events === "object" && !Array.isArray(events)
        ? { ...(events as Record<string, unknown>) }
        : {},
    issues:
      issues && typeof issues === "object" && !Array.isArray(issues)
        ? { ...(issues as Record<string, unknown>) }
        : {},
  };
  return pruneStaleGroupByInDoc(base);
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

export function newEmptyIssue(): Record<string, unknown> {
  return {
    category: "",
    severity: "medium",
    rca_hint: "",
    detect: {
      type: "missing_followup" as DetectType,
      trigger: "",
      expect: "",
      within_sec: 60,
      group_by: [],
    },
  };
}

/** Union of ``field_extracts[].name`` across all events in the doc. */
export function collectFieldExtractNames(doc: PatternLabDoc): string[] {
  const names = new Set<string>();
  for (const body of Object.values(doc.events || {})) {
    if (!body || typeof body !== "object" || Array.isArray(body)) continue;
    for (const rule of parseFieldExtracts(body as Record<string, unknown>)) {
      if (rule.name.trim()) names.add(rule.name.trim());
    }
  }
  return [...names].sort();
}

export function getGroupByFromDetect(detect: Record<string, unknown>): string[] {
  const raw = detect.group_by;
  if (!Array.isArray(raw)) return [];
  return raw.map((x) => String(x).trim()).filter(Boolean);
}

export function setDetectGroupBy(
  detect: Record<string, unknown>,
  groupBy: string[],
): Record<string, unknown> {
  const next = groupBy.map((x) => x.trim()).filter(Boolean);
  if (next.length === 0) {
    const { group_by: _gb, ...rest } = detect;
    return { ...rest, group_by: [] };
  }
  return { ...detect, group_by: next };
}

/** Drop group_by entries that no longer exist as field extract names on Events. */
export function pruneStaleGroupByInDoc(doc: PatternLabDoc): PatternLabDoc {
  const valid = new Set(collectFieldExtractNames(doc));
  let changed = false;
  const issues: Record<string, unknown> = {};

  for (const [ik, meta] of Object.entries(doc.issues || {})) {
    if (!meta || typeof meta !== "object" || Array.isArray(meta)) {
      issues[ik] = meta;
      continue;
    }
    const m = { ...(meta as Record<string, unknown>) };
    const det = getIssueDetect(m);
    const gb = getGroupByFromDetect(det);
    const pruned = gb.filter((g) => valid.has(g));
    if (pruned.length !== gb.length) {
      m.detect = setDetectGroupBy(det, pruned);
      changed = true;
    }
    issues[ik] = m;
  }

  return changed ? { ...doc, issues } : doc;
}

export function newEmptyEvent(): Record<string, unknown> {
  return {
    source_file_glob: "",
    matchers: orGroupsToMatchers([{ andRows: [{ kind: "logline_contains", value: "" }] }]),
    field_extracts: [],
  };
}

function rowToMatcherEntry(row: MatcherAndRow): Record<string, string> {
  return { [row.kind]: row.value };
}

/** Preserve one YAML matchers[] entry per OR group; multiple AND rows use ``and: [...]``. */
export function orGroupsToMatchers(groups: MatcherOrGroup[]): unknown[] {
  if (groups.length === 0) {
    return [{}];
  }
  return groups.map((g) => {
    const rows = g.andRows.length > 0 ? g.andRows : [{ kind: "logline_contains" as MatcherConditionKind, value: "" }];
    if (rows.length === 1) {
      return rowToMatcherEntry(rows[0]);
    }
    return { and: rows.map(rowToMatcherEntry) };
  });
}

function flatMatcherToAndRows(rec: Record<string, unknown>): MatcherAndRow[] {
  const andRows: MatcherAndRow[] = [];
  for (const k of MATCHER_KEYS) {
    if (k in rec && rec[k] != null) {
      andRows.push({ kind: k, value: String(rec[k]) });
    }
  }
  return andRows;
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
    const andParts = rec.and;
    let andRows: MatcherAndRow[] = [];
    if (Array.isArray(andParts)) {
      for (const part of andParts) {
        if (part && typeof part === "object" && !Array.isArray(part)) {
          andRows.push(...flatMatcherToAndRows(part as Record<string, unknown>));
        }
      }
    } else {
      andRows = flatMatcherToAndRows(rec);
    }
    if (andRows.length === 0) {
      andRows.push({ kind: "logline_contains", value: "" });
    }
    return { andRows };
  });
}

const LEGACY_FIELD_KEYS = ["sta_mac", "wcid", "ifname"] as const;

export function parseFieldExtracts(body: Record<string, unknown>): FieldExtractRule[] {
  const raw = body.field_extracts;
  if (Array.isArray(raw)) {
    const out: FieldExtractRule[] = [];
    for (const item of raw) {
      if (!item || typeof item !== "object" || Array.isArray(item)) continue;
      const r = item as Record<string, unknown>;
      const name = typeof r.name === "string" ? r.name.trim() : "";
      const logline_regex = typeof r.logline_regex === "string" ? r.logline_regex : "";
      if (!name || !logline_regex) continue;
      const group = Math.max(1, Number(r.group) || 1);
      const type: FieldExtractType = r.type === "number" ? "number" : "string";
      const cond = r.condition;
      const condition =
        cond === "lt" || cond === "gt" || cond === "lte" || cond === "gte" || cond === "eq"
          ? cond
          : undefined;
      const matcherRef =
        typeof r.matcher_ref === "string" && r.matcher_ref.trim() ? r.matcher_ref.trim() : undefined;
      out.push({
        name,
        logline_regex,
        group,
        type,
        matcherRef,
        condition,
        compare: condition && r.compare != null ? String(r.compare) : undefined,
      });
    }
    return out;
  }
  const legacy: FieldExtractRule[] = [];
  for (const key of LEGACY_FIELD_KEYS) {
    const block = body[key];
    if (!block || typeof block !== "object" || Array.isArray(block)) continue;
    const b = block as Record<string, unknown>;
    const rx = typeof b.logline_regex === "string" ? b.logline_regex : "";
    if (!rx) continue;
    legacy.push({
      name: key,
      logline_regex: rx,
      group: Math.max(1, Number(b.group) || 1),
      type: key === "sta_mac" ? "string" : "string",
    });
  }
  return legacy;
}

export function serializeFieldExtracts(
  rules: FieldExtractRule[],
  regexOptions: MatcherRegexOption[] = [],
): unknown[] {
  return rules
    .filter((r) => r.name.trim() && resolveFieldExtractPattern(r, regexOptions))
    .map((r) => {
      const pattern = resolveFieldExtractPattern(r, regexOptions);
      const o: Record<string, unknown> = {
        name: r.name.trim(),
        logline_regex: pattern,
        group: r.group,
        type: r.type,
      };
      if (r.matcherRef) o.matcher_ref = r.matcherRef;
      if (r.condition) {
        o.condition = r.condition;
        o.compare = r.compare ?? "";
      }
      return o;
    });
}

export function applyFieldExtractsToBody(
  body: Record<string, unknown>,
  rules: FieldExtractRule[],
): Record<string, unknown> {
  const { sta_mac: _sm, wcid: _wc, ifname: _if, ...rest } = body;
  const groups = matchersToOrGroups(body.matchers);
  return { ...rest, field_extracts: serializeFieldExtracts(rules, collectMatcherRegexOptions(groups)) };
}

export function eventSourceFileGlob(body: Record<string, unknown>): string {
  if (typeof body.source_file_glob === "string") return body.source_file_glob;
  const groups = matchersToOrGroups(body.matchers);
  const hit = groups.flatMap((g) => g.andRows).find((r) => r.kind === "source_file_glob");
  return hit?.value ?? "";
}

export function getIssueDetect(issue: Record<string, unknown> | undefined): Record<string, unknown> {
  const d = issue?.detect;
  if (d && typeof d === "object" && !Array.isArray(d)) return { ...(d as Record<string, unknown>) };
  return { type: "missing_followup", trigger: "", expect: "", within_sec: 60 };
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
  const group_by = getGroupByFromDetect(prev);
  if (next === "missing_followup") {
    return {
      type: next,
      trigger: String(prev.trigger ?? ""),
      expect: String(prev.expect ?? ""),
      within_sec: Number(prev.within_sec ?? 5) || 5,
      group_by,
    };
  }
  if (next === "burst_count") {
    return {
      type: next,
      event: String(prev.event ?? ""),
      min_occurrence: Number(prev.min_occurrence ?? 3) || 3,
      window_sec: Number(prev.window_sec ?? 10) || 10,
      group_by,
    };
  }
  const seq = Array.isArray(prev.sequence) ? prev.sequence.filter((x) => typeof x === "string") : [];
  return {
    type: "ordered_sequence",
    sequence: [...seq],
    max_gap_sec: Number(prev.max_gap_sec ?? 60) || 60,
    group_by,
  };
}

const MATCHER_KIND_LABELS: Record<MatcherConditionKind, string> = {
  logline_contains: "contains",
  logline_regex: "regex",
  template_contains: "template",
  source_file_glob: "file",
};

function truncateSummaryText(value: string, max = 36): string {
  const t = value.trim();
  if (!t) return "—";
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

function formatMatcherRowSummary(row: MatcherAndRow): string {
  const label = MATCHER_KIND_LABELS[row.kind];
  if (row.kind === "logline_regex") {
    return `${label} /${truncateSummaryText(row.value, 28)}/`;
  }
  return `${label}: ${truncateSummaryText(row.value)}`;
}

function summarizeMatcherGroups(groups: MatcherOrGroup[]): string {
  const orBranches: string[] = [];
  for (const g of groups) {
    const rows = g.andRows.filter((r) => r.value.trim() && r.kind !== "source_file_glob");
    if (rows.length === 0) continue;
    orBranches.push(rows.map(formatMatcherRowSummary).join(" AND "));
  }
  if (orBranches.length === 0) return "No match conditions";
  if (orBranches.length === 1) return orBranches[0];
  if (orBranches.length === 2) return `${orBranches[0]} OR ${orBranches[1]}`;
  return `${orBranches[0]} OR ${orBranches[1]} (+${orBranches.length - 2} more OR)`;
}

function summarizeFieldExtractNames(rules: FieldExtractRule[]): string {
  const names = rules.map((r) => r.name.trim()).filter(Boolean);
  if (names.length === 0) return "";
  if (names.length === 1) return `Extract: ${names[0]}`;
  if (names.length <= 3) return `Extracts: ${names.join(", ")}`;
  return `Extracts: ${names.slice(0, 2).join(", ")} (+${names.length - 2} more)`;
}

/** Short multi-line summary for event grid cards. */
export function summarizeEventBodyLines(body: Record<string, unknown>): string[] {
  const lines: string[] = [];
  const glob = eventSourceFileGlob(body);
  const groups = matchersToOrGroups(body.matchers);
  const fieldRules = parseFieldExtracts(body);

  lines.push(summarizeMatcherGroups(groups));

  if (glob.trim()) {
    lines.push(`Log file: ${truncateSummaryText(glob, 40)}`);
  }

  const fieldLine = summarizeFieldExtractNames(fieldRules);
  if (fieldLine) lines.push(fieldLine);

  return lines;
}

export function summarizeEventBody(body: Record<string, unknown>): string {
  return summarizeEventBodyLines(body).join(" · ");
}

export function summarizeIssue(meta: Record<string, unknown>): string {
  const detect = getIssueDetect(meta);
  const dtype = String(detect.type ?? "rule");
  const gb = getGroupByFromDetect(detect);
  const gbSuffix = gb.length > 0 ? ` · group: ${gb.join(", ")}` : " · device-level";
  if (dtype === "missing_followup") {
    const tr = String(detect.trigger ?? "").trim() || "—";
    const ex = String(detect.expect ?? "").trim() || "—";
    return `After ${tr} → expect ${ex}${gbSuffix}`;
  }
  if (dtype === "burst_count") {
    const ev = String(detect.event ?? "").trim() || "—";
    return `Burst: ${ev} (≥${detect.min_occurrence ?? 3} in ${detect.window_sec ?? 10}s)${gbSuffix}`;
  }
  const seq = Array.isArray(detect.sequence) ? detect.sequence.filter((x) => typeof x === "string" && x.trim()) : [];
  const base = seq.length > 0 ? `Sequence: ${seq.join(" → ")}` : "Sequence: (add steps)";
  return `${base}${gbSuffix}`;
}
