import Plot from "react-plotly.js";
import type { PcapOverview } from "@/api/endpoints";
import { usePlotlyLayoutMerge } from "@/lib/plotlyTheme";

function epochToTime(epoch: number): string {
  return new Date(epoch * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

const PLOT_CFG = { displayModeBar: false, responsive: true } as const;

interface Props {
  data: PcapOverview;
  onNavigateToClient: () => void;
}

export default function OverviewTab({ data, onNavigateToClient }: Props) {
  const mergePlot = usePlotlyLayoutMerge();
  const h = data.health;
  const ci = data.capture_info;
  const ns = data.network_summary;

  const statusColor = h.status === "CRITICAL" ? "bg-red-500/15 text-red-400 border-red-500/30"
    : h.status === "WARNING" ? "bg-amber-500/15 text-amber-400 border-amber-500/30"
    : "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";

  const stats = [
    { label: "APs", value: ns.ap_count },
    { label: "Clients", value: ns.client_count },
    { label: "SSIDs", value: ns.ssids.length },
    { label: "Duration", value: `${ci.duration.toFixed(1)}s` },
    { label: "Frames", value: ci.total_frames.toLocaleString() },
    { label: "Retry%", value: `${ci.retry_pct.toFixed(1)}%` },
  ];

  return (
    <div className="p-4 space-y-5">
      {/* Health Banner */}
      <div className={`flex items-center gap-4 p-3 rounded-lg border ${statusColor}`}>
        <div className="text-3xl font-bold tabular-nums">{h.score}</div>
        <div>
          <div className="text-sm font-semibold">{h.status}</div>
          <div className="text-xs opacity-80">{h.critical_count} critical, {h.warning_count} warnings</div>
        </div>
        <div className="text-xs opacity-70 ml-auto">{data.protocol_detected}</div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        {stats.map((s) => (
          <div key={s.label} className="rounded-lg border border-border bg-card px-3 py-2 text-center">
            <div className="text-lg font-bold tabular-nums">{s.value}</div>
            <div className="text-[10px] text-muted-foreground uppercase">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Issues */}
      {h.issues.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Issues</h4>
          <div className="space-y-1">
            {h.issues.map((issue, i) => (
              <div
                key={i}
                className={`flex items-center gap-2 px-3 py-1.5 rounded text-xs border ${issue.severity === "critical" ? "border-red-500/30 bg-red-500/5 text-red-400" : "border-amber-500/30 bg-amber-500/5 text-amber-400"}`}
                onClick={issue.affected_mac ? onNavigateToClient : undefined}
                style={{ cursor: issue.affected_mac ? "pointer" : "default" }}
              >
                <span className="font-semibold uppercase text-[9px] w-14">{issue.severity}</span>
                <span className="flex-1">{issue.description}</span>
                {issue.affected_mac && <span className="font-mono text-[10px] opacity-70">{issue.affected_mac}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recommendations */}
      {h.recommendations.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Recommendations</h4>
          <div className="space-y-1">
            {h.recommendations.map((r, i) => (
              <div key={i} className="flex gap-2 px-3 py-1.5 rounded text-xs border border-border bg-card">
                <span className="font-medium text-primary shrink-0">Action:</span>
                <span>{r.action}</span>
                <span className="text-muted-foreground ml-auto shrink-0">({r.reason})</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* EAPOL Handshakes */}
      {data.eapol_handshakes && data.eapol_handshakes.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">EAPOL 4-Way Handshakes</h4>
          <div className="overflow-auto max-h-40 border border-border rounded-lg">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-muted">
                <tr>
                  <th className="text-left px-3 py-1.5 font-semibold text-muted-foreground text-[10px] uppercase">Client</th>
                  <th className="text-left px-2 py-1.5 font-semibold text-muted-foreground text-[10px] uppercase">AP</th>
                  <th className="text-left px-2 py-1.5 font-semibold text-muted-foreground text-[10px] uppercase">Steps</th>
                  <th className="text-left px-2 py-1.5 font-semibold text-muted-foreground text-[10px] uppercase">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.eapol_handshakes.map((hs, i) => (
                  <tr key={i} className="hover:bg-muted/50">
                    <td className="px-3 py-1 font-mono">{hs.client}</td>
                    <td className="px-2 py-1 font-mono text-muted-foreground">{hs.ap}</td>
                    <td className="px-2 py-1 tabular-nums">{hs.steps_seen.join(", ")}</td>
                    <td className="px-2 py-1">
                      {hs.complete
                        ? <span className="text-emerald-400 font-medium">4/4</span>
                        : <span className="text-amber-400 font-medium">Incomplete ({hs.steps_seen.length}/4)</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Activity Timeline */}
      {data.activity_timeline.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Activity Timeline</h4>
          <div className="rounded-lg border border-border bg-card p-2" style={{ height: 250 }}>
            <Plot
              data={[
                { x: data.activity_timeline.map((b) => epochToTime(b.epoch)), y: data.activity_timeline.map((b) => b.mgmt_count), type: "bar", name: "Mgmt", marker: { color: "#3b82f6" } },
                { x: data.activity_timeline.map((b) => epochToTime(b.epoch)), y: data.activity_timeline.map((b) => b.ctrl_count), type: "bar", name: "Ctrl", marker: { color: "#f59e0b" } },
                { x: data.activity_timeline.map((b) => epochToTime(b.epoch)), y: data.activity_timeline.map((b) => b.data_count), type: "bar", name: "Data", marker: { color: "#10b981" } },
              ]}
              layout={mergePlot({
                autosize: true,
                barmode: "stack" as const,
                margin: { l: 40, r: 10, t: 10, b: 40 },
                xaxis: { tickangle: -35, tickfont: { size: 9 } },
                yaxis: { tickfont: { size: 9 } },
                showlegend: true,
                legend: { font: { size: 9 }, orientation: "h" as const, y: 1.08, x: 0 },
              })}
              config={PLOT_CFG}
              useResizeHandler style={{ width: "100%", height: "100%" }}
            />
          </div>
        </div>
      )}

      {/* Channel Distribution */}
      {data.channel_distribution.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Channel Distribution</h4>
          <div className="rounded-lg border border-border bg-card p-2" style={{ height: 220 }}>
            <Plot
              data={[
                { x: data.channel_distribution.map((c) => `Ch ${c.channel}`), y: data.channel_distribution.map((c) => c.frame_count), type: "bar", name: "Frames", marker: { color: "#3b82f6" } },
                { x: data.channel_distribution.map((c) => `Ch ${c.channel}`), y: data.channel_distribution.map((c) => c.retry_pct), type: "scatter", mode: "lines+markers", name: "Retry%", yaxis: "y2", line: { color: "#ef4444" }, marker: { size: 5 } },
              ]}
              layout={mergePlot({
                autosize: true,
                margin: { l: 40, r: 40, t: 10, b: 40 },
                yaxis: { title: { text: "Frames", font: { size: 9 } }, tickfont: { size: 9 } },
                yaxis2: { title: { text: "Retry%", font: { size: 9 } }, tickfont: { size: 9 }, overlaying: "y", side: "right" },
                showlegend: true,
                legend: { font: { size: 9 }, orientation: "h" as const, y: 1.08, x: 0 },
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
