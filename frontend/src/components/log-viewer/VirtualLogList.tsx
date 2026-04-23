import { useCallback, useEffect, useRef } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { convertLogTimestamp } from "@/lib/utils";
import { LogLine } from "./LogLine";
import type { LogRow } from "./types";

export interface VirtualLogListProps {
  rows: readonly LogRow[];
  firstItemIndex: number;
  scheduleLoadNext: () => void;
  scheduleLoadPrev: () => void;
  hasMoreNext: boolean;
  hasMorePrev: boolean;
  loadingNext: boolean;
  loadingPrev: boolean;
  followOutput: boolean | "smooth" | "auto";
  onAtBottomStateChange?: (atBottom: boolean) => void;
  syntaxHL: boolean;
  activeHighlight: string;
  logTimezone: string;
  scrollToLineNumber: number | null;
  onScrollToLineDone: () => void;
  onLineDoubleClick?: (text: string) => void;
  /** Changes remount Virtuoso (e.g. pagination jump) so scroll resets to top. */
  listKey: string;
}

export function VirtualLogList({
  rows,
  firstItemIndex,
  scheduleLoadNext,
  scheduleLoadPrev,
  hasMoreNext,
  hasMorePrev,
  loadingNext,
  loadingPrev,
  followOutput,
  onAtBottomStateChange,
  syntaxHL,
  activeHighlight,
  logTimezone,
  scrollToLineNumber,
  onScrollToLineDone,
  onLineDoubleClick,
  listKey,
}: VirtualLogListProps) {
  const virtuosoRef = useRef<VirtuosoHandle>(null);

  const onStartReached = useCallback(() => {
    if (hasMorePrev && !loadingPrev) scheduleLoadPrev();
  }, [hasMorePrev, loadingPrev, scheduleLoadPrev]);

  const onEndReached = useCallback(() => {
    if (hasMoreNext && !loadingNext) scheduleLoadNext();
  }, [hasMoreNext, loadingNext, scheduleLoadNext]);

  const itemContent = useCallback(
    (_index: number, row: LogRow) => (
      <LogLine
        lineNumber={row.lineNumber}
        text={row.text}
        displayText={convertLogTimestamp(row.text, logTimezone)}
        syntaxOn={syntaxHL}
        searchPattern={activeHighlight}
        onDoubleClick={onLineDoubleClick}
      />
    ),
    [logTimezone, syntaxHL, activeHighlight, onLineDoubleClick],
  );

  const computeKey = useCallback((_index: number, row: LogRow) => row.id, []);

  useEffect(() => {
    if (scrollToLineNumber == null || rows.length === 0) return;
    const idx = rows.findIndex((r) => r.lineNumber === scrollToLineNumber);
    if (idx < 0) return;

    const scroll = () => {
      virtuosoRef.current?.scrollToIndex({
        index: firstItemIndex + idx,
        align: "center",
        behavior: "auto",
      });
    };
    scroll();
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const el = document.querySelector(`[data-line="${scrollToLineNumber}"]`);
        if (el) {
          el.classList.add("bg-amber-700/40");
          setTimeout(() => el.classList.remove("bg-amber-700/40"), 2000);
        }
        onScrollToLineDone();
      });
    });
  }, [scrollToLineNumber, rows, firstItemIndex, onScrollToLineDone]);

  return (
    <div className="relative flex flex-1 min-h-0 min-w-0 flex-col">
      <Virtuoso
        key={listKey}
        ref={virtuosoRef}
        style={{ height: "100%" }}
        data={rows}
        firstItemIndex={firstItemIndex}
        itemContent={itemContent}
        computeItemKey={computeKey}
        followOutput={followOutput}
        atBottomStateChange={onAtBottomStateChange}
        startReached={onStartReached}
        endReached={onEndReached}
        increaseViewportBy={{ top: 200, bottom: 200 }}
        defaultItemHeight={22}
      />
      {(loadingPrev || loadingNext) && (
        <div className="pointer-events-none absolute bottom-2 right-2 text-[10px] text-log-pane-foreground/50">
          {loadingPrev && loadingNext ? "Loading…" : loadingPrev ? "Loading older…" : "Loading newer…"}
        </div>
      )}
    </div>
  );
}
