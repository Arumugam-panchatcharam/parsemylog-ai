import { describe, expect, it } from "vitest";
import {
  buildCursorPayload,
  decodeCursor,
  encodeCursor,
  fileContentToLogChunk,
  type FileContentResponse,
} from "../logDataSource";

describe("logDataSource", () => {
  it("round-trips cursor encoding", () => {
    const payload = buildCursorPayload({
      projectId: "p1",
      filename: "a.log",
      page: 3,
      linesPerPage: 500,
      cpeId: "cpe",
      dedup: true,
    });
    const enc = encodeCursor(payload);
    const dec = decodeCursor(enc);
    expect(dec).toEqual(payload);
  });

  it("maps API response to LogChunk with cursors", () => {
    const data: FileContentResponse = {
      lines: ["a", "b"],
      page: 2,
      total_pages: 5,
      total_lines: 100,
      line_numbers: [11, 12],
      start_line: 11,
      end_line: 12,
    };
    const payload = buildCursorPayload({
      projectId: "p",
      filename: "f",
      page: 2,
      linesPerPage: 10,
      cpeId: null,
      dedup: false,
    });
    const chunk = fileContentToLogChunk(data, payload);
    expect(chunk.rows.map((r) => r.lineNumber)).toEqual([11, 12]);
    expect(chunk.hasMoreNext).toBe(true);
    expect(chunk.hasMorePrev).toBe(true);
    expect(decodeCursor(chunk.nextCursor!)).toMatchObject({ page: 3 });
    expect(decodeCursor(chunk.prevCursor!)).toMatchObject({ page: 1 });
  });
});
