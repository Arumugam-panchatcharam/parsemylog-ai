/** One rendered row in the virtual list — stable `id` from line number. */
export interface LogRow {
  id: string;
  lineNumber: number;
  text: string;
}

/** Normalized chunk from the data source (API or stream). */
export interface LogChunk {
  lines: string[];
  lineNumbers: number[];
  rows: LogRow[];
  nextCursor?: string;
  prevCursor?: string;
  hasMoreNext: boolean;
  hasMorePrev: boolean;
  page: number;
  totalPages: number;
  totalLines: number;
}

/** Opaque cursor payload (client-side encoding of page fetch params). */
export interface LogCursorPayload {
  v: 1;
  projectId: string;
  filename: string;
  page: number;
  linesPerPage: number;
  cpeId: string | null;
  dedup: boolean;
}

export type TrimMode = "evict_head" | "evict_tail";
