import { memo, useMemo } from "react";
import { highlightLogLine } from "@/lib/logHighlighter";

export interface LogLineProps {
  lineNumber: number;
  /** Raw line (e.g. for double-click dedup). */
  text: string;
  /** After timezone conversion — highlighting runs on this string. */
  displayText: string;
  syntaxOn: boolean;
  searchPattern: string;
  onDoubleClick?: (text: string) => void;
}

function LogLineInner({
  lineNumber,
  text,
  displayText,
  syntaxOn,
  searchPattern,
  onDoubleClick,
}: LogLineProps) {
  const content = useMemo(() => {
    if (!syntaxOn && !searchPattern) return displayText;
    return highlightLogLine(displayText, searchPattern || undefined);
  }, [displayText, syntaxOn, searchPattern]);

  return (
    <div
      data-line={lineNumber}
      onDoubleClick={onDoubleClick ? () => onDoubleClick(text) : undefined}
      className="hover:bg-black/[0.06] dark:hover:bg-white/[0.06] whitespace-pre-wrap px-2 sm:px-3 leading-relaxed transition-colors duration-500"
    >
      <span className="select-none mr-3 inline-block w-12 text-right tabular-nums text-log-pane-foreground/55">
        {lineNumber}
      </span>
      {content}
    </div>
  );
}

export const LogLine = memo(LogLineInner);
