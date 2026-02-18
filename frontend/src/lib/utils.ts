import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes with clsx */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format an ISO date string to a readable locale date */
export function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

/** Timezone IANA mapping for log conversion */
export const TZ_OPTIONS = [
  { id: "Original", label: "Original", iana: "" },
  { id: "UTC", label: "UTC", iana: "UTC" },
  { id: "CET", label: "CET", iana: "Europe/Berlin" },
  { id: "IST", label: "IST", iana: "Asia/Kolkata" },
] as const;

/**
 * Common log timestamp patterns:
 *  - YYYY-MM-DD HH:MM:SS (with optional .ms and optional timezone offset)
 *  - YYMMDD-HH:MM:SS (RDK-style: 230115-14:23:01)
 *  - Mon DD HH:MM:SS (syslog-style: Jan 15 14:23:01)
 *  - Epoch seconds (10-digit) or milliseconds (13-digit)
 */
const TS_PATTERNS = [
  // ISO-like: 2025-01-15 14:23:01.123 or 2025-01-15T14:23:01+00:00
  /(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:?\d{2}|Z)?)/,
  // RDK-style: 230115-14:23:01.123456
  /(\d{6}-\d{2}:\d{2}:\d{2}(?:\.\d+)?)/,
  // Syslog-style: Jan 15 14:23:01
  /((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})/,
];

const MONTH_MAP: Record<string, number> = {
  Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5,
  Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11,
};

function parseTimestamp(raw: string): Date | null {
  // ISO-like
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
    const d = new Date(raw.replace(" ", "T"));
    return isNaN(d.getTime()) ? null : d;
  }
  // RDK: YYMMDD-HH:MM:SS
  if (/^\d{6}-\d{2}:/.test(raw)) {
    const yy = raw.slice(0, 2);
    const mm = raw.slice(2, 4);
    const dd = raw.slice(4, 6);
    const time = raw.slice(7);
    const d = new Date(`20${yy}-${mm}-${dd}T${time}Z`);
    return isNaN(d.getTime()) ? null : d;
  }
  // Syslog: Mon DD HH:MM:SS (assume current year, UTC)
  const sysMatch = raw.match(/^(\w{3})\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})$/);
  if (sysMatch) {
    const month = MONTH_MAP[sysMatch[1]];
    if (month === undefined) return null;
    const day = sysMatch[2].padStart(2, "0");
    const year = new Date().getFullYear();
    const d = new Date(`${year}-${String(month + 1).padStart(2, "0")}-${day}T${sysMatch[3]}Z`);
    return isNaN(d.getTime()) ? null : d;
  }
  return null;
}

function formatInTargetTZ(date: Date, iana: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: iana,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
    hour12: false,
  }).format(date).replace(",", "");
}

/**
 * Convert the first recognized timestamp in a log line to the target timezone.
 * Returns the original line unchanged if targetTZ is "Original" or no timestamp is found.
 */
export function convertLogTimestamp(line: string, targetTZ: string): string {
  if (!targetTZ || targetTZ === "Original") return line;
  const iana = TZ_OPTIONS.find((t) => t.id === targetTZ)?.iana;
  if (!iana) return line;

  for (const pattern of TS_PATTERNS) {
    const match = line.match(pattern);
    if (match) {
      const parsed = parseTimestamp(match[1]);
      if (parsed) {
        const converted = formatInTargetTZ(parsed, iana);
        return line.replace(match[1], converted);
      }
    }
  }
  return line;
}
