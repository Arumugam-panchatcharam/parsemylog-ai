import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

export interface BreadcrumbItem {
  label: string;
  /** In-app navigation (preferred over external href) */
  to?: string;
  href?: string;
}

export interface PageHeaderProps {
  title: ReactNode;
  description?: string;
  breadcrumbs?: BreadcrumbItem[];
  actions?: ReactNode;
  className?: string;
}

export function PageHeader({ title, description, breadcrumbs, actions, className }: PageHeaderProps) {
  return (
    <header className={cn("mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between", className)}>
      <div className="min-w-0 space-y-1">
        {breadcrumbs && breadcrumbs.length > 0 ? (
          <nav aria-label="Breadcrumb" className="mb-2">
            <ol className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
              {breadcrumbs.map((crumb, i) => (
                <li key={`${crumb.label}-${i}`} className="flex items-center gap-1">
                  {i > 0 ? <span aria-hidden className="text-muted-foreground/60">/</span> : null}
                  {crumb.to ? (
                    <Link to={crumb.to} className="hover:text-foreground underline-offset-2 hover:underline">
                      {crumb.label}
                    </Link>
                  ) : crumb.href ? (
                    <a href={crumb.href} className="hover:text-foreground underline-offset-2 hover:underline">
                      {crumb.label}
                    </a>
                  ) : (
                    <span className={i === breadcrumbs.length - 1 ? "font-medium text-foreground" : ""}>
                      {crumb.label}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </nav>
        ) : null}
        <h1 className="flex flex-wrap items-center gap-2 text-2xl font-bold tracking-tight text-foreground">
          {title}
        </h1>
        {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
