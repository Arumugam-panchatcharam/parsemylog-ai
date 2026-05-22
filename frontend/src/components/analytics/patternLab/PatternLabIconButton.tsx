import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PatternLabIconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  children: ReactNode;
  variant?: "default" | "primary" | "destructive";
}

export default function PatternLabIconButton({
  label,
  children,
  variant = "default",
  className,
  ...props
}: PatternLabIconButtonProps) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border transition-colors",
        "disabled:pointer-events-none disabled:opacity-50",
        variant === "primary" &&
          "border-primary bg-primary text-primary-foreground hover:bg-primary/90",
        variant === "destructive" &&
          "border-destructive/40 text-destructive hover:bg-destructive/10",
        variant === "default" && "border-border bg-background text-foreground hover:bg-muted",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
