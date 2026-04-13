/**
 * Ordered Drain3-style placeholders in a template (left-to-right).
 * Matches `<...>` segments (e.g. `<THREADID>`, `<*>`).
 */
export function extractOrderedMaskTokens(template: string): string[] {
  const tokens: string[] = [];
  const re = /<([^>]+)>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(template)) !== null) {
    tokens.push(m[1]!.trim());
  }
  return tokens;
}

/** Display labels for each index, with duplicate base tokens disambiguated. */
function disambiguatedMaskLabels(template: string): string[] {
  const raw = extractOrderedMaskTokens(template);
  const seen = new Map<string, number>();
  return raw.map((token) => {
    const n = (seen.get(token) ?? 0) + 1;
    seen.set(token, n);
    if (n === 1) return token;
    return `${token} (${n})`;
  });
}

/**
 * Map API `POSITION_n` to a mask label from `template`, or return `position` if unknown.
 */
export function labelForPosition(position: string, template: string): string {
  const m = /^POSITION_(\d+)$/.exec(position);
  if (!m) return position;
  const idx = Number(m[1]);
  const labels = disambiguatedMaskLabels(template);
  if (!Number.isFinite(idx) || idx < 0 || idx >= labels.length) return position;
  return labels[idx]!;
}
