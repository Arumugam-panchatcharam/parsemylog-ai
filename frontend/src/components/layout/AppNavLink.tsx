import { NavLink, type NavLinkProps } from "react-router-dom";
import { cn } from "@/lib/utils";

export interface AppNavLinkProps extends Omit<NavLinkProps, "className"> {
  collapsed?: boolean;
  className?: string;
  /**
   * When true, inactive state only tints background on hover (no accent text on hover).
   * Matches legacy “back to dashboard” styling in the workspace sidebar.
   */
  subtleInactive?: boolean;
}

export function AppNavLink({
  collapsed,
  className,
  subtleInactive = false,
  children,
  ...props
}: AppNavLinkProps) {
  return (
    <NavLink
      {...props}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2 px-3 py-2 text-sm rounded-lg transition-colors",
          isActive
            ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
            : cn(
                "text-muted-foreground hover:bg-sidebar-accent",
                !subtleInactive && "hover:text-sidebar-accent-foreground"
              ),
          collapsed && "justify-center px-2",
          className
        )
      }
    >
      {children}
    </NavLink>
  );
}
