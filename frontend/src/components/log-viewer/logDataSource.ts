import type { LogChunk, LogCursorPayload } from "./types";
import { toLogRows } from "./windowManager";

/** API shape from filesApi.getContent */
export interface FileContentResponse {
  lines: string[];
  page: number;
  total_pages: number;
  total_lines: number;
  total_lines_raw?: number;
  dedup_applied?: boolean;
  line_numbers?: number[];
  start_line: number;
  end_line: number;
}

function utf8ToBase64Url(json: string): string {
  const bytes = new TextEncoder().encode(json);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]!);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64UrlToUtf8(b64: string): string {
  const pad = b64.length % 4 === 0 ? "" : "=".repeat(4 - (b64.length % 4));
  const normalized = (b64 + pad).replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(normalized);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

export function encodeCursor(payload: LogCursorPayload): string {
  return utf8ToBase64Url(JSON.stringify(payload));
}

export function decodeCursor(cursor: string): LogCursorPayload | null {
  try {
    const raw = base64UrlToUtf8(cursor);
    const p = JSON.parse(raw) as LogCursorPayload;
    if (p?.v !== 1 || typeof p.projectId !== "string" || typeof p.filename !== "string") return null;
    if (typeof p.page !== "number" || typeof p.linesPerPage !== "number") return null;
    return {
      v: 1,
      projectId: p.projectId,
      filename: p.filename,
      page: p.page,
      linesPerPage: p.linesPerPage,
      cpeId: p.cpeId ?? null,
      dedup: Boolean(p.dedup),
    };
  } catch {
    return null;
  }
}

export function buildCursorPayload(
  base: Omit<LogCursorPayload, "v" | "page"> & { page: number },
): LogCursorPayload {
  return {
    v: 1,
    projectId: base.projectId,
    filename: base.filename,
    page: base.page,
    linesPerPage: base.linesPerPage,
    cpeId: base.cpeId,
    dedup: base.dedup,
  };
}

export function fileContentToLogChunk(data: FileContentResponse, payload: LogCursorPayload): LogChunk {
  const lineNumbers =
    data.line_numbers?.length === data.lines.length
      ? data.line_numbers
      : data.lines.map((_, i) => data.start_line + i);
  const rows = toLogRows(data.lines, lineNumbers);
  const hasMoreNext = data.page < data.total_pages;
  const hasMorePrev = data.page > 1;
  const nextPayload = hasMoreNext ? buildCursorPayload({ ...payload, page: data.page + 1 }) : null;
  const prevPayload = hasMorePrev ? buildCursorPayload({ ...payload, page: data.page - 1 }) : null;
  return {
    lines: data.lines,
    lineNumbers,
    rows,
    nextCursor: nextPayload ? encodeCursor(nextPayload) : undefined,
    prevCursor: prevPayload ? encodeCursor(prevPayload) : undefined,
    hasMoreNext,
    hasMorePrev,
    page: data.page,
    totalPages: data.total_pages,
    totalLines: data.total_lines,
  };
}
