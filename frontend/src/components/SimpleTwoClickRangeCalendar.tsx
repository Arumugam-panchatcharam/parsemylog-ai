import { useState, useMemo } from "react";
import { cn } from "@/lib/utils";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";

const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"] as const;

function formatLocalYYYYMMDD(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Parse ``YYYY-MM-DD`` as local calendar date at noon (avoids UTC shift). */
function parseYYYYMMDDStrict(s: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s.trim());
  if (!m) return null;
  const year = Number(m[1]);
  const monthIndex = Number(m[2]) - 1;
  const dom = Number(m[3]);
  const d = new Date(year, monthIndex, dom, 12, 0, 0, 0);
  if (
    d.getFullYear() !== year ||
    d.getMonth() !== monthIndex ||
    d.getDate() !== dom
  ) {
    return null;
  }
  return d;
}

function daysInMonth(year: number, monthIndex: number): number {
  return new Date(year, monthIndex + 1, 0).getDate();
}

export interface SimpleTwoClickRangeCalendarProps {
  startDate: string;
  endDate: string;
  onChange: (start: string, end: string) => void;
  /** Called once both start and end are set (second calendar click). Not called on Clear. */
  onRangeComplete?: () => void;
  disabled?: boolean;
  className?: string;
}

/**
 * Minimal range calendar: first click sets start, second sets end (inclusive).
 * If both bounds exist, the next click starts a new range from that day.
 */
export function SimpleTwoClickRangeCalendar({
  startDate,
  endDate,
  onChange,
  onRangeComplete,
  disabled = false,
  className,
}: SimpleTwoClickRangeCalendarProps) {
  const parsedStart = parseYYYYMMDDStrict(startDate);
  const initialView = parsedStart ?? new Date();
  const [viewYear, setViewYear] = useState(initialView.getFullYear());
  const [viewMonth, setViewMonth] = useState(initialView.getMonth());

  const paddedWeeks = useMemo(() => {
    const firstDow = new Date(viewYear, viewMonth, 1).getDay();
    const dim = daysInMonth(viewYear, viewMonth);
    const totalSlots = Math.ceil((firstDow + dim) / 7) * 7;
    type Cell = { key: string; iso: string | null; day: number | null };

    const row: Cell[] = [];
    for (let slot = 0; slot < totalSlots; slot++) {
      const dayIndex = slot - firstDow + 1;
      if (dayIndex < 1 || dayIndex > dim) {
        row.push({ key: `${viewYear}-${viewMonth}-${slot}-pad`, iso: null, day: null });
      } else {
        const iso = formatLocalYYYYMMDD(new Date(viewYear, viewMonth, dayIndex, 12, 0, 0, 0));
        row.push({
          key: iso,
          iso,
          day: dayIndex,
        });
      }
    }

    const weeks: Cell[][] = [];
    for (let i = 0; i < row.length; i += 7) {
      weeks.push(row.slice(i, i + 7));
    }
    return weeks;
  }, [viewYear, viewMonth]);

  const handleDayClick = (iso: string | null) => {
    if (disabled || !iso) return;
    if (!startDate || endDate) {
      onChange(iso, "");
      return;
    }
    let s = startDate;
    let e = iso;
    if (e < s) [s, e] = [e, s];
    onChange(s, e);
    onRangeComplete?.();
  };

  const summaryText = () => {
    if (!startDate && !endDate) return "Start, then end.";
    if (startDate && !endDate) return `${startDate} → end`;
    if (startDate && endDate) return `${startDate}→${endDate}`;
    return "";
  };

  const gotoPrevMonth = () => {
    if (disabled) return;
    if (viewMonth === 0) {
      setViewMonth(11);
      setViewYear((y) => y - 1);
    } else {
      setViewMonth((m) => m - 1);
    }
  };

  const gotoNextMonth = () => {
    if (disabled) return;
    if (viewMonth === 11) {
      setViewMonth(0);
      setViewYear((y) => y + 1);
    } else {
      setViewMonth((m) => m + 1);
    }
  };

  const monthLabel = new Date(viewYear, viewMonth, 1).toLocaleString(undefined, {
    month: "short",
    year: "numeric",
  });

  const todayIso = formatLocalYYYYMMDD(new Date());

  return (
    <div
      className={cn(
        "inline-block max-w-full rounded-md border border-border bg-muted/15 py-1 px-1 align-top leading-none select-none",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-0.5 mb-px px-px">
        <span className="text-[10px] font-medium text-foreground truncate">{monthLabel}</span>
        <div className="flex items-center shrink-0">
          <button
            type="button"
            disabled={disabled}
            onClick={gotoPrevMonth}
            className="p-px rounded hover:bg-muted text-muted-foreground disabled:opacity-40 leading-none"
            aria-label="Previous month"
          >
            <ChevronLeftIcon style={{ fontSize: 14 }} />
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={gotoNextMonth}
            className="p-px rounded hover:bg-muted text-muted-foreground disabled:opacity-40 leading-none"
            aria-label="Next month"
          >
            <ChevronRightIcon style={{ fontSize: 14 }} />
          </button>
        </div>
      </div>
      <p className="text-[8px] text-muted-foreground mb-px px-px truncate" title={summaryText()}>
        {summaryText()}
      </p>
      <div className="grid grid-cols-7 text-[7px] tabular-nums text-muted-foreground">
        {WEEKDAYS.map((w) => (
          <div key={w} className="h-3 flex items-center justify-center font-semibold">
            {w}
          </div>
        ))}
      </div>
      <div className="flex flex-col">
        {paddedWeeks.map((week, wi) => (
          <div key={wi} className="grid grid-cols-7 place-items-center">
            {week.map((cell) => {
              if (!cell.iso) {
                return <div key={cell.key} className="size-[22px] shrink-0" aria-hidden />;
              }
              const iso = cell.iso;
              const hasRange = !!startDate && !!endDate;
              const between =
                hasRange && iso >= startDate && iso <= endDate && iso !== startDate && iso !== endDate;
              const edge = iso === startDate || iso === endDate;
              const today = iso === todayIso;

              return (
                <button
                  key={cell.key}
                  type="button"
                  disabled={disabled}
                  onClick={() => handleDayClick(iso)}
                  className={cn(
                    "size-[22px] shrink-0 flex items-center justify-center text-[9px] rounded-[3px] p-0 transition-colors disabled:opacity-40 tabular-nums",
                    between && "bg-primary/15 text-foreground",
                    edge && "bg-primary text-primary-foreground font-semibold hover:bg-primary/90",
                    !between &&
                      !edge &&
                      today &&
                      "ring-1 ring-primary/35 ring-inset bg-background",
                    !between && !edge && !today && "hover:bg-muted/70 bg-background",
                  )}
                  aria-pressed={edge}
                  aria-label={`${iso}`}
                >
                  {cell.day}
                </button>
              );
            })}
          </div>
        ))}
      </div>
      {(startDate || endDate) && (
        <div className="mt-px flex justify-end pr-px">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange("", "")}
            className="text-[8px] text-muted-foreground underline hover:text-foreground disabled:opacity-40 leading-none py-px"
          >
            Clear
          </button>
        </div>
      )}
    </div>
  );
}
