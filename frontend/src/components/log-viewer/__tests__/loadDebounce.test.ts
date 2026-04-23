import { describe, expect, it, vi, afterEach } from "vitest";

/** Mirrors `LOAD_DEBOUNCE_MS` in useVirtualLogFeed — rapid scroll should coalesce loads. */
const DEBOUNCE_MS = 120;

describe("load debounce pattern (rapid scroll)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("schedules only one trailing call when invoked repeatedly within the window", () => {
    vi.useFakeTimers();
    let calls = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        calls++;
      }, DEBOUNCE_MS);
    };

    schedule();
    schedule();
    schedule();
    expect(calls).toBe(0);
    vi.advanceTimersByTime(DEBOUNCE_MS);
    expect(calls).toBe(1);
  });
});
