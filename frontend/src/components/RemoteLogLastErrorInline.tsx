import { parseRemoteLogLastError } from "@/utils/remoteLogLastError";

type Props = {
  lastError: string | null | undefined;
  /** Narrow column (table) vs wider block (log viewer) */
  variant?: "table" | "block";
};

/**
 * Shows structured remote-log fetch errors: technical message + short remediation
 * (e.g. refresh crash portal bearer).
 */
export function RemoteLogLastErrorInline({ lastError, variant = "table" }: Props) {
  const p = parseRemoteLogLastError(lastError);
  if (!p.message) {
    return <span className="text-muted-foreground">—</span>;
  }
  const wrap =
    variant === "table" ? "max-w-[min(320px,100%)]" : "max-w-[min(520px,100%)]";
  return (
    <div className={`flex flex-col gap-1 min-w-0 ${wrap}`}>
      <span className={`text-destructive ${variant === "table" ? "truncate" : ""}`} title={p.message}>
        {p.message}
      </span>
      {p.remediation ? (
        <span
          className="text-[10px] leading-snug text-amber-800 dark:text-amber-300"
          title={p.remediation}
        >
          {p.remediation}
        </span>
      ) : null}
    </div>
  );
}
