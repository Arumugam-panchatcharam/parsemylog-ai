import type { LogRow, TrimMode } from "./types";

/**
 * Append server chunk: keep ascending line order, skip lines already present at the end.
 */
export function mergeRowsAppend(current: readonly LogRow[], incoming: readonly LogRow[]): LogRow[] {
  if (incoming.length === 0) return [...current];
  if (current.length === 0) return [...incoming];
  const cutoff = current[current.length - 1]!.lineNumber;
  const toAdd = incoming.filter((r) => r.lineNumber > cutoff);
  return [...current, ...toAdd];
}

/**
 * Prepend server chunk: only lines strictly before the current first line.
 */
export function mergeRowsPrepend(current: readonly LogRow[], incoming: readonly LogRow[]): LogRow[] {
  if (incoming.length === 0) return [...current];
  if (current.length === 0) return [...incoming];
  const cutoff = current[0]!.lineNumber;
  const toAdd = incoming.filter((r) => r.lineNumber < cutoff);
  toAdd.sort((a, b) => a.lineNumber - b.lineNumber);
  return [...toAdd, ...current];
}

/**
 * Turn raw lines + line numbers into rows with stable ids.
 */
export function toLogRows(lines: readonly string[], lineNumbers: readonly number[]): LogRow[] {
  const out: LogRow[] = [];
  for (let i = 0; i < lines.length; i++) {
    const lineNumber = lineNumbers[i] ?? i + 1;
    out.push({
      id: `L${lineNumber}`,
      lineNumber,
      text: lines[i] ?? "",
    });
  }
  return out;
}

/**
 * Sliding window: drop oldest or newest rows when over `maxLines`.
 * - follow-tail / streaming: evict_head (drop top, keep end)
 * - browsing upward-heavy buffer: evict_tail when prepending caused overflow
 */
export function trimToMaxLines(
  rows: readonly LogRow[],
  maxLines: number,
  mode: TrimMode,
): { rows: LogRow[]; evictedFromHead: number } {
  if (rows.length <= maxLines) {
    return { rows: [...rows], evictedFromHead: 0 };
  }
  const overflow = rows.length - maxLines;
  if (mode === "evict_head") {
    return { rows: rows.slice(overflow), evictedFromHead: overflow };
  }
  return { rows: rows.slice(0, maxLines), evictedFromHead: 0 };
}

/**
 * Append streamed plain lines after `lastLineNumber` (tail). Assigns synthetic line numbers if needed.
 */
export function mergeStreamLines(
  current: readonly LogRow[],
  newLines: readonly string[],
  lastLineNumber: number,
): LogRow[] {
  if (newLines.length === 0) return [...current];
  let n = lastLineNumber;
  const appended: LogRow[] = newLines.map((text) => {
    n += 1;
    return { id: `S${n}`, lineNumber: n, text };
  });
  return [...current, ...appended];
}
