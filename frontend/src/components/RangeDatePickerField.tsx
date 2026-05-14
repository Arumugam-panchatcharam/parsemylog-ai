import { useEffect, useLayoutEffect, useRef, useState, useCallback } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import { SimpleTwoClickRangeCalendar } from "./SimpleTwoClickRangeCalendar";

export interface RangeDatePickerFieldProps {
  startDate: string;
  endDate: string;
  onChange: (start: string, end: string) => void;
  disabled?: boolean;
  className?: string;
  /** Optional id forwarded to trigger for label association */
  triggerId?: string;
  placeholder?: string;
}

/**
 * Single-line control: shows selected ``YYYY-MM-DD – YYYY-MM-DD`` range; clicking opens the
 * compact two-click range calendar in a portal (avoids modal overflow clipping).
 */
export function RangeDatePickerField({
  startDate,
  endDate,
  onChange,
  disabled = false,
  className,
  triggerId,
  placeholder = "Click to choose date range",
}: RangeDatePickerFieldProps) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0, minWidth: 0 });

  const updatePos = useCallback(() => {
    const el = anchorRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
    const mw = Math.max(r.width, 172);
    setPos({
      top: r.bottom + 6,
      left: Math.max(8, Math.min(r.left, vw - mw - 8)),
      minWidth: mw,
    });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    updatePos();
  }, [open, updatePos]);

  useEffect(() => {
    if (!open) return;
    const sync = () => updatePos();
    window.addEventListener("resize", sync);
    window.addEventListener("scroll", sync, true);
    return () => {
      window.removeEventListener("resize", sync);
      window.removeEventListener("scroll", sync, true);
    };
  }, [open, updatePos]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (popoverRef.current?.contains(t)) return;
      if (anchorRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const displayText =
    startDate && endDate ? `${startDate} – ${endDate}` : startDate ? `${startDate} – …` : "";

  return (
    <>
      <div ref={anchorRef} className={cn("relative mt-1", className)}>
        <input
          id={triggerId}
          readOnly
          disabled={disabled}
          tabIndex={disabled ? -1 : 0}
          value={displayText}
          placeholder={placeholder}
          aria-expanded={open}
          aria-haspopup="dialog"
          autoComplete="off"
          className={cn(
            "w-full cursor-pointer caret-transparent rounded-lg border border-border bg-background px-3 py-2 pr-10 text-sm tabular-nums outline-none outline-offset-2 focus-visible:outline focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-60",
            !displayText && "text-muted-foreground placeholder:text-muted-foreground",
          )}
          onFocus={() => !disabled && setOpen(true)}
          onKeyDown={(e) => {
            if (disabled) return;
            if (e.key === "Escape" && open) {
              setOpen(false);
              e.preventDefault();
            }
            if ((e.key === "Enter" || e.key === " ") && !open) {
              e.preventDefault();
              setOpen(true);
            }
          }}
        />
        <button
          type="button"
          disabled={disabled}
          data-datepicker-chevron-wrap
          className="absolute inset-y-0 right-2 z-[1] my-auto grid h-[22px] w-[22px] place-items-center rounded border-0 bg-transparent p-0 text-muted-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
          tabIndex={-1}
          aria-label={open ? "Close calendar" : "Open calendar"}
          onMouseDown={(e) => {
            e.preventDefault();
            if (disabled) return;
            setOpen((v) => !v);
          }}
        >
          <KeyboardArrowDownIcon
            style={{ fontSize: 18 }}
            className={cn("transition-transform duration-150", open && "rotate-180")}
          />
        </button>
      </div>

      {open &&
        createPortal(
          <div
            ref={popoverRef}
            role="dialog"
            aria-modal="false"
            aria-label="Pick date range"
            className="rounded-md border border-border bg-card p-0.5 shadow-xl"
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              minWidth: pos.minWidth,
              zIndex: 12000,
            }}
          >
            <SimpleTwoClickRangeCalendar
              startDate={startDate}
              endDate={endDate}
              disabled={disabled}
              onChange={onChange}
              onRangeComplete={() => setOpen(false)}
            />
          </div>,
          document.body,
        )}
    </>
  );
}
