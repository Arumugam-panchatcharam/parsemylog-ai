import { useState, useMemo, useCallback, useEffect, useRef, useLayoutEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { projectsApi, natcoApi } from "@/api/endpoints";
import type { NatcoInfo } from "@/api/endpoints";
import { useAuth } from "@/hooks/useAuth";
import { useProject } from "@/hooks/useProject";
import { cn, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { Empty } from "@/components/ui/Empty";
import { FullPageLoading } from "@/components/ui/Loading";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import AddIcon from "@mui/icons-material/Add";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import DeleteIcon from "@mui/icons-material/Delete";
import RefreshIcon from "@mui/icons-material/Refresh";
import CalendarTodayIcon from "@mui/icons-material/CalendarToday";
import PublicIcon from "@mui/icons-material/Public";
import WorkIcon from "@mui/icons-material/Work";
import EditIcon from "@mui/icons-material/Edit";
import LabelIcon from "@mui/icons-material/Label";
import SearchIcon from "@mui/icons-material/Search";

const MAX_TAGS = 20;
const MAX_TAG_LEN = 40;

export interface DashboardProject {
  id: string;
  name: string;
  description: string;
  created_at: string;
  project_type?: string;
  tags?: string[];
  natco_id?: number | null;
  natco?: { code: string; name: string } | null;
}

function primaryTagLabel(tags: string[] | undefined): string {
  if (!tags?.length) return "Untagged";
  const sorted = [...tags].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
  return sorted[0]!;
}

interface TagBucket {
  key: string;
  label: string;
  projects: DashboardProject[];
}

interface JobTypeGroup {
  key: string;
  label: string;
  tagBuckets: TagBucket[];
}

interface NatcoGroup {
  key: string;
  label: string;
  /** Short code for tab label (e.g. EU, PL) */
  shortLabel: string;
  projectCount: number;
  jobTypes: JobTypeGroup[];
}

function buildDashboardGroups(projects: DashboardProject[]): NatcoGroup[] {
  const byNatco = new Map<string, DashboardProject[]>();
  for (const p of projects) {
    const code = p.natco?.code ?? "__unassigned__";
    const list = byNatco.get(code) ?? [];
    list.push(p);
    byNatco.set(code, list);
  }

  const natcoKeys = [...byNatco.keys()].sort((a, b) => {
    if (a === "__unassigned__") return 1;
    if (b === "__unassigned__") return -1;
    return a.localeCompare(b, undefined, { sensitivity: "base" });
  });

  const result: NatcoGroup[] = [];
  for (const code of natcoKeys) {
    const plist = byNatco.get(code)!;
    const sample = plist[0];
    const label =
      code === "__unassigned__"
        ? "Unassigned NATCO"
        : `${sample?.natco?.code ?? code} — ${sample?.natco?.name ?? code}`;
    const shortLabel =
      code === "__unassigned__" ? "Unassigned" : (sample?.natco?.code ?? code);

    const normal = plist.filter((p) => (p.project_type || "normal") === "normal");
    const batch = plist.filter((p) => p.project_type === "batch");

    const jobTypes: JobTypeGroup[] = [];

    const makeBuckets = (list: DashboardProject[]): TagBucket[] => {
      const byTag = new Map<string, DashboardProject[]>();
      for (const p of list) {
        const tagKey = primaryTagLabel(p.tags);
        const bucket = byTag.get(tagKey) ?? [];
        bucket.push(p);
        byTag.set(tagKey, bucket);
      }
      const keys = [...byTag.keys()].sort((a, b) => {
        if (a === "Untagged") return 1;
        if (b === "Untagged") return -1;
        return a.localeCompare(b, undefined, { sensitivity: "base" });
      });
      return keys.map((k) => ({
        key: k,
        label: k,
        projects: byTag.get(k)!,
      }));
    };

    if (batch.length > 0) {
      jobTypes.push({
        key: "batch",
        label: "Batch",
        tagBuckets: makeBuckets(batch),
      });
    }
    if (normal.length > 0) {
      jobTypes.push({
        key: "normal",
        label: "Normal",
        tagBuckets: makeBuckets(normal),
      });
    }

    if (jobTypes.length > 0) {
      result.push({
        key: code,
        label,
        shortLabel,
        projectCount: plist.length,
        jobTypes,
      });
    }
  }
  return result;
}

function useTagChipsState(initial: string[]) {
  const [chips, setChips] = useState<string[]>(initial);
  const [draft, setDraft] = useState("");

  const addChip = useCallback((raw: string) => {
    const s = raw.trim();
    if (!s) return;
    if (s.length > MAX_TAG_LEN) return;
    setChips((prev) => {
      if (prev.length >= MAX_TAGS) return prev;
      const low = s.toLowerCase();
      if (prev.some((t) => t.toLowerCase() === low)) return prev;
      const next = [...prev, s];
      next.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
      return next;
    });
    setDraft("");
  }, []);

  const removeChip = useCallback((tag: string) => {
    setChips((prev) => prev.filter((t) => t !== tag));
  }, []);

  const commitDraft = useCallback(() => {
    if (draft.includes(",")) {
      const parts = draft
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean);
      setChips((prev) => {
        let next = [...prev];
        const seenLower = new Set(next.map((t) => t.toLowerCase()));
        for (const part of parts) {
          if (part.length > MAX_TAG_LEN) continue;
          if (next.length >= MAX_TAGS) break;
          const low = part.toLowerCase();
          if (seenLower.has(low)) continue;
          seenLower.add(low);
          next.push(part);
        }
        next.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
        return next;
      });
      setDraft("");
      return;
    }
    addChip(draft);
  }, [draft, addChip]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        commitDraft();
      }
    },
    [commitDraft],
  );

  const reset = useCallback((next: string[]) => {
    setChips([...next].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" })));
    setDraft("");
  }, []);

  return { chips, setChips, draft, setDraft, addChip, removeChip, onKeyDown, commitDraft, reset };
}

interface ProjectCardProps {
  project: DashboardProject;
  onOpen: () => void;
  onEdit: () => void;
  onDelete: () => void;
  /** Hide NATCO chip when already scoped to a NATCO tab */
  hideNatcoChip?: boolean;
  /** Denser layout for large lists */
  compact?: boolean;
}

function ProjectCard({ project: p, onOpen, onEdit, onDelete, hideNatcoChip, compact }: ProjectCardProps) {
  const navigate = useNavigate();
  const pad = compact ? "p-3" : "p-4";
  const titleCls = compact
    ? "font-semibold text-xs leading-tight flex items-center gap-1.5 min-w-0"
    : "font-semibold text-sm leading-snug flex items-start gap-2 min-w-0";

  return (
    <div
      className={cn(
        "group/card relative bg-card border border-border/70 rounded-xl mat-card min-w-0 max-w-full overflow-hidden shadow-sm transition-all duration-150 hover:shadow-md hover:border-primary/30",
        compact ? "hover:-translate-y-px" : "hover:-translate-y-0.5",
      )}
    >
      {!compact ? (
        <div className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-primary/0 via-primary/50 to-primary/0 opacity-0 group-hover/card:opacity-100 transition-opacity" />
      ) : null}
      <div className={cn(pad, "min-w-0 max-w-full")}>
        <div
          className={cn(
            "flex items-start gap-2 min-w-0 max-w-full",
            compact ? "mb-1.5" : "mb-2",
          )}
        >
          <h3 className={cn(titleCls, "flex-1 min-w-0 overflow-hidden")}>
            <span
              className={cn(
                "shrink-0 rounded-md bg-primary/10 text-primary",
                compact ? "p-0.5" : "mt-0.5 rounded-lg p-1",
              )}
            >
              <FolderOpenIcon style={{ fontSize: compact ? 14 : 16 }} />
            </span>
            <span className="min-w-0 truncate" title={p.name}>
              {p.name}
            </span>
          </h3>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
            {p.project_type === "batch" && (
              <span
                className={cn(
                  "px-1 py-0.5 bg-violet-500/15 text-violet-700 dark:text-violet-300 rounded text-[9px] font-bold",
                  !compact && "px-1.5 rounded-md text-[10px] tracking-wide",
                )}
                title="Batch Processing Project"
              >
                BATCH
              </span>
            )}
            {!hideNatcoChip && p.natco && (
              <span
                className={cn(
                  "px-1 py-0.5 bg-sky-500/15 text-sky-800 dark:text-sky-300 rounded text-[9px] font-bold",
                  !compact && "px-1.5 rounded-md text-[10px]",
                )}
                title={p.natco.name}
              >
                {p.natco.code}
              </span>
            )}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onEdit();
              }}
              className={cn(
                "rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-colors",
                compact ? "p-1" : "p-1.5 rounded-lg",
              )}
              title="Edit project"
            >
              <EditIcon style={{ fontSize: compact ? 14 : 16 }} />
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className={cn(
                "rounded-md hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors",
                compact ? "p-1" : "p-1.5 rounded-lg",
              )}
              title="Delete"
            >
              <DeleteIcon style={{ fontSize: compact ? 14 : 16 }} />
            </button>
          </div>
        </div>
        {!compact ? (
          <p
            className="text-xs text-muted-foreground mb-3 line-clamp-2 min-h-[2rem] leading-relaxed min-w-0 max-w-full break-words"
            title={p.description || "No description"}
          >
            {p.description || "No description"}
          </p>
        ) : p.description ? (
          <p
            className="text-[10px] text-muted-foreground mb-1.5 line-clamp-1 min-w-0 max-w-full break-words"
            title={p.description}
          >
            {p.description}
          </p>
        ) : null}
        {p.tags && p.tags.length > 0 ? (
          <div
            className={cn(
              "flex flex-wrap gap-1 min-w-0 max-w-full",
              compact ? "mb-2" : "mb-3 gap-1.5",
            )}
          >
            {(compact ? p.tags.slice(0, 2) : p.tags).map((t) => (
              <span
                key={t}
                className={cn(
                  "inline-flex items-center gap-0.5 rounded-full font-medium bg-secondary/80 text-secondary-foreground border border-border/50",
                  compact ? "px-1.5 py-px text-[9px]" : "px-2 py-0.5 text-[10px]",
                )}
              >
                {!compact ? <LabelIcon style={{ fontSize: 11 }} className="opacity-70" /> : null}
                {t}
              </span>
            ))}
            {compact && p.tags.length > 2 ? (
              <span className="text-[9px] text-muted-foreground px-1">+{p.tags.length - 2}</span>
            ) : null}
          </div>
        ) : null}
        <div
          className={cn(
            "flex flex-wrap items-center justify-between gap-x-2 gap-y-2 min-w-0 max-w-full border-border/50",
            compact ? "pt-1 border-t" : "pt-1 border-t",
          )}
        >
          <span
            className={cn(
              "text-muted-foreground flex items-center gap-1 tabular-nums min-w-0 shrink",
              compact ? "text-[10px]" : "text-[11px]",
            )}
          >
            <CalendarTodayIcon style={{ fontSize: compact ? 11 : 13 }} className="opacity-70 shrink-0" />
            <span className="truncate">{formatDate(p.created_at)}</span>
          </span>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
            {p.project_type === "batch" && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate(`/projects/${p.id}/batch-jobs`);
                }}
                className={cn(
                  "rounded-md font-medium transition-colors flex items-center gap-0.5 bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border/60",
                  compact ? "px-2 py-1 text-[10px]" : "px-3 py-1.5 text-xs rounded-lg gap-1",
                )}
                title="Batch Jobs"
              >
                <WorkIcon style={{ fontSize: compact ? 12 : 14 }} />
                Jobs
              </button>
            )}
            <button
              type="button"
              onClick={onOpen}
              title="Open project in log viewer"
              className={cn(
                "font-semibold bg-primary text-primary-foreground shadow-sm hover:brightness-110 transition-all rounded-md",
                compact ? "px-2 py-1 text-[10px]" : "px-3 py-1.5 text-xs rounded-lg",
              )}
            >
              Open
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function projectMatchesQuery(p: DashboardProject, q: string): boolean {
  const s = q.trim().toLowerCase();
  if (!s) return true;
  if (p.name.toLowerCase().includes(s)) return true;
  if ((p.description || "").toLowerCase().includes(s)) return true;
  if ((p.tags || []).some((t) => t.toLowerCase().includes(s))) return true;
  return false;
}

type LayoutRow =
  | { kind: "heading"; id: string; label: string; sub?: string; jobKey: "normal" | "batch" }
  | { kind: "subheading"; id: string; label: string; count: number }
  | { kind: "gridRow"; id: string; projects: DashboardProject[] };

function buildLayoutRows(group: NatcoGroup, columnCount: number, search: string): LayoutRow[] {
  const cols = Math.max(1, columnCount);
  const rows: LayoutRow[] = [];

  for (const jt of group.jobTypes) {
    rows.push({
      kind: "heading",
      id: `jt-${jt.key}`,
      label: `${jt.label} jobs`,
      sub: jt.key === "batch" ? "Bulk CPE processing" : "Standard log upload and analysis",
           jobKey: jt.key === "batch" ? "batch" : "normal",
    });

    for (const bucket of jt.tagBuckets) {
      const filtered = bucket.projects.filter((p) => projectMatchesQuery(p, search));
      if (!filtered.length) continue;

      rows.push({
        kind: "subheading",
        id: `sub-${jt.key}-${bucket.key}`,
        label: bucket.label,
        count: filtered.length,
      });

      for (let i = 0; i < filtered.length; i += cols) {
        rows.push({
          kind: "gridRow",
          id: `row-${jt.key}-${bucket.key}-${i}`,
          projects: filtered.slice(i, i + cols),
        });
      }
    }
  }

  return rows;
}

function useGridColumnCount(containerRef: React.RefObject<HTMLDivElement | null>, minCellPx: number): number {
  const [cols, setCols] = useState(() =>
    typeof window !== "undefined" ? Math.max(1, Math.floor(window.innerWidth / minCellPx)) : 4,
  );

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const w = el.getBoundingClientRect().width;
      const next = Math.max(1, Math.floor(w / minCellPx));
      setCols((c) => (c !== next ? next : c));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [minCellPx]);

  return cols;
}

const VIRTUAL_THRESHOLD = 24;

function NatcoProjectsPane({
  group,
  search,
  onSearchChange,
  onOpenProject,
  onEdit,
  onDelete,
}: {
  group: NatcoGroup;
  search: string;
  onSearchChange: (value: string) => void;
  onOpenProject: (id: string, name: string) => void;
  onEdit: (p: DashboardProject) => void;
  onDelete: (id: string) => void;
}) {
  const widthRef = useRef<HTMLDivElement>(null);
  const compact = group.projectCount >= 40;
  const minCell = compact ? 200 : 248;
  const columnCount = useGridColumnCount(widthRef, minCell);

  const layoutRows = useMemo(
    () => buildLayoutRows(group, columnCount, search),
    [group, columnCount, search],
  );

  const gridRowCount = useMemo(
    () => layoutRows.filter((r) => r.kind === "gridRow").length,
    [layoutRows],
  );

  const useVirtual = gridRowCount >= VIRTUAL_THRESHOLD;

  const virtualizer = useWindowVirtualizer({
    count: useVirtual ? layoutRows.length : 0,
    estimateSize: (index) => {
      const row = layoutRows[index];
      if (!row) return 48;
      if (row.kind === "heading") return compact ? 56 : 64;
      if (row.kind === "subheading") return 36;
      return compact ? 124 : 172;
    },
    overscan: 8,
  });

  const filteredTotal = useMemo(() => {
    let n = 0;
    for (const jt of group.jobTypes) {
      for (const b of jt.tagBuckets) {
        n += b.projects.filter((p) => projectMatchesQuery(p, search)).length;
      }
    }
    return n;
  }, [group, search]);

  const renderGridRow = (projects: DashboardProject[], key: string) => (
    <div
      key={key}
      className="grid gap-3 w-full"
      style={{
        gridTemplateColumns: `repeat(${columnCount}, minmax(0, 1fr))`,
      }}
    >
      {projects.map((p) => (
        <ProjectCard
          key={p.id}
          project={p}
          compact={compact}
          hideNatcoChip
          onOpen={() => onOpenProject(p.id, p.name)}
          onEdit={() => onEdit(p)}
          onDelete={() => onDelete(p.id)}
        />
      ))}
    </div>
  );

  const renderRow = (row: LayoutRow, layoutIndex: number) => {
    if (row.kind === "heading") {
      return (
        <div
          className={cn(
            "flex items-center gap-3 w-full pb-1",
            layoutIndex > 0 ? "mt-1 pt-8 border-t border-border/40" : "",
          )}
        >
          <div
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
              row.jobKey === "batch"
                ? "bg-violet-500/15 text-violet-700 dark:text-violet-300"
                : "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
            )}
          >
            {row.jobKey === "batch" ? (
              <WorkIcon style={{ fontSize: 18 }} />
            ) : (
              <FolderOpenIcon style={{ fontSize: 18 }} />
            )}
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold tracking-tight">{row.label}</h3>
            {row.sub ? <p className="text-xs text-muted-foreground">{row.sub}</p> : null}
          </div>
        </div>
      );
    }
    if (row.kind === "subheading") {
      return (
        <div className="flex items-center gap-2 pt-4 pb-1">
          <LabelIcon style={{ fontSize: 15 }} className="text-muted-foreground shrink-0" />
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{row.label}</span>
          <span className="text-[11px] tabular-nums text-muted-foreground/80">({row.count})</span>
        </div>
      );
    }
    return renderGridRow(row.projects, row.id);
  };

  return (
    <div ref={widthRef} className="w-full min-w-0">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4 pb-3 border-b border-border/50">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Active region</p>
          <p className="text-base font-semibold tracking-tight truncate">{group.label}</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            <span className="tabular-nums font-medium text-foreground">{filteredTotal}</span>
            {search.trim() ? " matching" : ""} of{" "}
            <span className="tabular-nums">{group.projectCount}</span> projects
          </p>
        </div>
        <div className="relative w-full sm:max-w-md shrink-0">
          <SearchIcon
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
            style={{ fontSize: 18 }}
          />
          <input
            type="search"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search name, description, tags…"
            autoComplete="off"
            className="w-full pl-9 pr-3 py-2 text-sm border border-input rounded-lg bg-background shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
      </div>

      {layoutRows.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8 text-center border border-dashed border-border rounded-xl">
          No projects match your search.
        </p>
      ) : useVirtual ? (
        <div
          className="w-full relative"
          style={{
            height: `${virtualizer.getTotalSize()}px`,
          }}
        >
          {virtualizer.getVirtualItems().map((vItem) => {
            const row = layoutRows[vItem.index];
            if (!row) return null;
            return (
              <div
                key={row.id}
                data-index={vItem.index}
                ref={virtualizer.measureElement}
                className="absolute left-0 top-0 w-full px-0.5"
                style={{
                  transform: `translateY(${vItem.start}px)`,
                }}
              >
                {renderRow(row, vItem.index)}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="flex flex-col gap-3">{layoutRows.map((row, i) => renderRow(row, i))}</div>
      )}
    </div>
  );
}

function TagsField({
  chips,
  draft,
  setDraft,
  removeChip,
  onKeyDown,
  onBlurCommit,
}: {
  chips: string[];
  draft: string;
  setDraft: (v: string) => void;
  removeChip: (t: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  onBlurCommit: () => void;
}) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1 flex items-center gap-1">
        <LabelIcon style={{ fontSize: 16 }} /> Tags (optional)
      </label>
      <div className="flex flex-wrap gap-1 min-h-[2.5rem] px-2 py-1.5 border border-input rounded-lg bg-background focus-within:ring-2 focus-within:ring-ring">
        {chips.map((t) => (
          <span
            key={t}
            className="inline-flex items-center gap-0.5 pl-2 pr-1 py-0.5 rounded-md text-xs bg-muted"
          >
            {t}
            <button
              type="button"
              className="p-0.5 rounded hover:bg-background"
              onClick={() => removeChip(t)}
              aria-label={`Remove ${t}`}
            >
              ×
            </button>
          </span>
        ))}
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={onBlurCommit}
          placeholder={chips.length ? "" : "Type and press Enter…"}
          className="flex-1 min-w-[120px] text-sm bg-transparent outline-none py-1"
        />
      </div>
      <p className="text-xs text-muted-foreground mt-1">
        Up to {MAX_TAGS} tags, {MAX_TAG_LEN} characters each. Comma or Enter adds a tag.
      </p>
    </div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { setProject } = useProject();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newNatcoId, setNewNatcoId] = useState<number | null>(null);
  const [newProjectType, setNewProjectType] = useState<"normal" | "batch">("normal");
  const createTags = useTagChipsState([]);

  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [editProject, setEditProject] = useState<DashboardProject | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editNatcoId, setEditNatcoId] = useState<number | null>(null);
  const [editProjectType, setEditProjectType] = useState<"normal" | "batch">("normal");
  const editTags = useTagChipsState([]);

  const { data: projects, isLoading, refetch } = useQuery({
    queryKey: ["projects", user?.id],
    queryFn: async () => (await projectsApi.list()).data as DashboardProject[],
    enabled: !!user,
  });

  const { data: natcos } = useQuery({
    queryKey: ["natcosList"],
    queryFn: async () => (await natcoApi.list()).data,
  });

  const grouped = useMemo(() => (projects?.length ? buildDashboardGroups(projects) : []), [projects]);

  const [activeNatcoKey, setActiveNatcoKey] = useState<string | null>(null);

  useEffect(() => {
    if (!grouped.length) {
      setActiveNatcoKey(null);
      return;
    }
    setActiveNatcoKey((prev) => {
      if (prev && grouped.some((g) => g.key === prev)) return prev;
      return grouped[0]!.key;
    });
  }, [grouped]);

  const activeNatcoGroup = useMemo(() => {
    if (!grouped.length) return null;
    if (activeNatcoKey && grouped.some((g) => g.key === activeNatcoKey)) {
      return grouped.find((g) => g.key === activeNatcoKey)!;
    }
    return grouped[0]!;
  }, [grouped, activeNatcoKey]);

  const [projectSearch, setProjectSearch] = useState("");

  useEffect(() => {
    setProjectSearch("");
  }, [activeNatcoKey]);

  const resolvedNatcoId = useMemo(() => {
    if (newNatcoId !== null) return newNatcoId;
    if (natcos?.length === 1) return natcos[0].id;
    return null;
  }, [newNatcoId, natcos]);

  const openEdit = (p: DashboardProject) => {
    setEditProject(p);
    setEditName(p.name);
    setEditDesc(p.description || "");
    setEditNatcoId(p.natco_id ?? null);
    setEditProjectType(p.project_type === "batch" ? "batch" : "normal");
    editTags.reset(p.tags ?? []);
  };

  const createMutation = useMutation({
    mutationFn: () => {
      if (!resolvedNatcoId) {
        throw new Error("NATCO selection is required");
      }
      return projectsApi.create(
        newName,
        newDesc,
        resolvedNatcoId,
        newProjectType,
        createTags.chips.length ? createTags.chips : undefined,
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", user?.id] });
      setShowCreate(false);
      setNewName("");
      setNewDesc("");
      setNewNatcoId(null);
      setNewProjectType("normal");
      createTags.reset([]);
    },
  });

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!editProject || !editNatcoId) {
        throw new Error("NATCO selection is required");
      }
      return projectsApi.update(editProject.id, {
        name: editName.trim(),
        description: editDesc.trim(),
        natco_id: editNatcoId,
        project_type: editProjectType,
        tags: editTags.chips,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", user?.id] });
      setEditProject(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => projectsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", user?.id] });
      setDeleteId(null);
    },
  });

  const openProject = (id: string, name: string) => {
    setProject(id, name, user!.id);
    navigate("/workspace/viewer");
  };

  return (
    <PageContainer className="max-w-none w-full px-3 sm:px-5 lg:px-6 xl:px-8">
      <PageHeader
        title={
          <>
            <FolderOpenIcon style={{ fontSize: 28 }} aria-hidden />
            My Projects
          </>
        }
        description={`Welcome back, ${user?.username ?? ""}`}
        actions={
          <>
            <Button
              variant="outline"
              size="icon"
              title="Refresh"
              aria-label="Refresh projects"
              onClick={() => refetch()}
            >
              <RefreshIcon style={{ fontSize: 18 }} />
            </Button>
            <Button title="Create a new project" onClick={() => setShowCreate(true)}>
              <AddIcon style={{ fontSize: 18 }} /> New Project
            </Button>
          </>
        }
      />

      {isLoading ? (
        <FullPageLoading label="Loading projects…" />
      ) : (
        <>
          {projects?.length === 0 ? (
            <Empty
              icon={<FolderOpenIcon style={{ fontSize: 48, color: "#9aa0a6" }} />}
              title="No projects yet"
              description="Create your first project to get started"
              actionLabel="New project"
              onAction={() => setShowCreate(true)}
            />
          ) : null}

          {projects && projects.length > 0 ? (
            <div className="space-y-4 w-full min-w-0">
              <div className="sticky top-0 z-10 -mx-0.5 px-0.5 pt-1 pb-2 bg-gradient-to-b from-background from-70% via-background/90 to-transparent">
                <div
                  role="tablist"
                  aria-label="NATCO regions"
                  className="flex gap-2 overflow-x-auto pb-1 scroll-smooth [scrollbar-width:thin]"
                >
                  {grouped.map((g) => {
                    const selected = g.key === activeNatcoGroup?.key;
                    return (
                      <button
                        key={g.key}
                        type="button"
                        role="tab"
                        aria-selected={selected}
                        id={`natco-tab-${g.key}`}
                        onClick={() => setActiveNatcoKey(g.key)}
                        className={cn(
                          "inline-flex shrink-0 items-center gap-2 rounded-full border px-3.5 sm:px-4 py-2 text-sm font-medium transition-all duration-200",
                          selected
                            ? "border-primary bg-primary text-primary-foreground shadow-md ring-2 ring-primary/20"
                            : "border-border/70 bg-muted/50 text-muted-foreground hover:border-border hover:bg-muted hover:text-foreground",
                        )}
                      >
                        <PublicIcon
                          style={{ fontSize: 18 }}
                          className={cn("shrink-0", selected ? "opacity-95" : "opacity-55")}
                        />
                        <span className="whitespace-nowrap">{g.shortLabel}</span>
                        <span
                          className={cn(
                            "tabular-nums rounded-full px-2 py-0.5 text-[11px] font-semibold min-w-[1.5rem] text-center",
                            selected ? "bg-primary-foreground/20" : "bg-background/90 text-foreground/80",
                          )}
                        >
                          {g.projectCount}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {activeNatcoGroup ? (
                <div
                  role="tabpanel"
                  id={`natco-panel-${activeNatcoGroup.key}`}
                  aria-labelledby={`natco-tab-${activeNatcoGroup.key}`}
                >
                  <NatcoProjectsPane
                    group={activeNatcoGroup}
                    search={projectSearch}
                    onSearchChange={setProjectSearch}
                    onOpenProject={openProject}
                    onEdit={openEdit}
                    onDelete={setDeleteId}
                  />
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      )}

      {/* Create Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border border-border rounded-2xl shadow-lg p-6 w-full max-w-md max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold mb-4">Create New Project</h3>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                createMutation.mutate();
              }}
              className="space-y-3"
            >
              <div>
                <label className="block text-sm font-medium mb-1">Project Name</label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Description (optional)</label>
                <textarea
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                  rows={3}
                />
              </div>
              <TagsField
                chips={createTags.chips}
                draft={createTags.draft}
                setDraft={createTags.setDraft}
                removeChip={createTags.removeChip}
                onKeyDown={createTags.onKeyDown}
                onBlurCommit={() => createTags.commitDraft()}
              />
              {natcos && natcos.length > 0 && (
                <div>
                  <label className="block text-sm font-medium mb-1 flex items-center gap-1">
                    <PublicIcon style={{ fontSize: 16 }} /> NATCO <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={resolvedNatcoId !== null ? String(resolvedNatcoId) : ""}
                    onChange={(e) => setNewNatcoId(e.target.value ? Number(e.target.value) : null)}
                    title="Select a country/operator for pattern management"
                    className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring text-sm"
                    required
                  >
                    <option value="">-- Select NATCO --</option>
                    {natcos.map((n: NatcoInfo) => (
                      <option key={n.id} value={n.id}>
                        {n.code} - {n.name}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-muted-foreground mt-1">
                    Required: Each project must have a NATCO for pattern management.
                  </p>
                </div>
              )}
              {(!natcos || natcos.length === 0) && (
                <div className="px-3 py-2 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 text-xs rounded">
                  No NATCOs available. Please contact admin to create NATCOs before creating projects.
                </div>
              )}
              <div>
                <label className="block text-sm font-medium mb-1">Project Type</label>
                <div className="space-y-2">
                  <label
                    className="flex items-start gap-2 cursor-pointer p-2 border border-border rounded-lg hover:bg-muted/50 transition-colors"
                    title="Standard project for log analysis"
                  >
                    <input
                      type="radio"
                      name="projectType"
                      value="normal"
                      checked={newProjectType === "normal"}
                      onChange={(e) => setNewProjectType(e.target.value as "normal" | "batch")}
                      className="mt-0.5"
                    />
                    <div className="flex-1">
                      <div className="font-medium text-sm">Normal Processing</div>
                      <div className="text-xs text-muted-foreground">Upload log files via UI for analysis</div>
                    </div>
                  </label>
                  <label
                    className="flex items-start gap-2 cursor-pointer p-2 border border-border rounded-lg hover:bg-muted/50 transition-colors"
                    title="Batch processing project for bulk CPE analysis"
                  >
                    <input
                      type="radio"
                      name="projectType"
                      value="batch"
                      checked={newProjectType === "batch"}
                      onChange={(e) => setNewProjectType(e.target.value as "normal" | "batch")}
                      className="mt-0.5"
                    />
                    <div className="flex-1">
                      <div className="font-medium text-sm">Batch Processing</div>
                      <div className="text-xs text-muted-foreground">Process large batches of CPE logs from server</div>
                    </div>
                  </label>
                </div>
              </div>
              {createMutation.isError && (
                <p className="text-sm text-destructive">
                  {(createMutation.error as Error)?.message || "Could not create project"}
                </p>
              )}
              <div className="flex gap-2 pt-2">
                <button
                  type="submit"
                  disabled={createMutation.isPending || !newName.trim() || !resolvedNatcoId}
                  className="flex-1 py-2.5 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 disabled:opacity-50"
                >
                  {createMutation.isPending ? "Creating..." : "Create Project"}
                </button>
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="flex-1 py-2.5 border border-border rounded-lg hover:bg-muted"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {editProject && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border border-border rounded-2xl shadow-lg p-6 w-full max-w-md max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold mb-4">Edit Project</h3>
            {!natcos?.length ? (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground py-2">Loading NATCO list…</p>
                <button
                  type="button"
                  onClick={() => setEditProject(null)}
                  className="w-full py-2.5 border border-border rounded-lg hover:bg-muted"
                >
                  Cancel
                </button>
              </div>
            ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                updateMutation.mutate();
              }}
              className="space-y-3"
            >
              <div>
                <label className="block text-sm font-medium mb-1">Project Name</label>
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Description (optional)</label>
                <textarea
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                  rows={3}
                />
              </div>
              <TagsField
                chips={editTags.chips}
                draft={editTags.draft}
                setDraft={editTags.setDraft}
                removeChip={editTags.removeChip}
                onKeyDown={editTags.onKeyDown}
                onBlurCommit={() => editTags.commitDraft()}
              />
              <div>
                <label className="block text-sm font-medium mb-1 flex items-center gap-1">
                  <PublicIcon style={{ fontSize: 16 }} /> NATCO <span className="text-red-500">*</span>
                </label>
                <select
                  value={editNatcoId !== null ? String(editNatcoId) : ""}
                  onChange={(e) => setEditNatcoId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring text-sm"
                  required
                >
                  <option value="">-- Select NATCO --</option>
                  {natcos.map((n: NatcoInfo) => (
                    <option key={n.id} value={n.id}>
                      {n.code} - {n.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Project Type</label>
                <div className="space-y-2">
                  <label className="flex items-start gap-2 cursor-pointer p-2 border border-border rounded-lg hover:bg-muted/50 transition-colors">
                    <input
                      type="radio"
                      name="editProjectType"
                      value="normal"
                      checked={editProjectType === "normal"}
                      onChange={(e) => setEditProjectType(e.target.value as "normal" | "batch")}
                      className="mt-0.5"
                    />
                    <div className="flex-1">
                      <div className="font-medium text-sm">Normal Processing</div>
                    </div>
                  </label>
                  <label className="flex items-start gap-2 cursor-pointer p-2 border border-border rounded-lg hover:bg-muted/50 transition-colors">
                    <input
                      type="radio"
                      name="editProjectType"
                      value="batch"
                      checked={editProjectType === "batch"}
                      onChange={(e) => setEditProjectType(e.target.value as "normal" | "batch")}
                      className="mt-0.5"
                    />
                    <div className="flex-1">
                      <div className="font-medium text-sm">Batch Processing</div>
                    </div>
                  </label>
                </div>
              </div>
              {updateMutation.isError && (
                <p className="text-sm text-destructive">
                  {(updateMutation.error as Error)?.message || "Could not update project"}
                </p>
              )}
              <div className="flex gap-2 pt-2">
                <button
                  type="submit"
                  disabled={updateMutation.isPending || !editName.trim() || !editNatcoId}
                  className="flex-1 py-2.5 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 disabled:opacity-50"
                >
                  {updateMutation.isPending ? "Saving..." : "Save"}
                </button>
                <button
                  type="button"
                  onClick={() => setEditProject(null)}
                  className="flex-1 py-2.5 border border-border rounded-lg hover:bg-muted"
                >
                  Cancel
                </button>
              </div>
            </form>
            )}
          </div>
        </div>
      )}

      {/* Delete Confirmation */}
      {deleteId && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border border-border rounded-2xl shadow-lg p-6 w-full max-w-sm">
            <h3 className="text-lg font-semibold mb-2">Delete Project</h3>
            <p className="text-sm text-muted-foreground mb-1">Are you sure? This cannot be undone.</p>
            <p className="text-sm text-destructive font-medium mb-4">All files and data will be permanently lost.</p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => deleteMutation.mutate(deleteId)}
                disabled={deleteMutation.isPending}
                className="flex-1 py-2.5 bg-destructive text-destructive-foreground rounded-lg font-medium hover:opacity-90 disabled:opacity-50"
              >
                {deleteMutation.isPending ? "Deleting..." : "Delete"}
              </button>
              <button
                type="button"
                onClick={() => setDeleteId(null)}
                className="flex-1 py-2.5 border border-border rounded-lg hover:bg-muted"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </PageContainer>
  );
}
