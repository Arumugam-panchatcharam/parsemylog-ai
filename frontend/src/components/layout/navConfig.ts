import type { ComponentType } from "react";
import AnalyticsIcon from "@mui/icons-material/Analytics";
import SearchIcon from "@mui/icons-material/Search";
import DescriptionIcon from "@mui/icons-material/Description";
import TimelineIcon from "@mui/icons-material/Timeline";
import MemoryIcon from "@mui/icons-material/Memory";
import ArticleIcon from "@mui/icons-material/Article";
import PsychologyIcon from "@mui/icons-material/Psychology";
import ManageSearchIcon from "@mui/icons-material/ManageSearch";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import ModelTrainingIcon from "@mui/icons-material/ModelTraining";
import HubIcon from "@mui/icons-material/Hub";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import WifiIcon from "@mui/icons-material/Wifi";
import TableChartIcon from "@mui/icons-material/TableChart";

/** MUI icon components accept `style` / `className` like Sidebar usage */
export type NavIcon = ComponentType<{ style?: React.CSSProperties; className?: string }>;

export interface WorkspaceNavItem {
  readonly to: string;
  readonly label: string;
  readonly icon: NavIcon;
}

export const workspaceNav: readonly WorkspaceNavItem[] = [
  { to: "/workspace/viewer", icon: SearchIcon, label: "Log Viewer" },
  { to: "/workspace/pattern", icon: AnalyticsIcon, label: "Pattern" },
  { to: "/workspace/pattern-analyzer", icon: ManageSearchIcon, label: "Pattern Analyzer" },
  { to: "/workspace/telemetry", icon: TimelineIcon, label: "Telemetry" },
  { to: "/workspace/syslog", icon: ArticleIcon, label: "Syslog" },
  { to: "/workspace/selfheal", icon: MemoryIcon, label: "SelfHeal" },
  { to: "/workspace/ai", icon: PsychologyIcon, label: "Semantic Search" },
  { to: "/workspace/cpe-overview", icon: CompareArrowsIcon, label: "CPE Overview" },
  { to: "/workspace/issue-analysis", icon: AccountTreeIcon, label: "Issue Analysis" },
  { to: "/workspace/ml-pipeline", icon: ModelTrainingIcon, label: "ML Pipeline" },
] as const;

export interface MainNavItem {
  readonly to: string;
  readonly label: string;
  readonly icon: NavIcon;
  readonly adminOnly?: boolean;
}

export const mainNav: readonly MainNavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: DescriptionIcon },
  { to: "/knowledge-graph", label: "Knowledge Graph", icon: HubIcon },
  { to: "/pcap", label: "PCAP Analyzer", icon: WifiIcon },
  { to: "/telemetry-csv", label: "Telemetry CSV", icon: TableChartIcon },
  { to: "/admin", label: "Admin", icon: AdminPanelSettingsIcon, adminOnly: true },
] as const;
