import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useLogFollowTail, useRafLineBatcher } from "../useLogStream";

describe("useLogStream", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "requestAnimationFrame",
      (cb: FrameRequestCallback) => {
        queueMicrotask(() => cb(0));
        return 1;
      },
    );
    vi.stubGlobal("cancelAnimationFrame", () => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("useRafLineBatcher coalesces many appendLines into one flush per frame (streaming stability)", async () => {
    const flushed: string[][] = [];
    const { result } = renderHook(() =>
      useRafLineBatcher((batch) => {
        flushed.push([...batch]);
      }),
    );

    await act(async () => {
      result.current.appendLines(["1", "2"]);
      result.current.appendLines(["3"]);
    });

    expect(flushed.length).toBe(1);
    expect(flushed[0]).toEqual(["1", "2", "3"]);
  });

  it("useLogFollowTail stops following when not at bottom", () => {
    const { result } = renderHook(() => useLogFollowTail(true));
    expect(result.current.isFollowing).toBe(true);
    act(() => {
      result.current.onAtBottomStateChange(false);
    });
    expect(result.current.isFollowing).toBe(false);
    act(() => {
      result.current.onAtBottomStateChange(true);
    });
    expect(result.current.isFollowing).toBe(true);
  });
});
