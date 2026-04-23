import { useCallback } from "react";
import type { Layout } from "plotly.js";
import { useTheme } from "@/hooks/useTheme";

const COLORS = {
  light: {
    fg: "#202124",
    fgMuted: "#5f6368",
    grid: "rgba(0, 0, 0, 0.12)",
    paper: "#ffffff",
    plot: "#fafafa",
  },
  dark: {
    fg: "#e8eaed",
    fgMuted: "#9aa0a6",
    grid: "rgba(255, 255, 255, 0.12)",
    paper: "#0b0b0c",
    plot: "#121214",
  },
} as const;

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function mergeAxis(
  base: Record<string, unknown> | undefined,
  override: unknown,
): Record<string, unknown> | undefined {
  if (override === undefined) return base;
  if (!isPlainObject(override)) return base;
  const o = override as Record<string, unknown>;
  const b = base ?? {};
  const merged: Record<string, unknown> = { ...b, ...o };
  if (isPlainObject(b.title) && isPlainObject(o.title)) {
    merged.title = { ...b.title, ...o.title };
  }
  if (isPlainObject(b.tickfont) && isPlainObject(o.tickfont)) {
    merged.tickfont = { ...b.tickfont, ...o.tickfont };
  }
  if (isPlainObject(b.titlefont) && isPlainObject(o.titlefont)) {
    merged.titlefont = { ...b.titlefont, ...o.titlefont };
  }
  return merged;
}

/**
 * Baseline Plotly layout for transparent charts on `bg-card` panels.
 */
export function plotlyLayoutBase(isDark: boolean): Partial<Layout> {
  const c = isDark ? COLORS.dark : COLORS.light;
  const axisBase = {
    gridcolor: c.grid,
    zerolinecolor: c.grid,
    tickfont: { color: c.fg, size: 10 },
    title: { font: { color: c.fg, size: 11 } },
    linecolor: c.grid,
  };
  const hoverLabelBg = isDark ? "#1e1e1e" : "#ffffff";
  const hoverLabelText = isDark ? "#e8eaed" : "#202124";
  
  return {
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { color: c.fg, family: "system-ui, sans-serif", size: 12 },
    legend: { font: { color: c.fg, size: 10 } },
    hoverlabel: {
      bgcolor: hoverLabelBg,
      bordercolor: c.grid,
      font: { color: hoverLabelText, family: "system-ui, sans-serif", size: 12 },
      namelength: -1,
    },
    xaxis: axisBase as Partial<Layout["xaxis"]>,
    yaxis: axisBase as Partial<Layout["yaxis"]>,
  };
}

/**
 * Non-transparent plot surface (fleet overview style).
 */
export function plotlyLayoutSolid(isDark: boolean): Partial<Layout> {
  const c = isDark ? COLORS.dark : COLORS.light;
  const base = plotlyLayoutBase(isDark);
  return {
    ...base,
    paper_bgcolor: c.paper,
    plot_bgcolor: c.plot,
  };
}

/**
 * Deep-merge axis/font keys so callers can override titles while keeping theme colors.
 */
export function mergePlotlyLayout(
  isDark: boolean,
  layout: Record<string, unknown>,
  options: { solid?: boolean } = {},
): Record<string, unknown> {
  const base = (options.solid ? plotlyLayoutSolid(isDark) : plotlyLayoutBase(isDark)) as Record<
    string,
    unknown
  >;
  const merged: Record<string, unknown> = { ...base, ...layout };
  merged.font = {
    ...(isPlainObject(base.font) ? base.font : {}),
    ...(isPlainObject(layout.font) ? layout.font : {}),
  };
  const axisKeys = [
    "xaxis",
    "yaxis",
    "xaxis2",
    "yaxis2",
    "xaxis3",
    "yaxis3",
    "yaxis4",
  ] as const;
  const yAxisFallback = isPlainObject(base.yaxis) ? (base.yaxis as Record<string, unknown>) : undefined;
  for (const key of axisKeys) {
    if (layout[key] !== undefined) {
      const baseAxis =
        (isPlainObject(base[key]) ? (base[key] as Record<string, unknown>) : undefined) ??
        (key !== "xaxis" && key !== "xaxis2" && key !== "xaxis3" ? yAxisFallback : undefined);
      merged[key] = mergeAxis(baseAxis, layout[key]);
    }
  }
  if (isPlainObject(layout.legend) && isPlainObject(base.legend)) {
    merged.legend = {
      ...base.legend,
      ...layout.legend,
      font: {
        ...(isPlainObject((base.legend as Record<string, unknown>).font)
          ? ((base.legend as Record<string, unknown>).font as object)
          : {}),
        ...(isPlainObject((layout.legend as Record<string, unknown>).font)
          ? ((layout.legend as Record<string, unknown>).font as object)
          : {}),
      },
    };
  }
  return merged;
}

export function usePlotlyLayoutMerge() {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  return useCallback(
    (layout: Record<string, unknown>, options?: { solid?: boolean }) =>
      mergePlotlyLayout(isDark, layout, options),
    [isDark],
  );
}
