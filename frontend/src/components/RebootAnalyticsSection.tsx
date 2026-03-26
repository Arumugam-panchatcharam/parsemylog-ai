import React, { useState } from "react";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import TimerIcon from "@mui/icons-material/Timer";
import SpeedIcon from "@mui/icons-material/Speed";

/**
 * RebootAnalyticsSection
 * 
 * Displays reboot analytics with two bucketing dimensions:
 * 1. Time-of-Day: 4 x 6-hour buckets (00-06, 06-12, 12-18, 18-24)
 * 2. Uptime Before Reboot: 6 categories (<1d, 1-5d, 5-10d, 10-15d, 15-20d, >20d)
 * 
 * Features:
 * - Interactive summary cards showing count and percentage per bucket
 * - Click card to select and view detailed CPE table below
 * - Sortable detail table (serial, timestamp, uptime)
 * - Inline table display (no modal popup)
 */

interface BucketData {
  count: number;
  label: string;
  percentage: number;
  devices: Array<{
    serial: string;
    model?: string;
    timestamp?: string;
    hour?: number;
    uptime_seconds?: number;
  }>;
}

interface RebootAnalytics {
  time_of_day_buckets: Record<string, BucketData>;
  uptime_buckets: Record<string, BucketData>;
  total_reboot_events: number;
}

interface RebootAnalyticsSectionProps {
  analytics: RebootAnalytics | null | undefined;
}

interface DeviceGroup {
  groupId: number;
  devices: Array<{
    serial: string;
    model?: string;
    timestamp?: string;
    hour?: number;
    uptime_seconds?: number;
  }>;
  size: number;
}

// Group devices by time proximity (within 10 minutes)
function groupDevicesByTimeProximity(
  devices: Array<{ serial: string; model?: string; timestamp?: string; hour?: number; uptime_seconds?: number }>,
  timeWindowMinutes: number = 10
): DeviceGroup[] {
  if (devices.length === 0) return [];

  // Don't re-sort - devices are already sorted by the component
  // The grouping should preserve the input sort order
  const groups: DeviceGroup[] = [];
  let currentGroup: typeof devices = [];
  let currentGroupId = 0;

  devices.forEach((device, idx) => {
    if (idx === 0) {
      currentGroup = [device];
    } else {
      const prevTime = new Date(currentGroup[0].timestamp || "").getTime();
      const currTime = new Date(device.timestamp || "").getTime();
      const diffMinutes = Math.abs(currTime - prevTime) / (1000 * 60);

      if (diffMinutes <= timeWindowMinutes) {
        currentGroup.push(device);
      } else {
        // Save current group and start a new one
        groups.push({
          groupId: currentGroupId++,
          devices: currentGroup,
          size: currentGroup.length,
        });
        currentGroup = [device];
      }
    }
  });

  // Don't forget the last group
  if (currentGroup.length > 0) {
    groups.push({
      groupId: currentGroupId,
      devices: currentGroup,
      size: currentGroup.length,
    });
  }

  return groups;
}

export default function RebootAnalyticsSection({ analytics }: RebootAnalyticsSectionProps) {
  const [selectedTimeBucket, setSelectedTimeBucket] = useState<string | null>(null);
  const [selectedUptimeBucket, setSelectedUptimeBucket] = useState<string | null>(null);
  const [timeSortKey, setTimeSortKey] = useState<"serial" | "timestamp">("timestamp");
  const [timeSortDir, setTimeSortDir] = useState<"asc" | "desc">("desc");
  const [uptimeSortKey, setUptimeSortKey] = useState<"serial" | "uptime">("uptime");
  const [uptimeSortDir, setUptimeSortDir] = useState<"asc" | "desc">("desc");

  if (!analytics || analytics.total_reboot_events === 0) {
    return null;
  }

  const timeBuckets = analytics.time_of_day_buckets || {};
  const uptimeBuckets = analytics.uptime_buckets || {};

  // Sort devices for time-of-day table
  const selectedTimeData = selectedTimeBucket ? timeBuckets[selectedTimeBucket] : null;
  const sortedTimeDevices = selectedTimeData
    ? [...selectedTimeData.devices].sort((a, b) => {
        if (timeSortKey === "serial") {
          const aVal = a.serial || "";
          const bVal = b.serial || "";
          return timeSortDir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        } else {
          const aVal = a.timestamp || "";
          const bVal = b.timestamp || "";
          return timeSortDir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        }
      })
    : [];

  // Sort devices for uptime table
  const selectedUptimeData = selectedUptimeBucket ? uptimeBuckets[selectedUptimeBucket] : null;
  const sortedUptimeDevices = selectedUptimeData
    ? [...selectedUptimeData.devices].sort((a, b) => {
        if (uptimeSortKey === "serial") {
          const aVal = a.serial || "";
          const bVal = b.serial || "";
          return uptimeSortDir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        } else {
          const aVal = a.uptime_seconds || 0;
          const bVal = b.uptime_seconds || 0;
          return uptimeSortDir === "asc" ? aVal - bVal : bVal - aVal;
        }
      })
    : [];

  // Group devices by time proximity
  const timeGroups = groupDevicesByTimeProximity(sortedTimeDevices);
  const uptimeGroups = groupDevicesByTimeProximity(sortedUptimeDevices);

  // Helper function to get color based on percentage
  const getColorClass = (percentage: number) => {
    if (percentage === 0) return "bg-gray-50 dark:bg-gray-900/20 border-gray-200 dark:border-gray-700";
    if (percentage < 10) return "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-700";
    if (percentage < 25) return "bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-700";
    if (percentage < 40) return "bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-700";
    if (percentage < 60) return "bg-orange-50 dark:bg-orange-900/20 border-orange-200 dark:border-orange-700";
    return "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-700";
  };

  const getTextColorClass = (percentage: number) => {
    if (percentage === 0) return "text-gray-700 dark:text-gray-300";
    if (percentage < 10) return "text-green-700 dark:text-green-300";
    if (percentage < 25) return "text-blue-700 dark:text-blue-300";
    if (percentage < 40) return "text-yellow-700 dark:text-yellow-300";
    if (percentage < 60) return "text-orange-700 dark:text-orange-300";
    return "text-red-700 dark:text-red-300";
  };

  // Helper function to get background color for grouped rows with alternating shades
  const getGroupRowBgClass = (groupSize: number, groupIdx: number): string => {
    if (groupSize === 1) {
      // Alternate light shade for single devices
      return groupIdx % 2 === 0 ? "" : "bg-slate-100 dark:bg-slate-800";
    }
    if (groupSize === 2) {
      // Alternate yellow shades for 2-device groups
      return groupIdx % 2 === 0 ? "bg-yellow-100 dark:bg-yellow-900" : "bg-yellow-50 dark:bg-yellow-950";
    }
    // Alternate orange shades for 3+ device groups
    return groupIdx % 2 === 0 ? "bg-orange-100 dark:bg-orange-900" : "bg-orange-50 dark:bg-orange-950";
  };

  const getGroupBorderClass = (groupSize: number): string => {
    if (groupSize === 1) return "border-l-0";
    if (groupSize === 2) return "border-l-2 border-l-yellow-400 dark:border-l-yellow-500";
    return "border-l-4 border-l-orange-500 dark:border-l-orange-400";
  };
  
  return (
    <div className="space-y-3">
      {/* Two Column Layout - Cards */}
      <div className="grid grid-cols-2 gap-3">
        {/* Time-of-Day Section */}
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="px-3 py-1.5 border-b border-border bg-muted/30 flex items-center gap-2">
            <TimerIcon style={{ fontSize: 16, color: "#f9ab00" }} />
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Reboots by Time-of-Day
            </h3>
            <span className="text-[10px] ml-auto px-2 py-0.5 rounded-full bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300 font-semibold">
              {analytics.total_reboot_events} events
            </span>
          </div>

          {/* Time-of-Day Cards */}
          <div className="p-3 grid grid-cols-2 gap-2">
            {Object.entries(timeBuckets).map(([bucketId, data]) => (
              <button
                key={bucketId}
                onClick={() => setSelectedTimeBucket(selectedTimeBucket === bucketId ? null : bucketId)}
                className={`p-3 rounded-lg border transition-all text-left ${getColorClass(data.percentage)} ${
                  selectedTimeBucket === bucketId
                    ? "ring-2 ring-yellow-400 dark:ring-yellow-500"
                    : "hover:border-muted-foreground/50"
                }`}
              >
                <div className={`text-[11px] font-bold mb-1 ${getTextColorClass(data.percentage)}`}>
                  {data.label}
                </div>
                <div className={`text-xl font-bold ${getTextColorClass(data.percentage)}`}>
                  {data.count}
                </div>
                <div className={`text-[10px] font-semibold ${getTextColorClass(data.percentage)}`}>
                  {data.percentage}%
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Uptime Section */}
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="px-3 py-1.5 border-b border-border bg-muted/30 flex items-center gap-2">
            <SpeedIcon style={{ fontSize: 16, color: "#e8710a" }} />
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Reboots by Uptime
            </h3>
          </div>

          {/* Uptime Cards - Sorted */}
          <div className="p-3 grid grid-cols-2 gap-2">
            {['<1d', '1-5d', '5-10d', '10-15d', '15-20d', '>20d'].map((bucketId) => {
              const data = uptimeBuckets[bucketId];
              if (!data) return null;
              return (
                <button
                  key={bucketId}
                  onClick={() => setSelectedUptimeBucket(selectedUptimeBucket === bucketId ? null : bucketId)}
                  className={`p-3 rounded-lg border transition-all text-left ${getColorClass(data.percentage)} ${
                    selectedUptimeBucket === bucketId
                      ? "ring-2 ring-orange-400 dark:ring-orange-500"
                      : "hover:border-muted-foreground/50"
                  }`}
                >
                  <div className={`text-[11px] font-bold mb-1 ${getTextColorClass(data.percentage)}`}>
                    {data.label}
                  </div>
                  <div className={`text-xl font-bold ${getTextColorClass(data.percentage)}`}>
                    {data.count}
                  </div>
                  <div className={`text-[10px] font-semibold ${getTextColorClass(data.percentage)}`}>
                    {data.percentage}%
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Two Column Layout - Tables */}
      <div className="grid grid-cols-2 gap-3">
        {/* Time-of-Day Table */}
        {selectedTimeBucket && selectedTimeData && (
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            <div className="px-3 py-2 border-b border-border bg-muted/30">
              <div className="text-xs font-semibold text-muted-foreground">
                {selectedTimeData.label} - {sortedTimeDevices.length} device{sortedTimeDevices.length !== 1 ? "s" : ""}
              </div>
            </div>
            <div className={`${sortedTimeDevices.length > 10 ? 'overflow-y-auto' : ''}`} style={{ maxHeight: sortedTimeDevices.length > 10 ? `${Math.min(sortedTimeDevices.length * 24 + 40, 600)}px` : 'auto' }}>
              <table className="text-[11px] border-collapse w-full">
                <colgroup>
                  <col style={{ width: "140px" }} />
                  <col style={{ width: "100px" }} />
                  <col style={{ width: "160px" }} />
                </colgroup>
                <thead className="bg-muted/20 border-b border-border sticky top-0 z-10">
                  <tr>
                    <th className="text-left px-2 py-1 font-semibold text-muted-foreground">
                      <button
                        onClick={() => {
                          if (timeSortKey === "serial") {
                            setTimeSortDir(timeSortDir === "asc" ? "desc" : "asc");
                          } else {
                            setTimeSortKey("serial");
                            setTimeSortDir("asc");
                          }
                        }}
                        className="flex items-center gap-1 hover:text-foreground"
                      >
                        Serial
                        {timeSortKey === "serial" && (
                          timeSortDir === "asc" ? <ExpandMoreIcon style={{ fontSize: 12 }} /> : <ExpandLessIcon style={{ fontSize: 12 }} />
                        )}
                      </button>
                    </th>
                    <th className="text-left px-2 py-1 font-semibold text-muted-foreground">Model</th>
                    <th className="text-left px-2 py-1 font-semibold text-muted-foreground">
                      <button
                        onClick={() => {
                          if (timeSortKey === "timestamp") {
                            setTimeSortDir(timeSortDir === "asc" ? "desc" : "asc");
                          } else {
                            setTimeSortKey("timestamp");
                            setTimeSortDir("asc");
                          }
                        }}
                        className="flex items-center gap-1 hover:text-foreground"
                      >
                        Timestamp
                        {timeSortKey === "timestamp" && (
                          timeSortDir === "asc" ? <ExpandMoreIcon style={{ fontSize: 12 }} /> : <ExpandLessIcon style={{ fontSize: 12 }} />
                        )}
                      </button>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {sortedTimeDevices.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-2 py-2 text-center text-muted-foreground">
                        No devices in this bucket
                      </td>
                    </tr>
                  ) : (
                    <>
                      {timeGroups.map((group, groupIdx) => (
                        <React.Fragment key={group.groupId}>
                          {group.devices.map((device, deviceIdx) => (
                            <tr 
                              key={`${group.groupId}-${deviceIdx}`}
                              className={`border-t border-border transition-colors ${getGroupRowBgClass(group.size, groupIdx)} ${getGroupBorderClass(group.size)}`}
                            >
                              <td className="px-2 py-1 font-mono font-medium text-foreground">
                                {device.serial}
                              </td>
                              <td className="px-2 py-1 text-muted-foreground">{device.model || "N/A"}</td>
                              <td className="px-2 py-1 text-muted-foreground text-[10px]">
                                {device.timestamp ? new Date(device.timestamp).toLocaleString() : "N/A"}
                              </td>
                            </tr>
                          ))}
                          {groupIdx < timeGroups.length - 1 && (
                            <tr className="h-1">
                              <td colSpan={3} className="px-0 py-0"></td>
                            </tr>
                          )}
                        </React.Fragment>
                      ))}
                    </>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Uptime Table */}
        {selectedUptimeBucket && selectedUptimeData && (
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            <div className="px-3 py-2 border-b border-border bg-muted/30">
              <div className="text-xs font-semibold text-muted-foreground">
                {selectedUptimeData.label} - {sortedUptimeDevices.length} device{sortedUptimeDevices.length !== 1 ? "s" : ""}
              </div>
            </div>
            <div className={`${sortedUptimeDevices.length > 10 ? 'overflow-y-auto' : ''}`} style={{ maxHeight: sortedUptimeDevices.length > 10 ? `${Math.min(sortedUptimeDevices.length * 24 + 40, 600)}px` : 'auto' }}>
              <table className="text-[11px] border-collapse w-full">
                <colgroup>
                  <col style={{ width: "140px" }} />
                  <col style={{ width: "100px" }} />
                  <col style={{ width: "160px" }} />
                </colgroup>
                <thead className="bg-muted/20 border-b border-border sticky top-0 z-10">
                  <tr>
                    <th className="text-left px-2 py-1 font-semibold text-muted-foreground">
                      <button
                        onClick={() => {
                          if (uptimeSortKey === "serial") {
                            setUptimeSortDir(uptimeSortDir === "asc" ? "desc" : "asc");
                          } else {
                            setUptimeSortKey("serial");
                            setUptimeSortDir("asc");
                          }
                        }}
                        className="flex items-center gap-1 hover:text-foreground"
                      >
                        Serial
                        {uptimeSortKey === "serial" && (
                          uptimeSortDir === "asc" ? <ExpandMoreIcon style={{ fontSize: 12 }} /> : <ExpandLessIcon style={{ fontSize: 12 }} />
                        )}
                      </button>
                    </th>
                    <th className="text-left px-2 py-1 font-semibold text-muted-foreground">Model</th>
                    <th className="text-right px-2 py-1 font-semibold text-muted-foreground cursor-pointer hover:text-foreground" onClick={() => {if (uptimeSortKey === "uptime") { setUptimeSortDir(uptimeSortDir === "asc" ? "desc" : "asc"); } else { setUptimeSortKey("uptime"); setUptimeSortDir("asc"); }}}>
                      <span className="flex items-center gap-1">
                        Uptime
                        {uptimeSortKey === "uptime" && (
                          uptimeSortDir === "asc" ? <ExpandMoreIcon style={{ fontSize: 12 }} /> : <ExpandLessIcon style={{ fontSize: 12 }} />
                        )}
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {sortedUptimeDevices.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-2 py-2 text-center text-muted-foreground">
                        No devices in this bucket
                      </td>
                    </tr>
                  ) : (
                    <>
                      {uptimeGroups.map((group, groupIdx) => (
                        <React.Fragment key={group.groupId}>
                          {group.devices.map((device, deviceIdx) => (
                            <tr 
                              key={`${group.groupId}-${deviceIdx}`}
                              className={`border-t border-border transition-colors ${getGroupRowBgClass(group.size, groupIdx)} ${getGroupBorderClass(group.size)}`}
                            >
                              <td className="px-2 py-1 font-mono font-medium text-foreground">
                                {device.serial}
                              </td>
                              <td className="px-2 py-1 text-muted-foreground">{device.model || "N/A"}</td>
                              <td className="px-2 py-1 text-muted-foreground text-[10px]">
                                {device.uptime_seconds ? formatDuration(device.uptime_seconds) : "N/A"}
                              </td>
                            </tr>
                          ))}
                          {groupIdx < uptimeGroups.length - 1 && (
                            <tr className="h-1">
                              <td colSpan={3} className="px-0 py-0"></td>
                            </tr>
                          )}
                        </React.Fragment>
                      ))}
                    </>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds >= 86400) {
    const days = Math.floor(seconds / 86400);
    const remaining = seconds % 86400;
    const hours = Math.floor(remaining / 3600);
    return `${days}d ${hours}h`;
  }
  if (seconds >= 3600) {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${mins}m`;
  }
  const mins = Math.floor(seconds / 60);
  return `${mins}m`;
}
