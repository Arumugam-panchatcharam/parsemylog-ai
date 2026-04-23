import { useCallback, useState } from "react";

/** Large enough for many prepends while staying positive (Virtuoso requirement). */
export const INITIAL_FIRST_ITEM_INDEX = 1_000_000;

export function useLogScrollAnchor() {
  const [firstItemIndex, setFirstItemIndex] = useState(INITIAL_FIRST_ITEM_INDEX);

  const resetAnchor = useCallback(() => {
    setFirstItemIndex(INITIAL_FIRST_ITEM_INDEX);
  }, []);

  /** Call **before** prepending `count` rows to `data` (inverse infinite scroll). */
  const beforePrepend = useCallback((count: number) => {
    if (count <= 0) return;
    setFirstItemIndex((f) => f - count);
  }, []);

  /** Call after evicting `count` rows from the **head** of `data` (sliding window). */
  const afterEvictHead = useCallback((count: number) => {
    if (count <= 0) return;
    setFirstItemIndex((f) => f + count);
  }, []);

  return { firstItemIndex, setFirstItemIndex, resetAnchor, beforePrepend, afterEvictHead };
}
