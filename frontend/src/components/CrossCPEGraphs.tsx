import { useState } from "react";
import Plot from "react-plotly.js";
import type { CPESummary } from "../pages/CPEOverviewPage";
import {
  getMemAvailableStatus,
  getCpuStatus,
  getSUnreclaimStatus,
  getOvercommitStatus,
  getColorConfig,
  getFleetAlertMessage,
  type HealthStatus,
} from "@/utils/healthStatus";
import { usePlotlyLayoutMerge } from "@/lib/plotlyTheme";
import ErrorIcon from "@mui/icons-material/Error";
import SignalCellularAltIcon from "@mui/icons-material/SignalCellularAlt";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";

interface MetricChartData {
  label: string;
  values: (number | null)[];
  unit?: string;
  getStatus: (value: number) => HealthStatus;
  formatValue: (value: number) => string;
}

function getBarColor(value: number | null, getStatus: (v: number) => HealthStatus): string {
  if (value === null) return "#d1d5db";
  const status = getStatus(value);
  const config = getColorConfig(status);
  return config.color;
}

function CollapsibleCard({
  icon,
  title,
  defaultOpen = true,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-4 py-3 border-b border-border bg-muted/30 flex items-center gap-2 text-left hover:bg-muted/50 transition-colors cursor-pointer"
      >
        {icon}
        <h3 className="text-sm font-semibold flex-1">{title}</h3>
        {open ? (
          <ExpandLessIcon style={{ fontSize: 20 }} className="text-muted-foreground" />
        ) : (
          <ExpandMoreIcon style={{ fontSize: 20 }} className="text-muted-foreground" />
        )}
      </button>
      {open && children}
    </div>
  );
}

export function CrossCPEGraphs({ cpes }: { cpes: CPESummary[] }) {
  const [selectedMetric, setSelectedMetric] = useState<"memavail" | "cpu" | "sunreclaim" | "overcommit">(
    "memavail"
  );
  const mergePlot = usePlotlyLayoutMerge();

  console.log("[CrossCPEGraphs] Component rendering with", cpes.length, "CPEs");

  if (!cpes || cpes.length === 0) {
    console.log("[CrossCPEGraphs] No CPEs provided");
    return null;
  }

  const labels = cpes.map((c) => c.serial);

  // Extract metrics data - use existing metrics or synthetic data for demo
  const memAvailData: MetricChartData = {
    label: "MemAvailable %",
    values: cpes.map((c, idx) => {
      // Try to use actual metric, fall back to synthetic data for demo
      let val = c.key_metrics?.mem_available_pct as number | undefined;
      if (val === undefined) {
        // Synthetic demo data for testing colors: 90%, 70%, 45%, 25%, 8%
        val = [90, 70, 45, 25, 8][idx % 5];
      }
      console.log(`[MemAvail] CPE ${c.serial}: ${val}`);
      return val || null;
    }),
    unit: "%",
    getStatus: getMemAvailableStatus,
    formatValue: (v) => `${v.toFixed(1)}%`,
  };

  const cpuData: MetricChartData = {
    label: "CPU Usage %",
    values: cpes.map((c, idx) => {
      let val = c.key_metrics?.cpu_avg as number | undefined;
      if (val === undefined) {
        // Synthetic demo data: 5%, 12%, 18%, 25%, 8%
        val = [5, 12, 18, 25, 8][idx % 5];
      }
      console.log(`[CPU] CPE ${c.serial}: ${val}`);
      return (val as number) || null;
    }),
    unit: "%",
    getStatus: getCpuStatus,
    formatValue: (v) => `${v.toFixed(1)}%`,
  };

  const sunreclaimData: MetricChartData = {
    label: "SUnreclaim Ratio %",
    values: cpes.map((c, idx) => {
      let val = c.key_metrics?.sunreclaim_ratio as number | undefined;
      if (val === undefined) {
        // Synthetic demo data: 30%, 60%, 75%, 85%, 45%
        val = [30, 60, 75, 85, 45][idx % 5];
      }
      console.log(`[SUnreclaim] CPE ${c.serial}: ${val}`);
      return (val as number) || null;
    }),
    unit: "%",
    getStatus: getSUnreclaimStatus,
    formatValue: (v) => `${v.toFixed(1)}%`,
  };

  const overcommitData: MetricChartData = {
    label: "Overcommit Ratio",
    values: cpes.map((c, idx) => {
      let val = c.key_metrics?.overcommit_ratio as number | undefined;
      if (val === undefined) {
        // Synthetic demo data: 0.8x, 1.5x, 2.5x, 4.2x, 0.9x
        val = [0.8, 1.5, 2.5, 4.2, 0.9][idx % 5];
      }
      console.log(`[Overcommit] CPE ${c.serial}: ${val}`);
      return (val as number) || null;
    }),
    unit: "x",
    getStatus: getOvercommitStatus,
    formatValue: (v) => `${v.toFixed(2)}x`,
  };

  const metrics: Record<string, MetricChartData> = {
    memavail: memAvailData,
    cpu: cpuData,
    sunreclaim: sunreclaimData,
    overcommit: overcommitData,
  };

  const currentMetric = metrics[selectedMetric];

  // Calculate bar colors - this is key!
  const barColors = currentMetric.values.map((val, idx) => {
    const color = getBarColor(val, currentMetric.getStatus);
    console.log(`Bar ${idx}: val=${val}, color=${color}`);
    return color;
  });
  
  console.log(`[CrossCPEGraphs] Metric: ${selectedMetric}`);
  console.log(`[CrossCPEGraphs] Values:`, currentMetric.values);
  console.log(`[CrossCPEGraphs] Colors array:`, barColors);
  console.log(`[CrossCPEGraphs] Colors are all strings?`, barColors.every(c => typeof c === 'string'));

  // Calculate text colors for annotations (dark text on light, white on dark)
  const annotations = currentMetric.values.map((val, idx) => {
    const status = val !== null ? currentMetric.getStatus(val) : "unknown";
    const config = getColorConfig(status);
    const textColor = ["warning", "caution"].includes(status) ? config.textColor : "#fff";
    return {
      x: labels[idx],
      y: val || 0,
      text: val !== null ? currentMetric.formatValue(val) : "N/A",
      showarrow: false as const,
      font: { color: textColor, size: 11 },
      yanchor: "bottom" as const,
      dy: 5,
    };
  });

  // Detect fleet alerts
  const fleetAlerts: { serial: string; alerts: string[] }[] = [];
  cpes.forEach((cpe) => {
    const alerts = getFleetAlertMessage({
      memAvailablePct: cpe.key_metrics.mem_available_pct as number | undefined,
      sunreclaimRatio: cpe.key_metrics.sunreclaim_ratio as number | undefined,
      overcommitRatio: cpe.key_metrics.overcommit_ratio as number | undefined,
    });
    if (alerts.length > 0) {
      fleetAlerts.push({ serial: cpe.serial, alerts });
    }
  });

  return (
    <CollapsibleCard
      icon={<SignalCellularAltIcon style={{ fontSize: 20 }} className="text-primary" />}
      title="Cross-CPE Health Metrics"
    >
      <div className="p-4 space-y-4">
        {/* Metric selector tabs */}
        <div className="flex gap-2 border-b border-border">
          {Object.entries(metrics).map(([key, metric]) => (
            <button
              key={key}
              onClick={() => setSelectedMetric(key as any)}
              className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                selectedMetric === key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {metric.label}
            </button>
          ))}
        </div>

        {/* Health status legend */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
          {selectedMetric === "memavail" && (
            <>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("normal").bgColor }}>
                <span style={{ color: getColorConfig("normal").textColor }} className="font-medium">
                  ✓ Normal
                </span>
                <p style={{ color: getColorConfig("normal").textColor }}>{">"} 30%</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("caution").bgColor }}>
                <span style={{ color: getColorConfig("caution").textColor }} className="font-medium">
                  ⚡ Caution
                </span>
                <p style={{ color: getColorConfig("caution").textColor }}>20–30%</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("warning").bgColor }}>
                <span style={{ color: getColorConfig("warning").textColor }} className="font-medium">
                  ⚠️ Risk
                </span>
                <p style={{ color: getColorConfig("warning").textColor }}>10–20%</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("critical").bgColor }}>
                <span style={{ color: getColorConfig("critical").textColor }} className="font-medium">
                  🔴 Critical
                </span>
                <p style={{ color: getColorConfig("critical").textColor }}>{`<`} 10%</p>
              </div>
            </>
          )}

          {selectedMetric === "cpu" && (
            <>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("normal").bgColor }}>
                <span style={{ color: getColorConfig("normal").textColor }} className="font-medium">
                  ✓ Idle
                </span>
                <p style={{ color: getColorConfig("normal").textColor }}>5–10%</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("normal").bgColor }}>
                <span style={{ color: getColorConfig("normal").textColor }} className="font-medium">
                  ✓ Normal
                </span>
                <p style={{ color: getColorConfig("normal").textColor }}>10–15%</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("caution").bgColor }}>
                <span style={{ color: getColorConfig("caution").textColor }} className="font-medium">
                  ⚡ Medium
                </span>
                <p style={{ color: getColorConfig("caution").textColor }}>15–20%</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("warning").bgColor }}>
                <span style={{ color: getColorConfig("warning").textColor }} className="font-medium">
                  ⚠️ Busy
                </span>
                <p style={{ color: getColorConfig("warning").textColor }}>{`>`} 20%</p>
              </div>
            </>
          )}

          {selectedMetric === "sunreclaim" && (
            <>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("normal").bgColor }}>
                <span style={{ color: getColorConfig("normal").textColor }} className="font-medium">
                  ✓ Healthy
                </span>
                <p style={{ color: getColorConfig("normal").textColor }}>{`<`} 50%</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("caution").bgColor }}>
                <span style={{ color: getColorConfig("caution").textColor }} className="font-medium">
                  ⚡ Moderate
                </span>
                <p style={{ color: getColorConfig("caution").textColor }}>50–70%</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("warning").bgColor }}>
                <span style={{ color: getColorConfig("warning").textColor }} className="font-medium">
                  ⚠️ Suspicious
                </span>
                <p style={{ color: getColorConfig("warning").textColor }}>70–80%</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("critical").bgColor }}>
                <span style={{ color: getColorConfig("critical").textColor }} className="font-medium">
                  🔴 High Risk
                </span>
                <p style={{ color: getColorConfig("critical").textColor }}>{`>`} 80%</p>
              </div>
            </>
          )}

          {selectedMetric === "overcommit" && (
            <>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("normal").bgColor }}>
                <span style={{ color: getColorConfig("normal").textColor }} className="font-medium">
                  ✓ Normal
                </span>
                <p style={{ color: getColorConfig("normal").textColor }}>{`<`} 1x</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("caution").bgColor }}>
                <span style={{ color: getColorConfig("caution").textColor }} className="font-medium">
                  ⚡ Over
                </span>
                <p style={{ color: getColorConfig("caution").textColor }}>{`>`} 1x</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("warning").bgColor }}>
                <span style={{ color: getColorConfig("warning").textColor }} className="font-medium">
                  ⚠️ Aggressive
                </span>
                <p style={{ color: getColorConfig("warning").textColor }}>{`>`} 2x</p>
              </div>
              <div className="px-2 py-1 rounded" style={{ backgroundColor: getColorConfig("critical").bgColor }}>
                <span style={{ color: getColorConfig("critical").textColor }} className="font-medium">
                  🔴 Very High
                </span>
                <p style={{ color: getColorConfig("critical").textColor }}>{`>`} 4x</p>
              </div>
            </>
          )}
        </div>

        {/* Chart */}
        <Plot
          key={`plot-${selectedMetric}`}
          data={[
            {
              type: "bar",
              x: labels,
              y: currentMetric.values,
              marker: {
                color: barColors,
                line: {
                  color: "rgba(0,0,0,0.1)",
                  width: 1,
                },
              },
              text: currentMetric.values.map((val) =>
                val !== null ? currentMetric.formatValue(val) : "N/A"
              ),
              textposition: "outside" as const,
              hovertemplate: "<b>%{x}</b><br>" + currentMetric.label + ": %{y}<extra></extra>",
            } as any,
          ]}
          layout={mergePlot({
            title: { text: currentMetric.label },
            height: 400,
            margin: { t: 40, b: 120, l: 50, r: 20 },
            xaxis: { tickangle: -45, automargin: true },
            yaxis: {
              title: { text: currentMetric.unit || "" },
              zeroline: true,
            },
            showlegend: false,
            annotations,
            hovermode: "x unified" as const,
          })}
          config={{ displayModeBar: false, responsive: true }}
          style={{ width: "100%" }}
        />

        {/* Fleet alerts */}
        {fleetAlerts.length > 0 && (
          <div className="mt-6 pt-6 border-t border-border">
            <div className="flex items-center gap-2 mb-3">
              <ErrorIcon style={{ fontSize: 20 }} className="text-red-600" />
              <h4 className="font-semibold text-sm">Fleet Alerts</h4>
            </div>
            <div className="space-y-2">
              {fleetAlerts.map((alert) => (
                <div key={alert.serial} className="p-3 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800">
                  <p className="font-medium text-sm text-red-900 dark:text-red-200">{alert.serial}</p>
                  <ul className="text-xs text-red-800 dark:text-red-300 list-disc list-inside">
                    {alert.alerts.map((msg, idx) => (
                      <li key={idx}>{msg}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </CollapsibleCard>
  );
}
