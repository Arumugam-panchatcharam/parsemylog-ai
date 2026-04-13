import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Parse a single MAC: 6 groups separated by space, colon, or hyphen. */
export function parseMacStringToBytes(input: string): string[] | null {
  const t = input.trim();
  if (!t) return null;
  const parts = t.split(/[\s:-]+/).filter(Boolean);
  if (parts.length !== 6) return null;
  const bytes: string[] = [];
  for (const p of parts) {
    if (!/^[0-9a-fA-F]{1,2}$/.test(p)) return null;
    const n = parseInt(p, 16);
    if (Number.isNaN(n) || n < 0 || n > 255) return null;
    bytes.push(n.toString(16).padStart(2, "0"));
  }
  return bytes;
}

export function macBytesToColon(bytes: string[]): string {
  return bytes.join(":");
}

/**
 * Plain-text line for tooltips: comma-separated tokens, MACs as aa:bb:...
 */
export function plainTextWithFormattedMacs(raw: string): string {
  return raw
    .split(",")
    .map((seg) => {
      const t = seg.trim();
      const b = parseMacStringToBytes(t);
      return b ? macBytesToColon(b) : t;
    })
    .join(", ");
}

/** Low nibble 2,6,A,E: unicast (I/G=0) and locally administered (U/L=1). */
const UL_UNICAST_LOCAL_LOW_NIBBLES = new Set(["2", "6", "a", "e"]);

function firstOctetIsUlUnicastLocal(octet: string): boolean {
  if (octet.length !== 2) return false;
  return UL_UNICAST_LOCAL_LOW_NIBBLES.has(octet[1]!.toLowerCase());
}

function MacColonHighlighted({ bytes }: { bytes: string[] }): ReactNode {
  const highlightUl = firstOctetIsUlUnicastLocal(bytes[0]!);
  return (
    <span className="font-mono tracking-tight">
      {bytes.map((octet, i) => (
        <span key={i}>
          {i > 0 ? <span className="text-muted-foreground">:</span> : null}
          <span
            className={cn(
              "rounded px-0.5",
              i === 0 && highlightUl && "bg-amber-500/25 text-foreground dark:bg-amber-500/20",
              (i === 4 || i === 5) && "font-bold",
            )}
            title={
              i === 0 && highlightUl
                ? "Locally administered unicast (U/L: low nibble 2, 6, A, E)"
                : i === 4 || i === 5
                  ? "Lower two octets (NIC)"
                  : undefined
            }
          >
            {octet}
          </span>
        </span>
      ))}
    </span>
  );
}

/**
 * Renders a comma-separated list; segments that look like MACs get colon form + highlights.
 */
export function DynamicValuesMacRichText({ raw }: { raw: string }): ReactNode {
  const segments = raw.split(",");
  const out: ReactNode[] = [];
  segments.forEach((seg, idx) => {
    const t = seg.trim();
    if (idx > 0) out.push(<span key={`sep-${idx}`}>, </span>);
    const b = parseMacStringToBytes(t);
    if (b) {
      out.push(<MacColonHighlighted key={`mac-${idx}`} bytes={b} />);
    } else {
      out.push(<span key={`txt-${idx}`}>{t}</span>);
    }
  });
  return <span className="inline leading-relaxed">{out}</span>;
}
