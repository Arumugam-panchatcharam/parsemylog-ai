/**
 * Log Syntax Highlighter
 * =======================
 * Port of gui/pages/highlighter.py — automatic coloring of timestamps,
 * IPs, MACs, paths, CLI flags, error/warn/info/debug keywords, and
 * bracketed module names (round-robin color per unique module).
 *
 * Works alongside the search highlighter: this function first splits
 * a line into typed segments, renders each with its style, and if a
 * search pattern is active it applies the search overlay inside each
 * segment.
 */

import { createElement, Fragment } from "react";
import type { ReactNode, CSSProperties } from "react";

/* ================================================================
   Pattern definitions (order = priority, first match wins)
   ================================================================ */
interface PatternDef {
  re: RegExp;
  type: string;
}

const PATTERNS: PatternDef[] = [
  // ISO / generic timestamps
  { re: /\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?\b/gi, type: "timestamp" },
  // RFC822 / syslog: "Nov 24 00:53:27"
  { re: /\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\b/gi, type: "timestamp" },
  // HH:MM:SS (not inside MACs)
  { re: /(?<![0-9A-Fa-f:])\b\d{2}:\d{2}:\d{2}(?:\.\d{3})?\b(?![:0-9A-Fa-f])/g, type: "timestamp" },
  // MAC addresses
  { re: /\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b/g, type: "mac" },
  // Bracketed module names [ModuleName]
  { re: /\[([A-Za-z0-9_-]*[A-Za-z][A-Za-z0-9_-]*)\]/g, type: "module" },
  // IPv6
  { re: /\b(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}\b/g, type: "ip" },
  // IPv4
  { re: /\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b/g, type: "ip" },
  // Unix paths
  { re: /(?<!\S)\/(?:[^\s/]+\/)*[^\s/]+/g, type: "path" },
  // Windows paths
  { re: /\b[A-Za-z]:\\(?:[^\s\\]+\\)*[^\s\\]+\b/g, type: "path" },
  // CLI flags
  { re: /--[a-zA-Z][a-zA-Z0-9-]*(?:=[^\s]+)?/g, type: "cli" },
  { re: /(?<!\w)-[a-zA-Z](?![a-zA-Z0-9])/g, type: "cli" },
  // Keywords
  { re: /\b(ERR|ERROR|FATAL|CRITICAL|FAIL|FAILED|EXCEPTION|CRASH|ABORT|PANIC)\b/gi, type: "error" },
  { re: /\b(WARN|WARNING|DEPRECATED|CAUTION|ALERT|DISCONNECTED)\b/gi, type: "warning" },
  { re: /\b(INFO|INFORMATION|NOTICE|SUCCESS|OK|PASS|PASSED|COMPLETE|COMPLETED|CONNECTED)\b/gi, type: "info" },
  { re: /\b(OFF|DEBUG|TRACE|VERBOSE|DETAIL)\b/gi, type: "debug" },
];

/* ================================================================
   Styles — tuned for dark (slate-900) background
   ================================================================ */
const STYLES: Record<string, CSSProperties> = {
  error:     { color: "#f87171", fontWeight: 700, backgroundColor: "rgba(220,53,69,0.15)", padding: "0 3px", borderRadius: 3 },
  warning:   { color: "#fb923c", fontWeight: 700, backgroundColor: "rgba(253,126,20,0.15)", padding: "0 3px", borderRadius: 3 },
  info:      { color: "#34d399", fontWeight: 700, backgroundColor: "rgba(32,201,151,0.12)", padding: "0 3px", borderRadius: 3 },
  debug:     { color: "#4ade80", fontWeight: 600 },
  mac:       { color: "#f472b6", fontWeight: 600, backgroundColor: "rgba(232,62,140,0.1)", padding: "0 3px", borderRadius: 3 },
  ip:        { color: "#a78bfa", fontWeight: 600, backgroundColor: "rgba(111,66,193,0.1)", padding: "0 3px", borderRadius: 3 },
  timestamp: { color: "#fbbf24", fontWeight: 500 },
  path:      { color: "#f472b6", textDecoration: "underline" },
  cli:       { color: "#22d3ee", fontWeight: 500, fontStyle: "italic" as const },
  module:    { fontWeight: 700, padding: "0 4px", borderRadius: 3 },
};

const MODULE_COLORS = ["#f472b6", "#60a5fa", "#34d399", "#fb923c", "#a78bfa", "#4ade80"];
const moduleColorMap = new Map<string, string>();
let moduleColorIdx = 0;

function getModuleColor(name: string): string {
  if (!moduleColorMap.has(name)) {
    moduleColorMap.set(name, MODULE_COLORS[moduleColorIdx % MODULE_COLORS.length]);
    moduleColorIdx++;
  }
  return moduleColorMap.get(name)!;
}

/* ================================================================
   Segment-based highlighter
   ================================================================ */
interface Segment { text: string; type: string | null; }

function segmentLine(line: string): Segment[] {
  // Collect all non-overlapping matches, first-pattern-wins
  const matches: Array<{ start: number; end: number; text: string; type: string }> = [];

  for (const { re, type } of PATTERNS) {
    // Reset lastIndex for every line
    re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(line)) !== null) {
      if (m[0].length === 0) { re.lastIndex++; continue; }
      const start = m.index;
      const end = m.index + m[0].length;
      // Check overlap with existing
      const overlaps = matches.some((e) => !(end <= e.start || start >= e.end));
      if (!overlaps) {
        matches.push({ start, end, text: m[0], type });
      }
    }
  }

  matches.sort((a, b) => a.start - b.start);

  if (matches.length === 0) return [{ text: line, type: null }];

  const segments: Segment[] = [];
  let last = 0;
  for (const m of matches) {
    if (m.start > last) segments.push({ text: line.slice(last, m.start), type: null });
    segments.push({ text: m.text, type: m.type });
    last = m.end;
  }
  if (last < line.length) segments.push({ text: line.slice(last), type: null });
  return segments;
}

/* ================================================================
   Public API
   ================================================================ */

/**
 * Highlight a log line with syntax coloring.
 *
 * If `searchPattern` is provided, matching portions get an additional
 * search-highlight overlay.
 */
export function highlightLogLine(
  line: string,
  searchPattern?: string,
): ReactNode {
  if (!line) return line;

  const segments = segmentLine(line);
  const nodes: ReactNode[] = [];
  let key = 0;

  // Pre-compile search regex if provided
  let searchRe: RegExp | null = null;
  if (searchPattern) {
    try { searchRe = new RegExp(`(${searchPattern})`, "gi"); }
    catch { /* ignore invalid */ }
  }

  for (const seg of segments) {
    const style: CSSProperties = seg.type ? { ...STYLES[seg.type] } : {};
    if (seg.type === "module") {
      const moduleName = seg.text.replace(/[[\]]/g, "");
      style.color = getModuleColor(moduleName);
    }

    if (searchRe && seg.text) {
      // Split this segment's text by search matches
      const parts = seg.text.split(searchRe);
      if (parts.length > 1) {
        const inner: ReactNode[] = [];
        for (let i = 0; i < parts.length; i++) {
          if (!parts[i]) continue;
          if (i % 2 === 1) {
            // Search match — overlay highlight
            inner.push(
              createElement("span", {
                key: `s${key++}`,
                style: { ...style, backgroundColor: "#b45309", color: "#fef3c7", fontWeight: 700, borderRadius: 2, padding: "1px 3px" },
              }, parts[i])
            );
          } else {
            if (seg.type) {
              inner.push(createElement("span", { key: `p${key++}`, style }, parts[i]));
            } else {
              inner.push(parts[i]);
            }
          }
        }
        nodes.push(createElement(Fragment, { key: `f${key++}` }, ...inner));
        continue;
      }
    }

    // No search or no match in this segment
    if (seg.type) {
      nodes.push(createElement("span", { key: key++, style }, seg.text));
    } else {
      nodes.push(seg.text);
    }
  }

  return createElement(Fragment, null, ...nodes);
}
