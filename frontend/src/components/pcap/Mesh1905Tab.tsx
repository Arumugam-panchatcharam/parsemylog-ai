import { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import Plot from "react-plotly.js";
import { pcapApi } from "@/api/endpoints";
import type { Pcap1905Overview } from "@/api/endpoints";
import FilterListIcon from "@mui/icons-material/FilterList";
import CircularProgress from "@mui/material/CircularProgress";

function epochToTime(epoch: number): string {
  return new Date(epoch * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

const CHART_BG = {
  paper_bgcolor: "transparent" as const,
  plot_bgcolor: "transparent" as const,
  font: { size: 10, color: "#9ca3af" },
};

const PLOT_CFG = { displayModeBar: false, responsive: true } as const;
const PIE_COLORS = ["#3b82f6", "#8b5cf6", "#06b6d4", "#f59e0b", "#10b981", "#ef4444", "#ec4899", "#6366f1", "#14b8a6", "#f97316", "#84cc16", "#0ea5e9"];
const BAR_COLORS = ["#3b82f6", "#8b5cf6", "#06b6d4", "#f59e0b", "#10b981", "#ef4444", "#ec4899", "#6366f1", "#14b8a6", "#f97316", "#84cc16", "#0ea5e9"];

interface Filters {
  al_mac: string;
  src: string;
  dst: string;
  exclude_periodic: boolean;
}

const EMPTY_FILTERS: Filters = { al_mac: "", src: "", dst: "", exclude_periodic: false };

function hasActiveFilters(f: Filters): boolean {
  return !!(f.al_mac || f.src || f.dst || f.exclude_periodic);
}

interface Props {
  data: Pcap1905Overview;
  filename: string;
}

export default function Mesh1905Tab({ data: initialData, filename }: Props) {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<Filters>(EMPTY_FILTERS);

  const filtersActive = hasActiveFilters(appliedFilters);

  const { data: filteredData, isFetching } = useQuery({
    queryKey: ["pcap-1905-filtered", filename, appliedFilters],
    queryFn: async () => {
      const res = await pcapApi.mesh1905Detail(filename, {
        al_mac: appliedFilters.al_mac || undefined,
        src: appliedFilters.src || undefined,
        dst: appliedFilters.dst || undefined,
        exclude_periodic: appliedFilters.exclude_periodic || undefined,
      });
      return res.data;
    },
    enabled: filtersActive,
    staleTime: 60_000,
  });

  const data: Pcap1905Overview = filtersActive && filteredData ? filteredData : initialData;

  const applyFilters = useCallback(() => {
    setAppliedFilters({ ...filters });
  }, [filters]);

  const clearFilters = useCallback(() => {
    setFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
  }, []);

  const deviceOptions = useMemo(() =>
    initialData.devices.map((d) => d.al_mac),
    [initialData.devices]
  );

  if (!initialData.has_1905) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2 py-16">
        <p className="text-sm">No IEEE 1905.1 frames detected in this capture</p>
      </div>
    );
  }

  const catEntries = Object.entries(data.category_distribution || {}).sort((a, b) => b[1] - a[1]);
  const hasTimeline = data.timeline.length > 0;

  return (
    <div className="p-4 space-y-6">
      {/* Filter Toolbar */}
      <div className="flex flex-wrap items-end gap-3 p-3 rounded-lg border border-border bg-muted/30">
        <FilterListIcon style={{ fontSize: 16 }} className="text-muted-foreground mt-4" />

        <div className="flex flex-col gap-0.5">
          <label className="text-[9px] uppercase font-semibold text-muted-foreground tracking-wider">Device (AL MAC)</label>
          <select
            value={filters.al_mac}
            onChange={(e) => setFilters((f) => ({ ...f, al_mac: e.target.value }))}
            className="text-[11px] border border-input rounded bg-background px-2 py-1 min-w-[160px]"
          >
            <option value="">All Devices</option>
            {deviceOptions.map((mac) => (
              <option key={mac} value={mac}>{mac}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-0.5">
          <label className="text-[9px] uppercase font-semibold text-muted-foreground tracking-wider">Source MAC</label>
          <input
            value={filters.src}
            onChange={(e) => setFilters((f) => ({ ...f, src: e.target.value }))}
            placeholder="e.g. aa:bb:cc:dd:ee:ff"
            className="text-[11px] border border-input rounded bg-background px-2 py-1 w-[160px] font-mono"
          />
        </div>

        <div className="flex flex-col gap-0.5">
          <label className="text-[9px] uppercase font-semibold text-muted-foreground tracking-wider">Destination MAC</label>
          <input
            value={filters.dst}
            onChange={(e) => setFilters((f) => ({ ...f, dst: e.target.value }))}
            placeholder="e.g. aa:bb:cc:dd:ee:ff"
            className="text-[11px] border border-input rounded bg-background px-2 py-1 w-[160px] font-mono"
          />
        </div>

        <label className="flex items-center gap-1.5 cursor-pointer mt-4">
          <input
            type="checkbox"
            checked={filters.exclude_periodic}
            onChange={(e) => setFilters((f) => ({ ...f, exclude_periodic: e.target.checked }))}
            className="rounded border-input"
          />
          <span className="text-[10px] text-muted-foreground whitespace-nowrap">Hide periodic</span>
        </label>

        <div className="flex items-center gap-1.5 mt-4">
          <button
            onClick={applyFilters}
            className="px-3 py-1 text-[10px] rounded bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
          >
            Apply
          </button>
          {filtersActive && (
            <button
              onClick={clearFilters}
              className="px-2 py-1 text-[10px] rounded border border-border text-muted-foreground font-medium hover:bg-muted transition-colors"
            >
              Clear
            </button>
          )}
          {isFetching && <CircularProgress size={12} />}
        </div>
      </div>

      {/* Device List */}
      <div>
        <h4 className="text-sm font-semibold mb-2">
          1905.1 / EasyMesh Devices
          {filtersActive && <span className="ml-2 text-[10px] font-normal text-muted-foreground">(filtered)</span>}
        </h4>
        <div className="overflow-auto max-h-64 border border-border rounded-lg">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted">
              <tr>
                <th className="text-left px-3 py-2 font-semibold text-muted-foreground text-[10px] uppercase">AL MAC</th>
                <th className="text-left px-2 py-2 font-semibold text-muted-foreground text-[10px] uppercase">ETH Source</th>
                <th className="text-right px-2 py-2 font-semibold text-muted-foreground text-[10px] uppercase">Messages</th>
                <th className="text-left px-2 py-2 font-semibold text-muted-foreground text-[10px] uppercase">Last Seen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.devices.map((d) => (
                <tr
                  key={d.al_mac}
                  className="hover:bg-muted/50 cursor-pointer"
                  onClick={() => {
                    setFilters((f) => ({ ...f, al_mac: d.al_mac }));
                    setAppliedFilters((f) => ({ ...f, al_mac: d.al_mac }));
                  }}
                >
                  <td className="px-3 py-1.5 font-mono">{d.al_mac}</td>
                  <td className="px-2 py-1.5 font-mono text-muted-foreground">{d.eth_src || "—"}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{d.message_count}</td>
                  <td className="px-2 py-1.5 text-muted-foreground">{d.last_seen ? epochToTime(d.last_seen) : "—"}</td>
                </tr>
              ))}
              {data.devices.length === 0 && (
                <tr><td colSpan={4} className="text-center py-4 text-muted-foreground">No devices match current filters</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Category Distribution bar chart */}
      {catEntries.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Category Distribution</h4>
          <div className="rounded-lg border border-border bg-card p-2" style={{ height: 280 }}>
            <Plot
              data={[{
                x: catEntries.map(([cat]) => cat),
                y: catEntries.map(([, cnt]) => cnt),
                type: "bar",
                marker: { color: catEntries.map((_, i) => BAR_COLORS[i % BAR_COLORS.length]) },
                text: catEntries.map(([, cnt]) => String(cnt)),
                textposition: "outside" as const,
                textfont: { size: 9 },
              }]}
              layout={{
                ...CHART_BG, autosize: true,
                margin: { l: 40, r: 10, t: 10, b: 90 },
                xaxis: { tickangle: -45, tickfont: { size: 9 }, showgrid: false },
                yaxis: { showgrid: true, gridcolor: "#374151", tickfont: { size: 9 } },
                showlegend: false,
              }}
              config={PLOT_CFG}
              useResizeHandler style={{ width: "100%", height: "100%" }}
            />
          </div>
        </div>
      )}

      {/* Unanswered Requests */}
      {data.unanswered_queries.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 text-amber-400">Unanswered Requests ({data.unanswered_queries.length})</h4>
          <div className="overflow-auto max-h-48 border border-amber-500/30 rounded-lg">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-muted">
                <tr>
                  <th className="text-left px-3 py-2 font-semibold text-muted-foreground text-[10px] uppercase">Request Type</th>
                  <th className="text-left px-2 py-2 font-semibold text-muted-foreground text-[10px] uppercase">Expected Response</th>
                  <th className="text-left px-2 py-2 font-semibold text-muted-foreground text-[10px] uppercase">Msg ID</th>
                  <th className="text-left px-2 py-2 font-semibold text-muted-foreground text-[10px] uppercase">Sender</th>
                  <th className="text-left px-2 py-2 font-semibold text-muted-foreground text-[10px] uppercase">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.unanswered_queries.map((q, i) => (
                  <tr key={i} className="hover:bg-muted/50">
                    <td className="px-3 py-1.5">{q.query_type}</td>
                    <td className="px-2 py-1.5 text-muted-foreground">{q.expected_response || "—"}</td>
                    <td className="px-2 py-1.5 font-mono">{q.query_id}</td>
                    <td className="px-2 py-1.5 font-mono">{q.sender}</td>
                    <td className="px-2 py-1.5 text-muted-foreground">{q.epoch ? epochToTime(q.epoch) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Message Timeline */}
      {hasTimeline && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Message Timeline</h4>
          <div className="rounded-lg border border-border bg-card p-2" style={{ height: 280 }}>
            <Plot
              data={(() => {
                const byType: Record<string, { x: string[]; y: string[]; text: string[] }> = {};
                data.timeline.forEach((m) => {
                  if (!byType[m.message_type]) byType[m.message_type] = { x: [], y: [], text: [] };
                  byType[m.message_type].x.push(epochToTime(m.epoch));
                  byType[m.message_type].y.push(m.src ? m.src.slice(-8) : "unknown");
                  byType[m.message_type].text.push(`${m.message_type}\n${m.src} → ${m.dst}`);
                });
                return Object.entries(byType).map(([type, d], i) => ({
                  x: d.x, y: d.y, text: d.text,
                  type: "scatter" as const, mode: "markers" as const,
                  marker: { size: 7, color: PIE_COLORS[i % PIE_COLORS.length] },
                  name: type, hoverinfo: "text" as const,
                }));
              })()}
              layout={{
                ...CHART_BG, autosize: true,
                margin: { l: 80, r: 16, t: 10, b: 44 },
                yaxis: { showgrid: false, automargin: true },
                xaxis: { showgrid: true, gridcolor: "#374151", tickangle: -35, tickfont: { size: 9 } },
                showlegend: false,
              }}
              config={PLOT_CFG}
              useResizeHandler style={{ width: "100%", height: "100%" }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
