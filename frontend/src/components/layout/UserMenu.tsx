import { useState, memo } from "react";
import { useNavigate } from "react-router-dom";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Divider from "@mui/material/Divider";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import SettingsIcon from "@mui/icons-material/Settings";
import LogoutIcon from "@mui/icons-material/Logout";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

export interface UserMenuProps {
  onOpenAbout: () => void;
}

function UserMenuInner({ onOpenAbout }: UserMenuProps) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const open = Boolean(anchorEl);

  if (!user) return null;

  const close = () => setAnchorEl(null);

  return (
    <>
      <button
        type="button"
        onClick={(e) => setAnchorEl(e.currentTarget)}
        title={`Account: ${user.username}`}
        aria-label={`Account menu for ${user.username}`}
        aria-haspopup="true"
        aria-expanded={open}
        className={cn(
          "inline-flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-full border border-border",
          "bg-primary/15 text-sm font-semibold uppercase text-primary transition-colors",
          "hover:bg-primary/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        {user.username.charAt(0)}
      </button>
      <Menu
        anchorEl={anchorEl}
        open={open}
        onClose={close}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
        slotProps={{
          paper: {
            className: "border border-border bg-card text-card-foreground mt-1 min-w-[220px]",
            elevation: 8,
          },
        }}
      >
        <div className="px-3 py-2 border-b border-border">
          <p className="text-sm font-medium text-foreground flex items-center gap-1 truncate">
            {user.username}
            {user.is_admin ? (
              <AdminPanelSettingsIcon sx={{ fontSize: 16, color: "#f9ab00" }} titleAccess="Administrator" />
            ) : null}
          </p>
          {user.email ? (
            <p className="text-xs text-muted-foreground truncate">{user.email}</p>
          ) : null}
        </div>
        <MenuItem
          onClick={() => {
            close();
            onOpenAbout();
          }}
        >
          <ListItemIcon>
            <InfoOutlinedIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>About</ListItemText>
        </MenuItem>
        <MenuItem
          onClick={() => {
            close();
            navigate("/profile");
          }}
        >
          <ListItemIcon>
            <SettingsIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Settings</ListItemText>
        </MenuItem>
        <Divider />
        <MenuItem
          onClick={() => {
            close();
            logout();
          }}
        >
          <ListItemIcon>
            <LogoutIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Log out</ListItemText>
        </MenuItem>
      </Menu>
    </>
  );
}

export const UserMenu = memo(UserMenuInner);
UserMenu.displayName = "UserMenu";

export default UserMenu;
