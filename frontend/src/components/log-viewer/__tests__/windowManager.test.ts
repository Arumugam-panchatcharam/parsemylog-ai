import { describe, expect, it } from "vitest";
import {
  mergeRowsAppend,
  mergeRowsPrepend,
  mergeStreamLines,
  toLogRows,
  trimToMaxLines,
} from "../windowManager";

const r = (n: number, t = "x") => ({ id: `L${n}`, lineNumber: n, text: t });

describe("windowManager", () => {
  it("trimToMaxLines evict_head drops oldest and reports evicted count (large dataset window)", () => {
    const rows = Array.from({ length: 25000 }, (_, i) => r(i + 1));
    const { rows: trimmed, evictedFromHead } = trimToMaxLines(rows, 20000, "evict_head");
    expect(trimmed.length).toBe(20000);
    expect(trimmed[0]!.lineNumber).toBe(5001);
    expect(evictedFromHead).toBe(5000);
  });

  it("trimToMaxLines evict_tail drops newest", () => {
    const rows = [r(1), r(2), r(3), r(4), r(5)];
    const { rows: trimmed, evictedFromHead } = trimToMaxLines(rows, 3, "evict_tail");
    expect(trimmed.map((x) => x.lineNumber)).toEqual([1, 2, 3]);
    expect(evictedFromHead).toBe(0);
  });

  it("mergeRowsAppend skips overlap", () => {
    const a = [r(1), r(2)];
    const b = [r(2), r(3), r(4)];
    expect(mergeRowsAppend(a, b).map((x) => x.lineNumber)).toEqual([1, 2, 3, 4]);
  });

  it("mergeRowsPrepend only adds strictly lower line numbers", () => {
    const a = [r(10), r(11)];
    const b = [r(8), r(9), r(10)];
    expect(mergeRowsPrepend(a, b).map((x) => x.lineNumber)).toEqual([8, 9, 10, 11]);
  });

  it("prepend stability: merged order stays ascending by line", () => {
    const current = [r(100), r(101)];
    const chunk = [r(98), r(99)];
    const merged = mergeRowsPrepend(current, chunk);
    const nums = merged.map((x) => x.lineNumber);
    expect(nums).toEqual([98, 99, 100, 101]);
  });

  it("mergeStreamLines assigns increasing line numbers after tail", () => {
    const base = [r(5, "a")];
    const next = mergeStreamLines(base, ["b", "c"], 5);
    expect(next.map((x) => ({ n: x.lineNumber, t: x.text }))).toEqual([
      { n: 5, t: "a" },
      { n: 6, t: "b" },
      { n: 7, t: "c" },
    ]);
  });

  it("toLogRows uses line_numbers when aligned", () => {
    const rows = toLogRows(["a", "b"], [10, 11]);
    expect(rows.map((x) => x.lineNumber)).toEqual([10, 11]);
  });
});
