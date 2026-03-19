import { useState, useCallback, useMemo } from "react";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import SwapHorizIcon from "@mui/icons-material/SwapHoriz";
import { cn } from "@/lib/utils";

const TIMEZONES = [
  { id: "UTC", label: "UTC", iana: "UTC" },
  { id: "CET", label: "CET", iana: "Europe/Berlin" },
  { id: "IST", label: "IST", iana: "Asia/Kolkata" },
] as const;

function formatInTZ(date: Date, iana: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: iana,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function toDatetimeLocal(date: Date, iana: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: iana,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(date);

  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}:${get("second")}`;
}

export default function TimeZoneBar() {
  const [expanded, setExpanded] = useState(() => {
    try {
      return localStorage.getItem("tz-bar-expanded") === "true";
    } catch {
      return false;
    }
  });

  const [sourceTZ, setSourceTZ] = useState<string>("UTC");
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());

  const toggleExpanded = useCallback(() => {
    setExpanded((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("tz-bar-expanded", String(next));
      } catch { /* ignore */ }
      return next;
    });
  }, []);

  const handleDateChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value;
      if (!val) return;

      const sourceIana = TIMEZONES.find((t) => t.id === sourceTZ)?.iana ?? "UTC";

      const localStr = val.length === 16 ? val + ":00" : val;
      const fakeLocal = new Date(localStr);

      const formatter = new Intl.DateTimeFormat("en-US", {
        timeZone: sourceIana,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
      const nowParts = formatter.formatToParts(new Date());
      const refParts = formatter.formatToParts(fakeLocal);

      const nowUTC = new Date();
      const getVal = (parts: Intl.DateTimeFormatPart[], type: string) =>
        parts.find((p) => p.type === type)?.value ?? "0";

      const nowInTZ = new Date(
        `${getVal(nowParts, "year")}-${getVal(nowParts, "month")}-${getVal(nowParts, "day")}T${getVal(nowParts, "hour")}:${getVal(nowParts, "minute")}:${getVal(nowParts, "second")}Z`
      );
      const targetInTZ = new Date(
        `${getVal(refParts, "year")}-${getVal(refParts, "month")}-${getVal(refParts, "day")}T${getVal(refParts, "hour")}:${getVal(refParts, "minute")}:${getVal(refParts, "second")}Z`
      );

      const offsetMs = targetInTZ.getTime() - nowInTZ.getTime();
      setSelectedDate(new Date(nowUTC.getTime() + offsetMs));
    },
    [sourceTZ]
  );

  const setNow = useCallback(() => {
    setSelectedDate(new Date());
  }, []);

  const inputValue = useMemo(() => {
    const iana = TIMEZONES.find((t) => t.id === sourceTZ)?.iana ?? "UTC";
    return toDatetimeLocal(selectedDate, iana);
  }, [selectedDate, sourceTZ]);

  const converted = useMemo(
    () => TIMEZONES.map((tz) => ({ ...tz, value: formatInTZ(selectedDate, tz.iana) })),
    [selectedDate]
  );

  return (
    <div className="bg-card">
      {/* Toggle button row */}
      <button
        onClick={toggleExpanded}
        className="flex items-center gap-1.5 w-full px-4 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
      >
        <AccessTimeIcon style={{ fontSize: 14 }} />
        <span className="font-medium">Time Zone Converter</span>
        {!expanded && (
          <span className="ml-2 text-muted-foreground/70">
            {converted.map((tz) => `${tz.label}: ${tz.value}`).join("  |  ")}
          </span>
        )}
        <span className="ml-auto">
          {expanded ? (
            <ExpandLessIcon style={{ fontSize: 16 }} />
          ) : (
            <ExpandMoreIcon style={{ fontSize: 16 }} />
          )}
        </span>
      </button>

      {/* Expanded panel */}
      {expanded && (
        <div className="px-4 pb-3 pt-1">
          <div className="flex flex-wrap items-end gap-4">
            {/* Source timezone selector */}
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                Input Timezone
              </label>
              <select
                value={sourceTZ}
                onChange={(e) => setSourceTZ(e.target.value)}
                className="h-9 px-2 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {TIMEZONES.map((tz) => (
                  <option key={tz.id} value={tz.id}>
                    {tz.label} ({tz.iana})
                  </option>
                ))}
              </select>
            </div>

            {/* DateTime picker */}
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                Date &amp; Time
              </label>
              <input
                type="datetime-local"
                step="1"
                value={inputValue}
                onChange={handleDateChange}
                className="h-9 px-2 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            {/* Now button */}
            <button
              onClick={setNow}
              className="h-9 px-3 rounded-md bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 transition-colors"
            >
              Now
            </button>

            {/* Converted values */}
            <div className="flex items-center gap-1 ml-2">
              <SwapHorizIcon style={{ fontSize: 16 }} className="text-muted-foreground" />
            </div>

            {TIMEZONES.map((tz) => (
              <div
                key={tz.id}
                className={cn(
                  "flex flex-col gap-1 px-3 py-1.5 rounded-md border",
                  tz.id === sourceTZ
                    ? "border-primary/30 bg-primary/5"
                    : "border-border bg-muted/30"
                )}
              >
                <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                  {tz.label}
                </span>
                <span className="text-sm font-mono font-medium">
                  {formatInTZ(selectedDate, tz.iana)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
