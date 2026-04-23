/**
 * Deterministic hue from a string — same algorithm as Syslog event timeline markers.
 * Use for scatter/dot colors so traces stay visually distinct and consistent across pages.
 */
export function eventIdChartColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i += 1) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  const hue = h % 360;
  return `hsl(${hue} 62% 42%)`;
}

/** Plotly marker outline that reads on both light and dark plot backgrounds. */
export const SCATTER_MARKER_LINE = "rgba(255,255,255,0.35)" as const;
