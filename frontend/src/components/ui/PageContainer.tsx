import { cn } from "@/lib/utils";

export interface PageContainerProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Narrower reading width for forms / detail pages */
  narrow?: boolean;
}

export function PageContainer({ className, narrow, ...props }: PageContainerProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full p-4 sm:p-6",
        narrow ? "max-w-3xl" : "max-w-7xl",
        className
      )}
      {...props}
    />
  );
}
