import { useCallback, useEffect, useRef, useState } from "react";
import { fileContentToLogChunk, type FileContentResponse } from "./logDataSource";
import { fetchLogChunk, makeInitialPayload } from "./useLogChunks";
import { useLogScrollAnchor } from "./useLogScrollAnchor";
import type { LogRow } from "./types";
import {
  mergeRowsAppend,
  mergeRowsPrepend,
  mergeStreamLines,
  trimToMaxLines,
} from "./windowManager";
import { filesApi } from "@/api/endpoints";

export const DEFAULT_MAX_LOG_WINDOW = 20_000;

const LOAD_DEBOUNCE_MS = 120;

interface UseVirtualLogFeedParams {
  projectId: string | null;
  filename: string | null;
  cpeId: string | null | undefined;
  linesPerPage: number;
  dedupApply: boolean;
  currentPage: number;
  /** When dedup patterns for the file change, pass a new string to reload the buffer. */
  dedupFingerprint: string;
  maxLines?: number;
  isFollowing: boolean;
}

export function useVirtualLogFeed({
  projectId,
  filename,
  cpeId,
  linesPerPage,
  dedupApply,
  currentPage,
  dedupFingerprint,
  maxLines = DEFAULT_MAX_LOG_WINDOW,
  isFollowing,
}: UseVirtualLogFeedParams) {
  const { firstItemIndex, resetAnchor, beforePrepend, afterEvictHead } = useLogScrollAnchor();
  const [rows, setRows] = useState<LogRow[]>([]);
  const [minPage, setMinPage] = useState(1);
  const [maxPage, setMaxPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalLines, setTotalLines] = useState(0);
  const [totalLinesRaw, setTotalLinesRaw] = useState<number | null>(null);
  const [dedupAppliedFlag, setDedupAppliedFlag] = useState(false);
  const [contentLoading, setContentLoading] = useState(false);
  const [loadingNext, setLoadingNext] = useState(false);
  const [loadingPrev, setLoadingPrev] = useState(false);

  const isFollowingRef = useRef(isFollowing);
  isFollowingRef.current = isFollowing;

  const loadingNextLock = useRef(false);
  const loadingPrevLock = useRef(false);
  const nextTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const maxLinesRef = useRef(maxLines);
  maxLinesRef.current = maxLines;

  const hasMoreNext = maxPage < totalPages;
  const hasMorePrev = minPage > 1;

  const applyTrim = useCallback(
    (nextRows: LogRow[]): LogRow[] => {
      const cap = maxLinesRef.current;
      const mode = isFollowingRef.current ? "evict_head" : "evict_tail";
      const { rows: trimmed, evictedFromHead } = trimToMaxLines(nextRows, cap, mode);
      if (evictedFromHead > 0) afterEvictHead(evictedFromHead);
      return trimmed;
    },
    [afterEvictHead],
  );

  // Initial / jump load when pagination or file context changes
  useEffect(() => {
    if (!projectId || !filename) {
      setRows([]);
      setTotalLines(0);
      setTotalLinesRaw(null);
      setDedupAppliedFlag(false);
      setTotalPages(1);
      setMinPage(1);
      setMaxPage(1);
      return;
    }

    let cancelled = false;
    setContentLoading(true);
    resetAnchor();

    (async () => {
      try {
        const payload = makeInitialPayload(
          projectId,
          filename,
          currentPage,
          linesPerPage,
          cpeId,
          dedupApply,
        );
        const res = await filesApi.getContent(
          projectId,
          filename,
          currentPage,
          linesPerPage,
          cpeId ?? undefined,
          dedupApply,
        );
        if (cancelled) return;
        const chunk = fileContentToLogChunk(res.data as FileContentResponse, payload);
        const raw = res.data as FileContentResponse;
        setRows(chunk.rows);
        setMinPage(chunk.page);
        setMaxPage(chunk.page);
        setTotalPages(chunk.totalPages);
        setTotalLines(chunk.totalLines);
        setTotalLinesRaw(raw.total_lines_raw ?? null);
        setDedupAppliedFlag(Boolean(raw.dedup_applied));
      } finally {
        if (!cancelled) setContentLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    projectId,
    filename,
    cpeId,
    linesPerPage,
    dedupApply,
    currentPage,
    dedupFingerprint,
    resetAnchor,
  ]);

  const loadNextPage = useCallback(async () => {
    if (!projectId || !filename || loadingNextLock.current) return;
    if (maxPage >= totalPages) return;
    loadingNextLock.current = true;
    setLoadingNext(true);
    try {
      const payload = makeInitialPayload(
        projectId,
        filename,
        maxPage + 1,
        linesPerPage,
        cpeId,
        dedupApply,
      );
      const chunk = await fetchLogChunk(payload);
      setRows((prev) => applyTrim(mergeRowsAppend(prev, chunk.rows)));
      setMaxPage((p) => Math.max(p, chunk.page));
      setTotalPages(chunk.totalPages);
      setTotalLines(chunk.totalLines);
    } finally {
      loadingNextLock.current = false;
      setLoadingNext(false);
    }
  }, [projectId, filename, maxPage, totalPages, linesPerPage, cpeId, dedupApply, applyTrim]);

  const loadPrevPage = useCallback(async () => {
    if (!projectId || !filename || loadingPrevLock.current) return;
    if (minPage <= 1) return;
    loadingPrevLock.current = true;
    setLoadingPrev(true);
    try {
      const payload = makeInitialPayload(
        projectId,
        filename,
        minPage - 1,
        linesPerPage,
        cpeId,
        dedupApply,
      );
      const chunk = await fetchLogChunk(payload);
      const added = chunk.rows.length;
      beforePrepend(added);
      setRows((prev) => {
        const merged = mergeRowsPrepend(prev, chunk.rows);
        const cap = maxLinesRef.current;
        const { rows: trimmed } = trimToMaxLines(merged, cap, "evict_tail");
        return trimmed;
      });
      setMinPage((p) => Math.min(p, chunk.page));
      setTotalPages(chunk.totalPages);
      setTotalLines(chunk.totalLines);
    } finally {
      loadingPrevLock.current = false;
      setLoadingPrev(false);
    }
  }, [projectId, filename, minPage, linesPerPage, cpeId, dedupApply, beforePrepend]);

  const scheduleLoadNext = useCallback(() => {
    if (!hasMoreNext || loadingNextLock.current) return;
    if (nextTimerRef.current) clearTimeout(nextTimerRef.current);
    nextTimerRef.current = setTimeout(() => {
      nextTimerRef.current = null;
      void loadNextPage();
    }, LOAD_DEBOUNCE_MS);
  }, [hasMoreNext, loadNextPage]);

  const scheduleLoadPrev = useCallback(() => {
    if (!hasMorePrev || loadingPrevLock.current) return;
    if (prevTimerRef.current) clearTimeout(prevTimerRef.current);
    prevTimerRef.current = setTimeout(() => {
      prevTimerRef.current = null;
      void loadPrevPage();
    }, LOAD_DEBOUNCE_MS);
  }, [hasMorePrev, loadPrevPage]);

  useEffect(
    () => () => {
      if (nextTimerRef.current) clearTimeout(nextTimerRef.current);
      if (prevTimerRef.current) clearTimeout(prevTimerRef.current);
    },
    [],
  );

  const appendStreamLines = useCallback(
    (lines: readonly string[]) => {
      setRows((prev) => {
        const lastNum =
          prev.length === 0 ? 0 : Math.max(...prev.map((r) => r.lineNumber));
        const merged = mergeStreamLines(prev, lines, lastNum);
        return applyTrim(merged);
      });
    },
    [applyTrim],
  );

  const loadedStartLine = rows.length ? rows[0]!.lineNumber : 0;
  const loadedEndLine = rows.length ? rows[rows.length - 1]!.lineNumber : 0;

  return {
    rows,
    firstItemIndex,
    totalLines,
    totalLinesRaw,
    dedupApplied: dedupAppliedFlag,
    totalPages,
    minPage,
    maxPage,
    loadedStartLine,
    loadedEndLine,
    hasMoreNext,
    hasMorePrev,
    contentLoading,
    loadingNext,
    loadingPrev,
    scheduleLoadNext,
    scheduleLoadPrev,
    appendStreamLines,
  };
}
