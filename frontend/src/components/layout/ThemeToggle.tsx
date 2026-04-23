import { memo } from "react";
import BrightnessAutoIcon from "@mui/icons-material/BrightnessAuto";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

function ThemeToggleInner() {
  const { theme, resolvedTheme, cycleTheme } = useTheme();

  const modeLabel =
    theme === "system"
      ? `Auto (${resolvedTheme === "dark" ? "dark" : "light"})`
      : theme === "light"
        ? "Light"
        : "Dark";

  const title = `Appearance: ${modeLabel}. Click to cycle (auto, light, dark).`;
  const ariaLabel = `Appearance ${modeLabel}. Cycle theme preference.`;

  return (
    <button
      type="button"
      onClick={cycleTheme}
      title={title}
      aria-label={ariaLabel}
      className={cn(
        "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border",
        "bg-background text-foreground transition-colors",
        "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      {theme === "system" ? (
        <BrightnessAutoIcon sx={{ fontSize: 18 }} />
      ) : theme === "light" ? (
        <LightModeIcon sx={{ fontSize: 18 }} />
      ) : (
        <DarkModeIcon sx={{ fontSize: 18 }} />
      )}
    </button>
  );
}

export const ThemeToggle = memo(ThemeToggleInner);
ThemeToggle.displayName = "ThemeToggle";

export default ThemeToggle;
