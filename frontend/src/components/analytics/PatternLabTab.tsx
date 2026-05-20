import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  analyticsApi,
  type AnalyticsStaIssue,
  type PatternLabDoc,
  type PatternLabProfileInfo,
  type PatternLabPreviewStats,
} from "@/api/endpoints";
import PatternLabEventsPanel from "@/components/analytics/patternLab/PatternLabEventsPanel";
import PatternLabIssuesPanel from "@/components/analytics/patternLab/PatternLabIssuesPanel";
import { useCPE } from "@/hooks/useCPE";
import { useProject } from "@/hooks/useProject";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { normalizePatternLabDoc } from "@/lib/patternLabTransforms";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import FileCopyOutlinedIcon from "@mui/icons-material/FileCopyOutlined";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import RefreshIcon from "@mui/icons-material/Refresh";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import SaveIcon from "@mui/icons-material/Save";
import ScienceIcon from "@mui/icons-material/Science";

type InnerTab = "issues" | "events";

export default function PatternLabTab({ etlBanner }: { etlBanner: ReactNode }) {
  const { projectId } = useProject();
  const { cpeId } = useCPE();
  const queryClient = useQueryClient();
  const [doc, setDoc] = useState<PatternLabDoc>({ events: {}, issues: {} });
  const [innerTab, setInnerTab] = useState<InnerTab>("issues");
  const [rawJsonOpen, setRawJsonOpen] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const [profiles, setProfiles] = useState<PatternLabProfileInfo[]>([]);
  const [activeProfile, setActiveProfile] = useState<string>("");
  const [profileInput, setProfileInput] = useState<string>("default_profile");
  const [previewRows, setPreviewRows] = useState<AnalyticsStaIssue[] | null>(null);
  const [previewStats, setPreviewStats] = useState<PatternLabPreviewStats | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const seededRef = useRef(false);

  const updateDoc = (next: PatternLabDoc) => {
    seededRef.current = true;
    setDoc(next);
  };

  const labQuery = useQuery({
    queryKey: ["analytics", "pattern-lab", projectId],
    queryFn: async () => (await analyticsApi.getPatternLab(projectId!)).data,
    enabled: !!projectId,
  });

  useEffect(() => {
    seededRef.current = false;
  }, [projectId]);

  useEffect(() => {
    const envelope = labQuery.data;
    if (!envelope?.success || !envelope.data || seededRef.current) return;
    setDoc(normalizePatternLabDoc(envelope.data));
    setProfiles(envelope.profiles ?? []);
    setActiveProfile(envelope.active_profile ?? "");
    if (envelope.active_profile) setProfileInput(envelope.active_profile);
    setValidationError(null);
    seededRef.current = true;
  }, [labQuery.data]);

  const rawJsonText = JSON.stringify(doc, null, 2);

  const saveMutation = useMutation({
    mutationFn: async (payload: PatternLabDoc) =>
      (await analyticsApi.putPatternLab(projectId!, payload, profileInput)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["analytics", "pattern-lab", projectId] });
    },
  });

  const setActiveMutation = useMutation({
    mutationFn: async (profile: string) => (await analyticsApi.setPatternLabActive(projectId!, profile)).data,
    onSuccess: (envelope) => {
      if (envelope?.success) {
        if (envelope.data) setDoc(normalizePatternLabDoc(envelope.data));
        setProfiles(envelope.profiles ?? []);
        setActiveProfile(envelope.active_profile ?? "");
        if (envelope.active_profile) setProfileInput(envelope.active_profile);
      }
    },
  });

  const deleteProfileMutation = useMutation({
    mutationFn: async (profile: string) =>
      (await analyticsApi.deletePatternLabProfile(projectId!, profile)).data,
    onSuccess: (envelope) => {
      if (envelope?.success) {
        if (envelope.data) setDoc(normalizePatternLabDoc(envelope.data));
        setProfiles(envelope.profiles ?? []);
        setActiveProfile(envelope.active_profile ?? "");
        if (!envelope.active_profile) setProfileInput("default_profile");
      }
    },
  });

  const duplicateProfileMutation = useMutation({
    mutationFn: async (payload: {
      target_profile: string;
      source_profile?: string;
      events: Record<string, unknown>;
      issues: Record<string, unknown>;
    }) => (await analyticsApi.duplicatePatternLabProfile(projectId!, payload)).data,
    onSuccess: (envelope) => {
      if (envelope?.success) {
        setProfiles(envelope.profiles ?? []);
        setProfileInput(envelope.profile ?? profileInput);
        setValidationError(null);
      } else if (envelope?.error) {
        setValidationError(envelope.error);
      }
    },
    onError: (e: Error) => setValidationError(e.message),
  });

  const resetDefaultsMutation = useMutation({
    mutationFn: async () => (await analyticsApi.getPatternLabDefaults(projectId!)).data,
    onSuccess: (envelope) => {
      if (envelope?.success && envelope.data) {
        setDoc(normalizePatternLabDoc(envelope.data));
        setValidationError(null);
        seededRef.current = true;
      }
    },
  });

  const previewMutation = useMutation({
    mutationFn: async (payload: { doc: PatternLabDoc; useSaved: boolean }) => {
      if (!cpeId) throw new Error("Select a CPE in the sidebar");
      return (
        await analyticsApi.previewPatternLab(
          projectId!,
          { cpe_serial: cpeId, use_saved: payload.useSaved },
          payload.useSaved ? undefined : payload.doc,
        )
      ).data;
    },
    onSuccess: (envelope) => {
      if (envelope?.success) {
        setPreviewRows(envelope.data ?? []);
        setPreviewStats((envelope.stats as PatternLabPreviewStats) ?? null);
        setPreviewError(null);
      } else {
        setPreviewRows(null);
        setPreviewStats(null);
        setPreviewError(envelope?.error ?? "Preview failed");
      }
    },
    onError: (e: Error) => {
      setPreviewRows(null);
      setPreviewStats(null);
      setPreviewError(e.message);
    },
  });

  const lightValidate = (d: PatternLabDoc): string | null => {
    for (const ik of Object.keys(d.issues)) {
      const m = d.issues[ik];
      if (!ik.trim()) return "Each rule needs a non-empty id.";
      if (m && typeof m === "object" && !Array.isArray(m)) {
        const detect = (m as Record<string, unknown>).detect as Record<string, unknown> | undefined;
        if (!detect) continue;
        const dt = detect.type;
        if (dt === "ordered_sequence") {
          const seq = detect.sequence as unknown;
          const arr = Array.isArray(seq) ? seq.filter((x) => typeof x === "string" && x.trim()) : [];
          if (arr.length < 2) return `Rule "${ik}": sequence needs at least two event codes.`;
        }
        if (dt === "missing_followup") {
          const tr = typeof detect.trigger === "string" ? detect.trigger.trim() : "";
          const ex = typeof detect.expect === "string" ? detect.expect.trim() : "";
          if (!tr || !ex)
            return `Rule "${ik}": choose both "after" and "expect" events for missing follow-up.`;
        }
        if (dt === "burst_count") {
          const ev = typeof detect.event === "string" ? detect.event.trim() : "";
          if (!ev) return `Rule "${ik}": choose an event for burst count.`;
        }
      }
    }
    return null;
  };

  const handleSave = () => {
    if (!profileInput.trim()) {
      setValidationError("Profile name is required to save.");
      return;
    }
    const err = lightValidate(doc);
    if (err) {
      setValidationError(err);
      return;
    }
    setValidationError(null);
    saveMutation.mutate(normalizePatternLabDoc(doc));
  };

  const handlePreview = (useSaved: boolean) => {
    if (useSaved) {
      setValidationError(null);
      previewMutation.mutate({ doc: { events: {}, issues: {} }, useSaved: true });
      return;
    }
    const err = lightValidate(doc);
    if (err) {
      setValidationError(err);
      return;
    }
    setValidationError(null);
    previewMutation.mutate({ doc: normalizePatternLabDoc(doc), useSaved: false });
  };

  const handleDuplicateAs = () => {
    const suggested =
      activeProfile && activeProfile.length > 0
        ? `${activeProfile}_copy`
        : profileInput.trim()
          ? `${profileInput.trim()}_copy`
          : "my_profile_copy";
    const raw = window.prompt("New profile name (letters, numbers, underscore, hyphen):", suggested);
    if (!raw) return;
    const target = raw.trim().toLowerCase().replace(/\s+/g, "_");
    if (!target) {
      setValidationError("Profile name is required to duplicate.");
      return;
    }
    const err = lightValidate(doc);
    if (err) {
      setValidationError(err);
      return;
    }
    setValidationError(null);
    const normalized = normalizePatternLabDoc(doc);
    duplicateProfileMutation.mutate({
      target_profile: target,
      source_profile: activeProfile || undefined,
      events: normalized.events,
      issues: normalized.issues,
    });
  };

  const handleCopyRaw = async () => {
    try {
      await navigator.clipboard.writeText(rawJsonText);
      setCopiedJson(true);
      window.setTimeout(() => setCopiedJson(false), 2000);
    } catch {
      setCopiedJson(false);
    }
  };

  const sourceLabel = labQuery.data?.source === "profile" ? "User profile" : "Generic starter example";

  const saveError =
    saveMutation.data && !saveMutation.data.success ? saveMutation.data.error : saveMutation.error?.message;

  return (
    <div className="bg-card rounded-lg border border-border shadow-sm">
      {etlBanner}
      <div className="p-6 space-y-4">
        <section className="space-y-2" aria-labelledby="pattern-lab-heading">
          <h3 id="pattern-lab-heading" className="text-base font-medium flex items-center gap-2">
            <ScienceIcon className="h-5 w-5 text-primary" />
            Pattern lab
          </h3>
          <p className="text-xs text-muted-foreground max-w-3xl">
            Define <strong>events</strong> (how log lines map to codes) and <strong>rules</strong> (issues to detect).
            Save writes a named YAML profile in your user library. Preview runs detectors on the selected CPE without
            updating fleet Parquet.
          </p>
          <p className="text-xs text-muted-foreground">
            Loaded from: <span className="font-medium text-foreground">{sourceLabel}</span>
            {labQuery.isFetching ? " · refreshing…" : null}
          </p>
        </section>

        <div className="rounded-lg border border-border p-3 bg-muted/20 space-y-2">
          <div className="flex flex-wrap gap-2 items-end">
            <label className="flex flex-col gap-0.5 min-w-[14rem]">
              <span className="text-xs text-muted-foreground">Profile name</span>
              <input
                type="text"
                value={profileInput}
                onChange={(e) => setProfileInput(e.target.value)}
                placeholder="e.g. default_profile"
                className="px-2 py-1.5 border border-input rounded-md text-sm font-mono bg-background"
              />
            </label>
            <label className="flex flex-col gap-0.5 min-w-[14rem]">
              <span className="text-xs text-muted-foreground">Saved profiles</span>
              <select
                value={activeProfile}
                onChange={(e) => {
                  const p = e.target.value;
                  setActiveProfile(p);
                  if (p) setActiveMutation.mutate(p);
                }}
                className="px-2 py-1.5 border border-input rounded-md text-sm font-mono bg-background"
              >
                <option value="">(starter example)</option>
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.id}
                  </option>
                ))}
              </select>
            </label>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={duplicateProfileMutation.isPending || !projectId}
              onClick={handleDuplicateAs}
              title="Copy the current editor to a new profile name"
            >
              <FileCopyOutlinedIcon className="w-4 h-4 mr-1" />
              {duplicateProfileMutation.isPending ? "Duplicating…" : "Duplicate as…"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!activeProfile || deleteProfileMutation.isPending}
              className="text-destructive"
              onClick={() => activeProfile && deleteProfileMutation.mutate(activeProfile)}
            >
              Delete profile
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Save writes/updates <span className="font-mono">pattern_lab_profiles/&lt;profile&gt;.yaml</span> for this
            user and marks it active for this project. <strong>Duplicate as…</strong> saves a copy under a new name
            without overwriting an existing profile.
          </p>
        </div>

        <div className="flex flex-wrap gap-2 items-center">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={labQuery.isFetching || !projectId}
            onClick={() => {
              seededRef.current = false;
              void labQuery.refetch();
            }}
          >
            <RefreshIcon className="w-4 h-4 mr-1" />
            Reload from server
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={resetDefaultsMutation.isPending || !projectId}
            onClick={() => resetDefaultsMutation.mutate()}
          >
            <RestartAltIcon className="w-4 h-4 mr-1" />
            Load starter example
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            disabled={saveMutation.isPending || !projectId}
            onClick={handleSave}
          >
            <SaveIcon className="w-4 h-4 mr-1" />
            {saveMutation.isPending ? "Saving…" : "Save profile"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={previewMutation.isPending || !projectId || !cpeId}
            onClick={() => handlePreview(false)}
            title={!cpeId ? "Select a CPE in the sidebar" : undefined}
          >
            <PlayArrowIcon className="w-4 h-4 mr-1" />
            {previewMutation.isPending ? "Preview…" : "Preview draft"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={previewMutation.isPending || !projectId || !cpeId}
            onClick={() => handlePreview(true)}
            title={!cpeId ? "Select a CPE in the sidebar" : undefined}
          >
            Preview saved file
          </Button>
        </div>

        {!cpeId ? (
          <p className="text-sm text-amber-800 dark:text-amber-200 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2">
            Select a CPE in the sidebar to run preview.
          </p>
        ) : (
          <p className="text-xs text-muted-foreground font-mono">Preview CPE folder: {cpeId}</p>
        )}

        {(validationError || saveError) && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {validationError ?? saveError}
          </div>
        )}

        {saveMutation.data?.success === true && (
          <p className="text-xs text-emerald-700 dark:text-emerald-400">Saved successfully.</p>
        )}

        <div
          className="flex flex-wrap gap-1 border-b border-border pb-px"
          role="tablist"
          aria-label="Pattern lab sections"
        >
          {(
            [
              ["issues", "Issues (rules)"],
              ["events", "Events (log labels)"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={innerTab === id}
              onClick={() => setInnerTab(id)}
              className={cn(
                "px-4 py-2 text-sm font-medium rounded-t-md border border-b-0 -mb-px transition-colors",
                innerTab === id
                  ? "bg-card border-border text-primary z-[1]"
                  : "bg-muted/40 border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="pt-2 min-h-[12rem]" role="tabpanel">
          {innerTab === "issues" ? (
            <PatternLabIssuesPanel doc={doc} setDoc={updateDoc} />
          ) : (
            <PatternLabEventsPanel doc={doc} setDoc={updateDoc} />
          )}
        </div>

        <div className="rounded-lg border border-border">
          <button
            type="button"
            className="flex w-full items-center justify-between px-3 py-2 text-left text-xs font-medium text-muted-foreground hover:bg-muted/30"
            onClick={() => setRawJsonOpen((o) => !o)}
          >
            <span>
              Raw JSON <span className="font-normal opacity-80">(read-only · for support / debugging)</span>
            </span>
            <span className="text-foreground">{rawJsonOpen ? "−" : "+"}</span>
          </button>
          {rawJsonOpen ? (
            <div className="border-t border-border p-3 space-y-2">
              <div className="flex justify-end">
                <Button type="button" variant="outline" size="sm" onClick={() => void handleCopyRaw()}>
                  <ContentCopyIcon className="w-4 h-4 mr-1" />
                  {copiedJson ? "Copied" : "Copy"}
                </Button>
              </div>
              <pre className="text-[11px] font-mono bg-muted/50 border border-input rounded-md p-3 overflow-x-auto max-h-72 overflow-y-auto">
                {rawJsonText}
              </pre>
            </div>
          ) : null}
        </div>

        {(previewError || previewStats) && (
          <div className="space-y-2">
            {previewError ? (
              <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {previewError}
              </div>
            ) : null}
            {previewStats ? (
              <pre className="text-xs bg-muted/50 border border-border rounded-md p-3 overflow-x-auto max-h-40">
                {JSON.stringify(previewStats, null, 2)}
              </pre>
            ) : null}
          </div>
        )}

        {previewRows && previewRows.length > 0 ? (
          <div className="rounded-lg border border-border overflow-hidden">
            <div className="px-3 py-2 bg-muted/50 border-b border-border text-xs font-medium">
              Preview matches ({previewRows.length})
            </div>
            <ul className="divide-y divide-border max-h-80 overflow-y-auto">
              {previewRows.map((row, idx) => (
                <li key={`${row.issue_key}-${row.sta_mac}-${idx}`} className="px-3 py-2 text-xs space-y-1">
                  <div className="flex flex-wrap gap-2 font-mono text-foreground">
                    <span className="font-sans text-muted-foreground">issue</span>
                    <span>{row.issue_key}</span>
                    <span className="font-sans text-muted-foreground">sta</span>
                    <span>{row.sta_mac || "—"}</span>
                    <span className="font-sans text-muted-foreground">sev</span>
                    <span>{row.severity}</span>
                  </div>
                  {row.evidence ? (
                    <pre className="text-[11px] text-muted-foreground whitespace-pre-wrap break-all max-h-24 overflow-y-auto">
                      {row.evidence}
                    </pre>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : previewRows && previewRows.length === 0 && !previewError ? (
          <p className="text-sm text-muted-foreground">No issue rows matched for this preview.</p>
        ) : null}
      </div>
    </div>
  );
}
