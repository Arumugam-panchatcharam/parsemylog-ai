import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { INITIAL_FIRST_ITEM_INDEX, useLogScrollAnchor } from "../useLogScrollAnchor";

describe("useLogScrollAnchor", () => {
  it("beforePrepend shifts firstItemIndex down by count (prepend scroll stability)", () => {
    const { result } = renderHook(() => useLogScrollAnchor());
    expect(result.current.firstItemIndex).toBe(INITIAL_FIRST_ITEM_INDEX);
    act(() => {
      result.current.beforePrepend(100);
    });
    expect(result.current.firstItemIndex).toBe(INITIAL_FIRST_ITEM_INDEX - 100);
  });

  it("afterEvictHead shifts firstItemIndex up when sliding window drops head rows", () => {
    const { result } = renderHook(() => useLogScrollAnchor());
    act(() => {
      result.current.afterEvictHead(40);
    });
    expect(result.current.firstItemIndex).toBe(INITIAL_FIRST_ITEM_INDEX + 40);
  });
});
