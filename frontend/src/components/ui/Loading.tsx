import { cn } from "@/lib/utils";

export interface LoadingProps {
  className?: string;
  label?: string;
  size?: "sm" | "md" | "lg";
}

const sizeMap = {
  sm: "h-5 w-5 border-2",
  md: "h-8 w-8 border-[3px]",
  lg: "h-12 w-12 border-4",
} as const;

export function Loading({ className, label, size = "md" }: LoadingProps) {
  return (
    <div
      className={cn("flex flex-col items-center justify-center gap-3", className)}
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div
        className={cn(
          "animate-spin rounded-full border-primary border-t-transparent",
          sizeMap[size]
        )}
        aria-hidden
      />
      {label ? <span className="text-sm text-muted-foreground">{label}</span> : null}
    </div>
  );
}

export function FullPageLoading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="min-h-[40vh] flex items-center justify-center p-8">
      <Loading size="lg" label={label} />
    </div>
  );
}
