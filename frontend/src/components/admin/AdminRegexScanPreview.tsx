import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { adminApi } from "@/api/endpoints";
import type {
  PatternAnalyzerScanResult,
  RegexScanProgressPayload,
  UserPattern,
} from "@/api/endpoints";
import { runPatternAnalyzerScan } from "@/lib/patternAnalyzerScanRunner";
import CircularProgress from "@mui/material/CircularProgress";
import LinearProgress from "@mui/material/LinearProgress";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ManageSearchIcon from "@mui/icons-material/ManageSearch";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";

const PREVIEW_BUCKET_MINUTES = 60;

interface AdminUserProjectRow {
  id: string | number;
  name: string;
}

interface AdminRegexScanPreviewProps {
  patterns: UserPattern[];
  /** When set (e.g. submission submitter), prefills the user selector */
  defaultUserId?: number;
}

export function AdminRegexScanPreview({ patterns, defaultUserId }: AdminRegexScanPreviewProps) {
  const cpeIdRef = useRef<string | null>(null);

  const [open, setOpen] = useState(false);
  const [userId, setUserId] = useState<number | "">("");
  const [projectId, setProjectId] = useState("");
  const [cpeId, setCpeId] = useState("");
  const [filterPreNtp, setFilterPreNtp] = useState(true);
  const [filterShortReboots, setFilterShortReboots] = useState(true);
  const [scanProgress, setScanProgress] = useState<RegexScanProgressPayload | null>(null);
  const [previewResult, setPreviewResult] = useState<PatternAnalyzerScanResult | null>(null);
  const [statusMsg, setStatusMsg] = useState("");

  useEffect(() => {
    if (defaultUserId != null) {
      setUserId(defaultUserId);
    }
  }, [defaultUserId]);

  useEffect(() => {
    cpeIdRef.current = cpeId || null;
  }, [cpeId]);

  const enabledPatterns = useMemo(
    () => patterns.filter((p) => p.enabled && p.regex.trim()),
    [patterns],
  );

  const { data: users, isLoading: usersLoading } = useQuery({
    queryKey: ["adminUsers"],
    queryFn: async () => (await adminApi.listUsers()).data as Array<{ id: number; username: string }>,
    enabled: open,
  });

  const { data: userProjectsPayload, isLoading: projectsLoading } = useQuery({
    queryKey: ["adminRegexPreviewProjects", userId],
    queryFn: async () => (await adminApi.userProjects(userId as number)).data as {
      username: string;
      projects: AdminUserProjectRow[];
    },
    enabled: open && typeof userId === "number",
  });

  const { data: cpes, isLoading: cpesLoading } = useQuery({
    queryKey: ["adminRegexPreviewCpes", projectId],
    queryFn: async () => (await adminApi.listProjectCpes(projectId)).data,
    enabled: open && !!projectId,
  });

  useEffect(() => {
    if (!open) return;
    setProjectId("");
    setCpeId("");
    setPreviewResult(null);
    setScanProgress(null);
    setStatusMsg("");
  }, [open, userId]);

  useEffect(() => {
    if (!open) return;
    setCpeId("");
    setPreviewResult(null);
  }, [open, projectId]);

  const scanMutation = useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error("Select a project");
      const dbgCpe = cpeId.trim() || null;

      setPreviewResult(null);
      setStatusMsg("Scanning uploaded logs…");
      setScanProgress({
        status: "running",
        current: 0,
        total: Math.max(enabledPatterns.length, 1),
        pattern_name: null,
        error: null,
      });

      const result = await runPatternAnalyzerScan("admin", {
        projectId,
        cpeId: dbgCpe,
        patterns: enabledPatterns,
        bucketMinutes: PREVIEW_BUCKET_MINUTES,
        filterPreNtp,
        filterShortReboots,
        onProgress: setScanProgress,
      });

      return { result, dbgCpe };
    },
    onSuccess: (payload) => {
      const expected = cpeIdRef.current ?? null;
      const stamped = payload.result.cpe_serial ?? null;
      const started = payload.dbgCpe ?? null;
      const resultKey = stamped !== null && stamped !== "" ? stamped : started;
      const applyResult = resultKey === expected;
      setScanProgress(null);
      if (!applyResult) {
        setStatusMsg("Results ignored — CPE changed before the scan finished. Run again.");
        return;
      }
      setPreviewResult(payload.result);
      setStatusMsg("");
    },
    onError: (err: unknown) => {
      setScanProgress(null);
      const msg =
        err instanceof Error ? err.message : typeof err === "string" ? err : "Scan failed";
      setStatusMsg(msg);
    },
  });

  const sortedUsers = useMemo(() => {
    if (!users?.length) return users;
    return [...users].sort((a, b) =>
      a.username.localeCompare(b.username, undefined, { sensitivity: "base" }),
    );
  }, [users]);

  return (
    <div className="mb-4 border border-border rounded-xl overflow-hidden bg-muted/15">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-4 py-2 text-left text-sm font-semibold bg-muted/40 hover:bg-muted/55 transition-colors"
      >
        <span className="flex items-center gap-2">
          <ManageSearchIcon style={{ fontSize: 18 }} className="text-primary shrink-0" />
          Preview on uploaded logs
        </span>
        {open ? (
          <ExpandLessIcon style={{ fontSize: 20 }} className="text-muted-foreground shrink-0" />
        ) : (
          <ExpandMoreIcon style={{ fontSize: 20 }} className="text-muted-foreground shrink-0" />
        )}
      </button>

      {open && (
        <div className="p-4 space-y-3 text-xs">
          <p className="text-muted-foreground">
            Run an admin-only ripgrep preview against any user&apos;s project. Pattern rows may include optional{" "}
            <strong className="text-foreground font-medium">scan_filename</strong> and project-local{" "}
            <strong className="text-foreground font-medium">scan_time_range</strong> (UTC ISO bounds imported with that
            project&apos;s patterns). Use workspace Pattern Analyzer for full charts.
          </p>

          <div className="flex flex-wrap gap-3 items-end">
            <div>
              <label className="block text-[10px] text-muted-foreground font-semibold uppercase mb-1">User</label>
              <select
                value={userId === "" ? "" : String(userId)}
                onChange={(e) => setUserId(e.target.value === "" ? "" : Number(e.target.value))}
                className="text-xs px-2 py-1.5 rounded border border-border bg-background min-w-[180px]"
              >
                <option value="">— Select user —</option>
                {sortedUsers?.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-[10px] text-muted-foreground font-semibold uppercase mb-1">Project</label>
              <select
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                disabled={typeof userId !== "number" || projectsLoading}
                className="text-xs px-2 py-1.5 rounded border border-border bg-background min-w-[200px] disabled:opacity-50"
              >
                <option value="">— Project —</option>
                {userProjectsPayload?.projects.map((p) => (
                  <option key={String(p.id)} value={String(p.id)}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-[10px] text-muted-foreground font-semibold uppercase mb-1">
                CPE (optional)
              </label>
              <select
                value={cpeId}
                onChange={(e) => setCpeId(e.target.value)}
                disabled={!projectId || cpesLoading}
                className="text-xs px-2 py-1.5 rounded border border-border bg-background min-w-[200px] disabled:opacity-50"
              >
                <option value="">— All / project root —</option>
                {cpes?.map((c) => (
                  <option key={c.serial} value={c.serial}>
                    {c.serial}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex flex-wrap gap-4 items-center">
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={filterPreNtp}
                onChange={(e) => setFilterPreNtp(e.target.checked)}
                className="h-3.5 w-3.5 rounded accent-primary"
              />
              <span className="text-muted-foreground">Filter pre-NTP logs</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={filterShortReboots}
                onChange={(e) => setFilterShortReboots(e.target.checked)}
                className="h-3.5 w-3.5 rounded accent-primary"
              />
              <span className="text-muted-foreground">Short reboots only</span>
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => scanMutation.mutate()}
              disabled={scanMutation.isPending || enabledPatterns.length === 0 || !projectId}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {scanMutation.isPending ? (
                <CircularProgress size={14} sx={{ color: "white" }} />
              ) : (
                <PlayArrowIcon style={{ fontSize: 16 }} />
              )}
              Run preview ({enabledPatterns.length} pattern{enabledPatterns.length !== 1 ? "s" : ""})
            </button>
            {usersLoading && <span className="text-muted-foreground">Loading users…</span>}
          </div>

          {scanMutation.isPending && (
            <div className="space-y-2">
              <LinearProgress
                variant={
                  scanProgress != null && scanProgress.total > 0 ? "determinate" : "indeterminate"
                }
                value={
                  scanProgress != null && scanProgress.total > 0
                    ? (100 * scanProgress.current) / scanProgress.total
                    : 0
                }
              />
              <p className="text-[11px] text-muted-foreground">
                {scanProgress?.pattern_name
                  ? `Pattern: ${scanProgress.pattern_name}`
                  : statusMsg || "Ripgrep scan in progress…"}
              </p>
            </div>
          )}

          {statusMsg && !scanMutation.isPending && (
            <div className="text-[11px] text-amber-800 dark:text-amber-200">{statusMsg}</div>
          )}

          {previewResult && !scanMutation.isPending && (
            <div className="rounded-lg border border-border bg-background px-3 py-2 space-y-1">
              <p className="text-sm font-semibold text-foreground">
                Total matches:{" "}
                <span className="tabular-nums">{previewResult.total_matches.toLocaleString()}</span>
              </p>
              <p className="text-muted-foreground">
                CPE serial:{" "}
                <span className="font-mono text-foreground">{(previewResult.cpe_serial ?? cpeId) || "—"}</span>
                {" · "}
                Reboots detected: {previewResult.reboots.length}
              </p>
              <ul className="mt-2 max-h-40 overflow-y-auto space-y-0.5 font-mono text-[10px] text-muted-foreground">
                {previewResult.traces.map((t) => (
                  <li key={t.name}>
                    {t.name}: <span className="text-foreground">{t.total.toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
