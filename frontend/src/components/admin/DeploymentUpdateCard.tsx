import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import CircularProgress from "@mui/material/CircularProgress";
import SystemUpdateAltIcon from "@mui/icons-material/SystemUpdateAlt";
import RefreshIcon from "@mui/icons-material/Refresh";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { adminApi } from "@/api/endpoints";
import type { DeploymentUpdateStatus } from "@/api/endpoints";

const RUNNING_STATES = new Set(["previewing", "applying", "rolling_back"]);

function stepLabel(step: string | null | undefined): string {
  const labels: Record<string, string> = {
    fetch: "Fetching from remote",
    check_tree: "Checking working tree",
    pull: "Pulling latest changes",
    build_frontend: "Building frontend",
    restart: "Restarting services",
    health_check: "Verifying health",
    rollback: "Rolling back",
    rebuild_frontend: "Rebuilding frontend (rollback)",
    done: "Complete",
  };
  return labels[step ?? ""] ?? step ?? "—";
}

export function DeploymentUpdateCard() {
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  const { data: status, isLoading, refetch } = useQuery({
    queryKey: ["adminDeploymentStatus"],
    queryFn: async () => (await adminApi.getDeploymentStatus()).data,
    refetchInterval: (query) => {
      const st = query.state.data?.state;
      return st && RUNNING_STATES.has(st) ? 2000 : false;
    },
  });

  const previewMutation = useMutation({
    mutationFn: () => adminApi.previewDeployment(),
    onSuccess: () => {
      setPreviewOpen(true);
      queryClient.invalidateQueries({ queryKey: ["adminDeploymentStatus"] });
    },
  });

  const applyMutation = useMutation({
    mutationFn: () => adminApi.applyDeployment(),
    onSuccess: () => {
      setConfirmOpen(false);
      queryClient.invalidateQueries({ queryKey: ["adminDeploymentStatus"] });
    },
  });

  useEffect(() => {
    if (status?.phase === "preview" && status.state === "completed") {
      setPreviewOpen(true);
    }
  }, [status?.phase, status?.state]);

  const isRunning = status?.state ? RUNNING_STATES.has(status.state) : false;
  const canUpgrade =
    status?.enabled &&
    status?.preview_ready &&
    status?.phase === "preview" &&
    status?.state === "completed" &&
    !isRunning;

  const noUpdates =
    status?.phase === "preview" &&
    status?.state === "completed" &&
    (status?.behind_count ?? 0) === 0;

  return (
    <div className="bg-card border border-border rounded-2xl p-6 h-full min-h-0 flex flex-col overflow-auto">
      <div className="flex items-start gap-4 flex-1 min-h-0">
        <div className="shrink-0 h-12 w-12 rounded-xl bg-primary/10 flex items-center justify-center">
          <SystemUpdateAltIcon style={{ fontSize: 28 }} className="text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-base font-semibold">Application Update</h3>
            {status?.version && (
              <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                v{status.version}
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-0.5">
            Pull the latest code, rebuild the frontend, and restart services. Failed upgrades roll back
            automatically.
          </p>

          {status?.version && (
            <p className="mt-2 text-sm text-muted-foreground">
              Installed version: <span className="font-medium text-foreground">v{status.version}</span>
              {status.current_sha && (
                <>
                  {" "}
                  · Git{" "}
                  <code className="text-xs bg-muted px-1 rounded font-mono" title={status.current_sha}>
                    {status.current_sha.slice(0, 12)}
                  </code>
                </>
              )}
            </p>
          )}

          {!status?.enabled && (
            <div className="mt-4 p-3 bg-muted/40 border border-border rounded-lg text-sm text-muted-foreground">
              In-app updates are disabled. Set <code className="text-xs bg-muted px-1 rounded">DEPLOY_UPDATE_ENABLED=1</code>{" "}
              in <code className="text-xs bg-muted px-1 rounded">.env</code> and restart the API container.
            </div>
          )}

          {status?.enabled && (
            <>
              {status.last_update_at && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Last update by {status.last_update_by ?? "—"} ({status.last_update_status ?? "—"}) ·{" "}
                  {status.last_update_at}
                </p>
              )}

              {isRunning && (
                <div className="mt-4 flex items-center gap-2 text-sm">
                  <CircularProgress size={16} />
                  <span>
                    {status.state === "previewing" ? "Checking for updates" : "Upgrading"} —{" "}
                    {stepLabel(status.step)}
                  </span>
                </div>
              )}

              {status.error && !isRunning && (
                <div className="mt-4 p-3 bg-destructive/10 border border-destructive/30 rounded-lg text-sm text-destructive">
                  {status.error}
                </div>
              )}

              {status.state === "completed" && status.phase === "apply" && (
                <div className="mt-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg text-sm text-green-800 dark:text-green-200">
                  Upgrade completed successfully.
                </div>
              )}

              {status.state === "rolled_back" && (
                <div className="mt-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg text-sm text-yellow-800 dark:text-yellow-200">
                  Upgrade failed and was rolled back to the previous version.
                </div>
              )}

              <div className="flex flex-wrap gap-2 mt-4">
                <button
                  type="button"
                  onClick={() => previewMutation.mutate()}
                  disabled={!status.enabled || isRunning || previewMutation.isPending}
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  {previewMutation.isPending ? (
                    <CircularProgress size={14} color="inherit" />
                  ) : (
                    "Check for updates"
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmOpen(true)}
                  disabled={!canUpgrade || applyMutation.isPending}
                  className="px-4 py-2 rounded-lg text-sm font-medium border border-border hover:bg-muted disabled:opacity-50"
                >
                  Upgrade
                </button>
                <button
                  type="button"
                  onClick={() => refetch()}
                  title="Refresh status"
                  className="p-2 border border-border rounded-lg hover:bg-muted"
                >
                  <RefreshIcon style={{ fontSize: 18 }} />
                </button>
              </div>

              {noUpdates && (
                <p className="mt-3 text-sm text-muted-foreground">Already up to date with remote.</p>
              )}
            </>
          )}

          {isLoading && !status && (
            <div className="mt-4">
              <CircularProgress size={20} />
            </div>
          )}
        </div>
      </div>

      {previewOpen && status?.phase === "preview" && status.state === "completed" && (
        <PreviewModal
          status={status}
          onClose={() => setPreviewOpen(false)}
          onUpgrade={() => {
            setPreviewOpen(false);
            setConfirmOpen(true);
          }}
        />
      )}

      {confirmOpen && (
        <ConfirmUpgradeModal
          status={status}
          pending={applyMutation.isPending}
          error={
            applyMutation.isError
              ? (applyMutation.error as { response?: { data?: { error?: string } } })?.response?.data
                  ?.error ?? "Upgrade failed to start"
              : null
          }
          onCancel={() => setConfirmOpen(false)}
          onConfirm={() => applyMutation.mutate()}
        />
      )}

      {status?.log_tail && (isRunning || status.error) && (
        <pre className="mt-4 p-3 text-xs bg-muted/30 rounded-lg overflow-x-auto max-h-40 text-muted-foreground">
          {status.log_tail}
        </pre>
      )}
    </div>
  );
}

function PreviewModal({
  status,
  onClose,
  onUpgrade,
}: {
  status: DeploymentUpdateStatus;
  onClose: () => void;
  onUpgrade: () => void;
}) {
  const behind = status.behind_count ?? 0;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-card border border-border rounded-2xl max-w-lg w-full max-h-[80vh] flex flex-col shadow-xl">
        <div className="p-4 border-b border-border flex justify-between items-center gap-2">
          <div>
            <h4 className="font-semibold">Available updates ({behind} commit{behind === 1 ? "" : "s"})</h4>
            {status.version && (
              <p className="text-xs text-muted-foreground mt-0.5">Current version: v{status.version}</p>
            )}
          </div>
          <button type="button" onClick={onClose} className="p-1 hover:bg-muted rounded">
            ×
          </button>
        </div>
        <div className="p-4 overflow-y-auto flex-1">
          <ul className="space-y-2 text-sm">
            {(status.commits ?? []).map((c) => (
              <li key={c.full_sha} className="border-b border-border/50 pb-2">
                <span className="font-mono text-xs text-primary">{c.sha}</span>{" "}
                <span className="font-medium">{c.subject}</span>
                <div className="text-xs text-muted-foreground mt-0.5">
                  {c.author} · {c.date_relative}
                </div>
              </li>
            ))}
          </ul>
          {status.diff_stat && (
            <pre className="mt-4 text-xs bg-muted/30 p-3 rounded-lg overflow-x-auto whitespace-pre-wrap">
              {status.diff_stat}
            </pre>
          )}
        </div>
        <div className="p-4 border-t border-border flex gap-2 justify-end">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-sm border border-border hover:bg-muted">
            Close
          </button>
          {behind > 0 && (
            <button
              type="button"
              onClick={onUpgrade}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-primary text-primary-foreground"
            >
              Proceed to upgrade
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ConfirmUpgradeModal({
  status,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  status: DeploymentUpdateStatus | undefined;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-card border border-border rounded-2xl max-w-md w-full p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <WarningAmberIcon className="text-yellow-600 shrink-0" />
          <div>
            <h4 className="font-semibold">Confirm upgrade</h4>
            <p className="text-sm text-muted-foreground mt-2">
              This will upgrade from <strong>v{status?.version ?? "?"}</strong> by pulling{" "}
              {status?.behind_count ?? 0} commit(s), rebuild the frontend, and restart nginx, celery-worker,
              and logai-api. The app may be briefly unavailable.
            </p>
            <p className="text-sm text-muted-foreground mt-2">
              On failure, the server will roll back to commit{" "}
              <code className="text-xs bg-muted px-1 rounded">{status?.current_sha?.slice(0, 12)}</code>.
            </p>
          </div>
        </div>
        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
        <div className="flex gap-2 justify-end mt-6">
          <button type="button" onClick={onCancel} disabled={pending} className="px-4 py-2 rounded-lg text-sm border border-border hover:bg-muted">
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-primary text-primary-foreground disabled:opacity-50"
          >
            {pending ? <CircularProgress size={14} color="inherit" /> : "Upgrade now"}
          </button>
        </div>
      </div>
    </div>
  );
}
