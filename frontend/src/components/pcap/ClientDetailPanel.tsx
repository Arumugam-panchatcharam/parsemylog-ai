import { useQuery } from "@tanstack/react-query";
import Plot from "react-plotly.js";
import { pcapApi } from "@/api/endpoints";
import type { PcapClientDetail } from "@/api/endpoints";
import CircularProgress from "@mui/material/CircularProgress";
import { usePlotlyLayoutMerge } from "@/lib/plotlyTheme";

function epochToTime(epoch: number): string {
  return new Date(epoch * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

const PLOT_CFG = { displayModeBar: false, responsive: true } as const;

interface Props {
  mac: string;
  filename: string;
}

export default function ClientDetailPanel({ mac, filename }: Props) {
  const mergePlot = usePlotlyLayoutMerge();
  const { data, isLoading, error } = useQuery({
    queryKey: ["pcap-client-detail", filename, mac],
    queryFn: async () => (await pcapApi.clientDetail(filename, mac)).data,
  });

  if (isLoading) return <div className="flex items-center gap-2 p-4"><CircularProgress size={16} /><span className="text-xs text-muted-foreground">Loading detail for {mac}...</span></div>;
  if (error || !data) return <div className="p-4 text-xs text-destructive">Failed to load detail for {mac}</div>;
  if (data.error) return <div className="p-4 text-xs text-destructive">{data.error}</div>;

  const d: PcapClientDetail = data;
  const apsSeen = d.ap_conversations.length;
  const ftd = d.frame_type_dist;

  return (
    <div className="p-3 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span className="font-mono font-semibold text-sm">{d.mac}</span>
        <span className="text-muted-foreground">Mgmt: {ftd.mgmt} Data: {ftd.data} Ctrl: {ftd.ctrl}</span>
        <span className="text-muted-foreground">Roaming events: {d.roaming.length}</span>
        <span className="text-muted-foreground">Seq gaps: {d.sequence_analysis.seq_gaps.length}</span>
        <span className="text-muted-foreground">Duplicate frames: {d.sequence_analysis.duplicate_frames}</span>
        {apsSeen > 0 && <span className="text-muted-foreground">APs seen: {apsSeen}</span>}
      </div>

      {/* RSSI Over Time */}
      {d.rssi_timeline.length > 0 && (
        <div>
          <h5 className="text-xs font-semibold mb-1">RSSI Over Time</h5>
          <div className="rounded-lg border border-border bg-card p-2" style={{ height: 220 }}>
            <Plot
              data={[
                { x: d.rssi_timeline.map((p) => epochToTime(p.epoch)), y: d.rssi_timeline.map((p) => p.rssi), type: "scatter", mode: "lines", line: { color: "#3b82f6", width: 1.5 }, name: "RSSI" },
              ]}
              layout={mergePlot({
                autosize: true,
                margin: { l: 40, r: 10, t: 10, b: 40 },
                yaxis: { title: { text: "dBm", font: { size: 9 } }, tickfont: { size: 9 } },
                xaxis: { tickangle: -35, tickfont: { size: 9 } },
                shapes: [
                  { type: "rect", xref: "paper", yref: "y", x0: 0, x1: 1, y0: -30, y1: -67, fillcolor: "rgba(16,185,129,0.06)", line: { width: 0 } },
                  { type: "rect", xref: "paper", yref: "y", x0: 0, x1: 1, y0: -67, y1: -75, fillcolor: "rgba(245,158,11,0.06)", line: { width: 0 } },
                  { type: "rect", xref: "paper", yref: "y", x0: 0, x1: 1, y0: -75, y1: -100, fillcolor: "rgba(239,68,68,0.06)", line: { width: 0 } },
                ],
                showlegend: false,
              })}
              config={PLOT_CFG}
              useResizeHandler style={{ width: "100%", height: "100%" }}
            />
          </div>
        </div>
      )}

      {/* Retry Rate Over Time */}
      {d.retry_timeline.length > 0 && (
        <div>
          <h5 className="text-xs font-semibold mb-1">Retry Rate Over Time</h5>
          <div className="rounded-lg border border-border bg-card p-2" style={{ height: 180 }}>
            <Plot
              data={[{ x: d.retry_timeline.map((p) => epochToTime(p.epoch)), y: d.retry_timeline.map((p) => p.retry_pct), type: "scatter", mode: "lines", fill: "tozeroy", line: { color: "#f59e0b" }, name: "Retry %" }]}
              layout={mergePlot({
                autosize: true,
                margin: { l: 40, r: 10, t: 10, b: 40 },
                yaxis: { title: { text: "%", font: { size: 9 } }, tickfont: { size: 9 } },
                xaxis: { tickangle: -35, tickfont: { size: 9 } },
                showlegend: false,
              })}
              config={PLOT_CFG}
              useResizeHandler style={{ width: "100%", height: "100%" }}
            />
          </div>
        </div>
      )}

      {/* Power Management */}
      {d.power_mgmt_timeline.length > 0 && (
        <div>
          <h5 className="text-xs font-semibold mb-1">Power Management (Sleep/Wake)</h5>
          <div className="rounded-lg border border-border bg-card p-2" style={{ height: 180 }}>
            <Plot
              data={[
                { x: d.power_mgmt_timeline.map((p) => epochToTime(p.epoch)), y: d.power_mgmt_timeline.map((p) => p.state), type: "scatter", mode: "lines", line: { shape: "hv", color: "#8b5cf6" }, name: "PS State" },
                ...(d.retry_vs_power.length > 0 ? [{
                  x: d.retry_vs_power.filter((p) => p.retry).map((p) => epochToTime(p.epoch)),
                  y: d.retry_vs_power.filter((p) => p.retry).map(() => 0.5),
                  type: "scatter" as const, mode: "markers" as const,
                  marker: { color: "#ef4444", size: 4, symbol: "diamond" },
                  name: "Retry", yaxis: "y" as const,
                }] : []),
              ]}
              layout={mergePlot({
                autosize: true,
                margin: { l: 40, r: 10, t: 10, b: 40 },
                yaxis: { tickvals: [0, 1], ticktext: ["Active", "PS"], tickfont: { size: 9 } },
                xaxis: { tickangle: -35, tickfont: { size: 9 } },
                showlegend: false,
              })}
              config={PLOT_CFG}
              useResizeHandler style={{ width: "100%", height: "100%" }}
            />
          </div>
        </div>
      )}

      {/* Sequence Numbers */}
      {d.sequence_analysis.seq_timeline.length > 0 && (
        <div>
          <h5 className="text-xs font-semibold mb-1">Sequence Numbers</h5>
          <div className="rounded-lg border border-border bg-card p-2" style={{ height: 220 }}>
            <Plot
              data={[
                { x: d.sequence_analysis.seq_timeline.filter((p) => !p.retry).map((p) => epochToTime(p.epoch)), y: d.sequence_analysis.seq_timeline.filter((p) => !p.retry).map((p) => p.seq), type: "scatter", mode: "markers", marker: { size: 3, color: "#3b82f6" }, name: "Normal" },
                { x: d.sequence_analysis.seq_timeline.filter((p) => p.retry).map((p) => epochToTime(p.epoch)), y: d.sequence_analysis.seq_timeline.filter((p) => p.retry).map((p) => p.seq), type: "scatter", mode: "markers", marker: { size: 3, color: "#f97316" }, name: "Retry" },
                ...(d.sequence_analysis.seq_gaps.length > 0 ? [{
                  x: d.sequence_analysis.seq_gaps.map((g) => epochToTime(g.epoch)),
                  y: d.sequence_analysis.seq_gaps.map((g) => g.actual_seq),
                  type: "scatter" as const, mode: "markers" as const,
                  marker: { size: 6, color: "#ef4444", symbol: "diamond" },
                  name: `Gaps (${d.sequence_analysis.seq_gaps.length})`,
                }] : []),
              ]}
              layout={mergePlot({
                autosize: true,
                margin: { l: 50, r: 10, t: 10, b: 40 },
                yaxis: { title: { text: "Seq #", font: { size: 9 } }, tickfont: { size: 9 } },
                xaxis: { tickangle: -35, tickfont: { size: 9 } },
                showlegend: true,
                legend: { font: { size: 9 }, orientation: "h" as const, y: 1.08, x: 0 },
              })}
              config={PLOT_CFG}
              useResizeHandler style={{ width: "100%", height: "100%" }}
            />
          </div>
        </div>
      )}

      {/* Events */}
      {d.events.length > 0 && (
        <div>
          <h5 className="text-xs font-semibold mb-1">Events ({d.events.length})</h5>
          <div className="overflow-auto max-h-40 border border-border rounded-lg">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 bg-muted">
                <tr>
                  <th className="text-left px-2 py-1 font-semibold text-muted-foreground text-[9px] uppercase">Time</th>
                  <th className="text-left px-2 py-1 font-semibold text-muted-foreground text-[9px] uppercase">Type</th>
                  <th className="text-left px-2 py-1 font-semibold text-muted-foreground text-[9px] uppercase">Peer</th>
                  <th className="text-left px-2 py-1 font-semibold text-muted-foreground text-[9px] uppercase">Dir</th>
                  <th className="text-left px-2 py-1 font-semibold text-muted-foreground text-[9px] uppercase">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {d.events.map((e, i) => (
                  <tr key={i} className="hover:bg-muted/50">
                    <td className="px-2 py-1 text-muted-foreground">{e.epoch ? epochToTime(e.epoch) : "—"}</td>
                    <td className="px-2 py-1 font-medium">{e.event_type}</td>
                    <td className="px-2 py-1 font-mono">{e.peer}</td>
                    <td className="px-2 py-1">{e.direction}</td>
                    <td className="px-2 py-1 text-muted-foreground truncate max-w-[200px]">{e.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* EAPOL Handshakes */}
      {d.eapol_handshakes.length > 0 && (
        <div>
          <h5 className="text-xs font-semibold mb-1">EAPOL Handshakes</h5>
          <div className="flex flex-wrap gap-2">
            {d.eapol_handshakes.map((hs, i) => (
              <div key={i} className={`px-2 py-1 rounded text-[11px] border ${hs.complete ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-400" : "border-amber-500/30 bg-amber-500/5 text-amber-400"}`}>
                <span className="font-mono">{hs.peer}</span>: steps [{hs.steps_seen.join(",")}] {hs.complete ? "✓" : "incomplete"}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
