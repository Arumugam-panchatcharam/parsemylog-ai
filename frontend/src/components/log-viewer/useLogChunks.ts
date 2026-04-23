import { filesApi } from "@/api/endpoints";
import {
  buildCursorPayload,
  decodeCursor,
  fileContentToLogChunk,
  type FileContentResponse,
} from "./logDataSource";
import type { LogChunk, LogCursorPayload } from "./types";

export async function fetchLogChunk(payload: LogCursorPayload): Promise<LogChunk> {
  const res = await filesApi.getContent(
    payload.projectId,
    payload.filename,
    payload.page,
    payload.linesPerPage,
    payload.cpeId ?? undefined,
    payload.dedup,
  );
  return fileContentToLogChunk(res.data as FileContentResponse, payload);
}

export async function fetchLogChunkByCursor(cursor: string): Promise<LogChunk | null> {
  const payload = decodeCursor(cursor);
  if (!payload) return null;
  return fetchLogChunk(payload);
}

export function makeInitialPayload(
  projectId: string,
  filename: string,
  page: number,
  linesPerPage: number,
  cpeId: string | null | undefined,
  dedup: boolean,
): LogCursorPayload {
  return buildCursorPayload({
    projectId,
    filename,
    page,
    linesPerPage,
    cpeId: cpeId ?? null,
    dedup,
  });
}
