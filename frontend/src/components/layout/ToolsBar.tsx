import { memo } from "react";
import TimeZoneBar from "./TimeZoneBar";
import MacLookupBar from "./MacLookupBar";

/**
 * Unified utilities region: timezone converter + MAC OUI lookup (single landmark for screen readers).
 */
function ToolsBarInner() {
  return (
    <section
      className="shrink-0 divide-y divide-border border-b border-border bg-card"
      aria-label="Time zone converter and MAC OUI lookup"
    >
      <TimeZoneBar />
      <MacLookupBar />
    </section>
  );
}

export const ToolsBar = memo(ToolsBarInner);
ToolsBar.displayName = "ToolsBar";

export default ToolsBar;
