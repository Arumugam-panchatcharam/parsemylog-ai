import { useQuery } from "@tanstack/react-query";
import Plot from "react-plotly.js";
import { pcapApi } from "@/api/endpoints";
import type { PcapApDetail } from "@/api/endpoints";
import CircularProgress from "@mui/material/CircularProgress";
import { usePlotlyLayoutMerge } from "@/lib/plotlyTheme";

function epochToTime(epoch: number): string {
  return new Date(epoch * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

const PLOT_CFG = { displayModeBar: false, responsive: true } as const;
const BOX_COLORS = ["#3b82f6", "#8b5cf6", "#06b6d4", "#f59e0b", "#10b981", "#ef4444", "#ec4899", "#6366f1"];

interface Props {
  bssid: string;
  filename: string;
}

export default function APDetailPanel({ bssid, filename }: Props) {
  const mergePlot = usePlotlyLayoutMerge();
  const { data, isLoading, error } = useQuery({
    queryKey: ["pcap-ap-detail", filename, bssid],
    queryFn: async () => (await pcapApi.apDetail(filename, bssid)).data,
  });

  if (isLoading) return <div className="flex items-center gap-2 p-4"><CircularProgress size={16} /><span className="text-xs text-muted-foreground">Loading AP detail...</span></div>;
  if (error || !data) return <div className="p-4 text-xs text-destructive">Failed to load AP detail</div>;
  if (data.error) return <div className="p-4 text-xs text-destructive">{data.error}</div>;

  const d: PcapApDetail = data;
  const totalClients = d.client_metrics.length;
  const maxConnected = d.client_timeline.length > 0 ? Math.max(...d.client_timeline.map((t) => t.connected_clients)) : 0;
  const dtick = maxConnected <= 5 ? 1 : maxConnected <= 15 ? 2 : maxConnected <= 40 ? 5 : 10;

  return (
    <div className="p-3 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span className="font-mono font-semibold text-sm">{d.bssid}</span>
        <span className="text-muted-foreground">Total clients: {totalClients}</span>
        <span className="text-muted-foreground">Max concurrent: {maxConnected}</span>
        {d.channel_info.channel && <span className="text-muted-foreground">Ch {d.channel_info.channel}</span>}
      </div>

      {/* Client Metrics Table */}
      <div>
        <h5 className="text-xs font-semibold mb-1">Client Metrics</h5>
        <div className="overflow-auto max-h-40 border border-border rounded-lg">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-muted">
              <tr>
                <th className="text-left px-2 py-1 font-semibold text-muted-foreground text-[9px] uppercase">MAC</th>
                <th className="text-right px-2 py-1 font-semibold text-muted-foreground text-[9px] uppercase">Avg RSSI</th>
                <th className="text-right px-2 py-1 font-semibold text-muted-foreground text-[9px] uppercase">Retry%</th>
                <th className="text-right px-2 py-1 font-semibold text-muted-foreground text-[9px] uppercase">Frames</th>
                <th className="text-left px-2 py-1 font-semibold text-muted-foreground text-[9px] uppercase">First Seen</th>
                <th className="text-left px-2 py-1 font-semibold text-muted-foreground text-[9px] uppercase">Last Seen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {d.client_metrics.map((cm) => (
                <tr key={cm.mac} className="hover:bg-muted/50">
                  <td className="px-2 py-1 font-mono">{cm.mac}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{cm.avg_rssi != null ? cm.avg_rssi.toFixed(0) : "—"}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{cm.retry_pct.toFixed(1)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{cm.frame_count}</td>
                  <td className="px-2 py-1 text-muted-foreground">{cm.first_seen ? epochToTime(cm.first_seen) : "—"}</td>
                  <td className="px-2 py-1 text-muted-foreground">{cm.last_seen ? epochToTime(cm.last_seen) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* RSSI Distribution per client */}
      {d.rssi_distribution.length > 0 && (
        <div>
          <h5 className="text-xs font-semibold mb-1">Client RSSI Distribution</h5>
          <div className="rounded-lg border border-border bg-card p-2" style={{ height: 280 }}>
            <Plot
              data={[{
                type: "bar" as const,
                x: d.rssi_distribution.map((r) => r.mac.slice(-8)),
                y: d.rssi_distribution.map((r) => r.median),
                error_y: {
                  type: "data" as const,
                  symmetric: false,
                  array: d.rssi_distribution.map((r) => r.max - r.median),
                  arrayminus: d.rssi_distribution.map((r) => r.median - r.min),
                  color: "#9ca3af",
                  thickness: 1,
                },
                marker: { color: d.rssi_distribution.map((_, i) => BOX_COLORS[i % BOX_COLORS.length]) },
                hovertemplate: "%{x}<br>Median: %{y} dBm<br>Min: %{customdata[0]} dBm<br>Max: %{customdata[1]} dBm<extra></extra>",
                customdata: d.rssi_distribution.map((r) => [r.min, r.max]),
              }]}
              layout={mergePlot({
                autosize: true,
                margin: { l: 45, r: 10, t: 10, b: 60 },
                xaxis: { title: { text: "Client MAC", font: { size: 9 } }, tickangle: -45, tickfont: { size: 8 } },
                yaxis: { title: { text: "RSSI (dBm)", font: { size: 9 } }, tickfont: { size: 9 } },
                showlegend: false,
              })}
              config={PLOT_CFG}
              useResizeHandler style={{ width: "100%", height: "100%" }}
            />
          </div>
        </div>
      )}

      {/* Active Clients Over Time */}
      {d.client_timeline.length > 0 && (
        <div>
          <h5 className="text-xs font-semibold mb-1">Active Clients Over Time</h5>
          <div className="rounded-lg border border-border bg-card p-2" style={{ height: 220 }}>
            <Plot
              data={[{ x: d.client_timeline.map((t) => epochToTime(t.epoch)), y: d.client_timeline.map((t) => t.connected_clients), type: "scatter", mode: "lines", line: { shape: "hv", color: "#8b5cf6" }, fill: "tozeroy" }]}
              layout={mergePlot({
                autosize: true,
                margin: { l: 40, r: 10, t: 10, b: 40 },
                yaxis: { title: { text: "Clients", font: { size: 9 } }, tickfont: { size: 9 }, dtick, range: [0, maxConnected + 1] },
                xaxis: { tickangle: -35, tickfont: { size: 9 } },
                showlegend: false,
              })}
              config={PLOT_CFG}
              useResizeHandler style={{ width: "100%", height: "100%" }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
