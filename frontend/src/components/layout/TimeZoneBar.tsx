import { useState, useCallback, useMemo } from "react";
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

/**
 * Time zone converter form (used inside a popover from ToolsBar).
 */
export default function TimeZoneBar() {
  const [sourceTZ, setSourceTZ] = useState<string>("UTC");
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());

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
        `${getVal(nowParts, "year")}-${getVal(nowParts, "month")}-${getVal(nowParts, "day")}T${getVal(nowParts, "hour")}:${getVal(nowParts, "minute")}:${getVal(nowParts, "second")}Z`,
      );
      const targetInTZ = new Date(
        `${getVal(refParts, "year")}-${getVal(refParts, "month")}-${getVal(refParts, "day")}T${getVal(refParts, "hour")}:${getVal(refParts, "minute")}:${getVal(refParts, "second")}Z`,
      );

      const offsetMs = targetInTZ.getTime() - nowInTZ.getTime();
      setSelectedDate(new Date(nowUTC.getTime() + offsetMs));
    },
    [sourceTZ],
  );

  const setNow = useCallback(() => {
    setSelectedDate(new Date());
  }, []);

  const inputValue = useMemo(() => {
    const iana = TIMEZONES.find((t) => t.id === sourceTZ)?.iana ?? "UTC";
    return toDatetimeLocal(selectedDate, iana);
  }, [selectedDate, sourceTZ]);

  return (
    <div className="bg-card">
      <div className="px-1 pb-1 pt-0">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
          Time zone converter
        </p>
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Input Timezone
            </label>
            <select
              value={sourceTZ}
              onChange={(e) => setSourceTZ(e.target.value)}
              className="h-9 px-2 rounded-md border border-input bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {TIMEZONES.map((tz) => (
                <option key={tz.id} value={tz.id}>
                  {tz.label} ({tz.iana})
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              Date &amp; Time
            </label>
            <input
              type="datetime-local"
              step="1"
              value={inputValue}
              onChange={handleDateChange}
              className="h-9 px-2 rounded-md border border-input bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <button
            type="button"
            onClick={setNow}
            className="h-9 px-3 rounded-md bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 transition-colors"
          >
            Now
          </button>

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
                  : "border-border bg-muted/30",
              )}
            >
              <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                {tz.label}
              </span>
              <span className="text-sm font-mono font-medium text-foreground">
                {formatInTZ(selectedDate, tz.iana)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
