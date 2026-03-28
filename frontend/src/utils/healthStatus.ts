/**
 * Health status color coding utilities
 * Provides functions to determine colors and status badges based on thresholds
 */

export type HealthStatus = "critical" | "warning" | "caution" | "normal" | "unknown";

export interface ColorConfig {
  color: string;
  bgColor: string;
  textColor: string;
  icon?: string;
}

const COLOR_PALETTE: Record<HealthStatus, ColorConfig> = {
  critical: {
    color: "#dc2626", // red-600
    bgColor: "#fee2e2", // red-100
    textColor: "#991b1b", // red-900
    icon: "🔴",
  },
  warning: {
    color: "#ea580c", // orange-600
    bgColor: "#fed7aa", // orange-100
    textColor: "#92400e", // orange-900
    icon: "⚠️",
  },
  caution: {
    color: "#eab308", // yellow-500
    bgColor: "#fef3c7", // yellow-100
    textColor: "#713f12", // yellow-900
    icon: "⚡",
  },
  normal: {
    color: "#16a34a", // green-600
    bgColor: "#dcfce7", // green-100
    textColor: "#15803d", // green-700
    icon: "✓",
  },
  unknown: {
    color: "#6b7280", // gray-500
    bgColor: "#f3f4f6", // gray-100
    textColor: "#374151", // gray-700
  },
};

/**
 * MemAvailable percentage thresholds
 * Returns health status based on percentage of available memory
 */
export function getMemAvailableStatus(percentAvailable: number): HealthStatus {
  if (percentAvailable < 10) return "critical";
  if (percentAvailable < 20) return "warning";
  if (percentAvailable < 30) return "caution";
  return "normal";
}

/**
 * CPU usage percentage thresholds
 */
export function getCpuStatus(cpuPercent: number): HealthStatus {
  if (cpuPercent > 20) return "warning";
  if (cpuPercent > 15) return "caution";
  if (cpuPercent > 10) return "normal";
  return "normal"; // 5-10% is idle, still normal
}

/**
 * SUnreclaim ratio thresholds
 * Ratio of SUnreclaim to Slab (in percentage)
 */
export function getSUnreclaimStatus(sunreclaimRatio: number): HealthStatus {
  if (sunreclaimRatio > 80) return "critical";
  if (sunreclaimRatio > 70) return "warning";
  if (sunreclaimRatio > 50) return "caution";
  return "normal";
}

/**
 * Overcommit ratio thresholds
 * Ratio of Committed_AS / CommitLimit
 */
export function getOvercommitStatus(ratio: number): HealthStatus {
  if (ratio > 4) return "critical";
  if (ratio > 2) return "warning";
  if (ratio > 1) return "caution";
  return "normal";
}

/**
 * Get color configuration for a given health status
 */
export function getColorConfig(status: HealthStatus): ColorConfig {
  return COLOR_PALETTE[status];
}

/**
 * Fleet alert detection
 * Returns true if any of these conditions are met:
 * - MemAvailable < 20%
 * - SUnreclaim > 80%
 * - Overcommit ratio > 4
 */
export function shouldTriggerFleetAlert(metrics: {
  memAvailablePct?: number;
  sunreclaimRatio?: number;
  overcommitRatio?: number;
}): boolean {
  if (metrics.memAvailablePct !== undefined && metrics.memAvailablePct < 20) return true;
  if (metrics.sunreclaimRatio !== undefined && metrics.sunreclaimRatio > 80) return true;
  if (metrics.overcommitRatio !== undefined && metrics.overcommitRatio > 4) return true;
  return false;
}

/**
 * Get alert message for fleet
 */
export function getFleetAlertMessage(metrics: {
  memAvailablePct?: number;
  sunreclaimRatio?: number;
  overcommitRatio?: number;
}): string[] {
  const alerts: string[] = [];
  if (metrics.memAvailablePct !== undefined && metrics.memAvailablePct < 20) {
    alerts.push(`MemAvailable is critically low (${metrics.memAvailablePct}%)`);
  }
  if (metrics.sunreclaimRatio !== undefined && metrics.sunreclaimRatio > 80) {
    alerts.push(`SUnreclaim ratio is very high (${metrics.sunreclaimRatio}%)`);
  }
  if (metrics.overcommitRatio !== undefined && metrics.overcommitRatio > 4) {
    alerts.push(`Overcommit ratio is very high (${metrics.overcommitRatio.toFixed(2)}x)`);
  }
  return alerts;
}
