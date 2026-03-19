import { cn } from "@/lib/utils";

export type AlertVariant = "default" | "success" | "destructive";

const variantClass: Record<AlertVariant, string> = {
  default: "border-border bg-muted/50 text-foreground",
  success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300",
  destructive: "border-destructive/30 bg-destructive/10 text-destructive",
};

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: AlertVariant;
  title?: string;
}

export function Alert({ className, variant = "default", title, children, role = "alert", ...props }: AlertProps) {
  return (
    <div
      role={role}
      className={cn("rounded-lg border px-3 py-2 text-sm", variantClass[variant], className)}
      {...props}
    >
      {title ? (
        <div className="font-medium">{title}</div>
      ) : null}
      {children ? <div className={title ? "mt-1 text-muted-foreground" : ""}>{children}</div> : null}
    </div>
  );
}
