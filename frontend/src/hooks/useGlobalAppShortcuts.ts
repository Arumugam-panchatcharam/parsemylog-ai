import { useEffect } from "react";

const OPEN_ABOUT_EVENT = "parsemylog:open-about";

/**
 * Global shortcuts: Cmd/Ctrl+/ opens About; Cmd/Ctrl+K focuses first `[data-command-search]` if present.
 */
export function useGlobalAppShortcuts(): void {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;

      if (e.key === "/") {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent(OPEN_ABOUT_EVENT));
        return;
      }

      if (e.key.toLowerCase() === "k") {
        e.preventDefault();
        document.querySelector<HTMLElement>("[data-command-search]")?.focus();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}

export { OPEN_ABOUT_EVENT };
