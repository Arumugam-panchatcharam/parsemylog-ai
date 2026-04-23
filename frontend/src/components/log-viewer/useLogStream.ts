import { useCallback, useRef, useState } from "react";

/**
 * Live tail (future): implement a transport that pushes lines into `useRafLineBatcher` →
 * `useVirtualLogFeed.appendStreamLines`. Backend options: SSE endpoint for growing files
 * (mirror chat: `text/event-stream`, nginx `proxy_buffering off` on that route) or polling
 * the last N lines. Keep UI decoupled via a small `LogTailTransport` interface if needed.
 */
export interface LogTailTransport {
  start: (onLines: (lines: readonly string[]) => void) => void;
  stop: () => void;
}

/**
 * Tail-follow: when the list reports `atBottom === false`, following stops;
 * scrolling back to bottom resumes follow (chat / tail -f style).
 */
export function useLogFollowTail(initialFollowing = true) {
  const [isFollowing, setIsFollowing] = useState(initialFollowing);

  const onAtBottomStateChange = useCallback((atBottom: boolean) => {
    if (atBottom) setIsFollowing(true);
    else setIsFollowing(false);
  }, []);

  return { isFollowing, setIsFollowing, onAtBottomStateChange };
}

/**
 * Coalesce many `appendLines` calls into at most one `flush` per animation frame
 * (stability under ~100 lines/sec).
 */
export function useRafLineBatcher(flush: (batch: readonly string[]) => void) {
  const bufRef = useRef<string[]>([]);
  const rafRef = useRef<number | null>(null);

  const appendLines = useCallback(
    (lines: readonly string[]) => {
      if (lines.length === 0) return;
      bufRef.current.push(...lines);
      if (rafRef.current != null) return;
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        const batch = bufRef.current;
        bufRef.current = [];
        if (batch.length > 0) flush(batch);
      });
    },
    [flush],
  );

  const cancel = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    bufRef.current = [];
  }, []);

  return { appendLines, cancel };
}
