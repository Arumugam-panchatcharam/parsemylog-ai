import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import {
  analyticsApi,
  cpesApi,
  type PatternLabDoc,
  type PatternLabPreviewData,
  type PatternLabProfileInfo,
  type PatternLabPreviewStats,
  type PatternLabRuleRow,
} from "@/api/endpoints";
import PatternLabEventsPanel from "@/components/analytics/patternLab/PatternLabEventsPanel";
import PatternLabIssuesPanel from "@/components/analytics/patternLab/PatternLabIssuesPanel";
import PatternLabResultsPanel from "@/components/patternAnalyzer/PatternLabResultsPanel";
import { useCPE } from "@/hooks/useCPE";
import { useProject } from "@/hooks/useProject";
import PatternLabIconButton from "@/components/analytics/patternLab/PatternLabIconButton";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { normalizePatternLabDoc } from "@/lib/patternLabTransforms";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import FileCopyOutlinedIcon from "@mui/icons-material/FileCopyOutlined";
import SaveIcon from "@mui/icons-material/Save";
import ScienceIcon from "@mui/icons-material/Science";
import NoteAddOutlinedIcon from "@mui/icons-material/NoteAddOutlined";

type InnerTab = "issues" | "events";

function sanitizeProfileInput(raw: string): string | null {
  const s = raw
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!s || s.length > 64 || !/^[a-z0-9][a-z0-9_-]*$/.test(s)) return null;
  return s;
}

function mergeFleetPreviewResults(
  cpeResults: Array<{ serial: string; data: PatternLabPreviewData }>,
  totalCpes: number,
): PatternLabPreviewData {
  const ruleMap = new Map<string, PatternLabRuleRow>();

  let totalLines = 0;
  let labeled = 0;
  let parquetLines = 0;
  let rawLines = 0;
  const domains = new Set<string>();
  const rawFiles = new Set<string>();

  for (const { serial, data } of cpeResults) {
    const s = data.summary;
    totalLines += Number(s.total_log_lines ?? 0);
    labeled += Number(s.labeled_log_lines ?? 0);
    parquetLines += Number(s.parquet_log_lines ?? 0);
    rawLines += Number(s.raw_log_lines ?? 0);
    for (const d of s.domains_scanned ?? []) domains.add(d);
    for (const f of s.raw_files_scanned ?? []) rawFiles.add(f);

    for (const row of data.rule_rows ?? []) {
      const key = row.rule_key;
      const count = Number(row.total_matches ?? 0);
      const existing = ruleMap.get(key);
      if (!existing) {
        ruleMap.set(key, {
          rule_key: key,
          detect_type: row.detect_type,
          group_by: row.group_by,
          total_matches: 0,
          candidate_labeled_rows: row.candidate_labeled_rows,
          skip_reason: row.skip_reason,
          samples: row.samples,
          per_cpe: [],
        });
      }
      const agg = ruleMap.get(key)!;
      agg.total_matches = Number(agg.total_matches) + count;
      const per = [...(agg.per_cpe ?? [])];
      const idx = per.findIndex((p) => p.serial === serial);
      if (idx >= 0) per[idx] = { serial, count };
      else per.push({ serial, count });
      agg.per_cpe = per;
    }
  }

  const ruleRows = [...ruleMap.values()].sort((a, b) =>
    a.rule_key.localeCompare(b.rule_key),
  );

  return {
    summary: {
      domains_scanned: [...domains],
      total_log_lines: totalLines,
      labeled_log_lines: labeled,
      unlabeled_log_lines: Math.max(0, totalLines - labeled),
      parquet_log_lines: parquetLines,
      raw_log_lines: rawLines,
      raw_files_scanned: [...rawFiles],
      rules_with_matches: ruleRows.filter((r) => Number(r.total_matches) > 0).length,
      cpes_scanned: cpeResults.length,
      cpes_failed: Math.max(0, totalCpes - cpeResults.length),
    },
    event_breakdown: [],
    rule_rows: ruleRows,
  };
}

function patternLabRequestError(err: unknown): string {
  if (isAxiosError(err)) {
    const data = err.response?.data;
    if (data && typeof data === "object" && "error" in data && typeof data.error === "string") {
      return data.error;
    }
  }
  if (err instanceof Error) return err.message;
  return "Request failed";
}

export default function PatternLabTab() {
  const { projectId } = useProject();
  const { cpeId } = useCPE();
  const queryClient = useQueryClient();
  const [doc, setDoc] = useState<PatternLabDoc>({ events: {}, issues: {} });
  const [innerTab, setInnerTab] = useState<InnerTab>("issues");
  const [profiles, setProfiles] = useState<PatternLabProfileInfo[]>([]);
  const [activeProfile, setActiveProfile] = useState<string>("");
  const [profileInput, setProfileInput] = useState<string>("default_profile");
  const [previewResult, setPreviewResult] = useState<PatternLabPreviewData | null>(null);
  const [previewStats, setPreviewStats] = useState<PatternLabPreviewStats | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [previewTotalCpes, setPreviewTotalCpes] = useState(1);
  const seededRef = useRef(false);

  const updateDoc = (next: PatternLabDoc) => {
    seededRef.current = true;
    setDoc(normalizePatternLabDoc(next));
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

  const saveMutation = useMutation({
    mutationFn: async ({ payload, profile }: { payload: PatternLabDoc; profile: string }) =>
      (await analyticsApi.putPatternLab(projectId!, payload, profile)).data,
    onSuccess: (envelope) => {
      if (envelope?.success) {
        setValidationError(null);
        if (envelope.profile) {
          setActiveProfile(envelope.profile);
          setProfileInput(envelope.profile);
        }
        void queryClient.invalidateQueries({ queryKey: ["analytics", "pattern-lab", projectId] });
      } else if (envelope?.error) {
        setValidationError(envelope.error);
      }
    },
    onError: (err) => setValidationError(patternLabRequestError(err)),
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
        setPreviewResult(envelope.data ?? null);
        setPreviewStats((envelope.stats as PatternLabPreviewStats) ?? null);
        setPreviewTotalCpes(1);
        setPreviewError(null);
      } else {
        setPreviewResult(null);
        setPreviewStats(null);
        setPreviewError(envelope?.error ?? "Preview failed");
      }
    },
    onError: (e: Error) => {
      setPreviewResult(null);
      setPreviewStats(null);
      setPreviewError(e.message);
    },
  });

  const fleetScanMutation = useMutation({
    mutationFn: async (payload: PatternLabDoc) => {
      if (!projectId) throw new Error("No project selected");
      const err = lightValidate(payload);
      if (err) throw new Error(err);
      const normalized = normalizePatternLabDoc(payload);
      const list = await cpesApi.list(projectId);
      const serials = ((list.data as Array<{ serial: string }> | undefined) ?? [])
        .map((c) => c.serial)
        .filter(Boolean);
      if (serials.length === 0) throw new Error("No CPEs in this project");

      const ok: Array<{ serial: string; data: PatternLabPreviewData }> = [];
      for (const serial of serials) {
        try {
          const res = await analyticsApi.previewPatternLab(
            projectId,
            { cpe_serial: serial },
            normalized,
          );
          const envelope = res.data;
          if (envelope?.success && envelope.data && !envelope.data.summary?.skipped) {
            ok.push({ serial, data: envelope.data });
          }
        } catch {
          /* skip CPEs without RG data or on error */
        }
      }
      if (ok.length === 0) {
        throw new Error("No CPEs returned pattern lab results (missing *_rg.parquet or no matches)");
      }
      return mergeFleetPreviewResults(ok, serials.length);
    },
    onSuccess: (data) => {
      setPreviewResult(data);
      setPreviewStats(data.summary as PatternLabPreviewStats);
      setPreviewTotalCpes(Number(data.summary.cpes_scanned ?? 1));
      setPreviewError(null);
    },
    onError: (e: Error) => {
      setPreviewResult(null);
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

  const handleNewProfile = () => {
    seededRef.current = true;
    setDoc({ events: {}, issues: {} });
    setActiveProfile("");
    setProfileInput("");
    setValidationError(null);
    setPreviewResult(null);
    setPreviewStats(null);
    setPreviewError(null);
  };

  const handleSave = () => {
    const profile = sanitizeProfileInput(profileInput);
    if (!profile) {
      setValidationError(
        "Profile name is required (letters, numbers, underscore, hyphen; start with a letter or number).",
      );
      return;
    }
    if (profile !== profileInput) setProfileInput(profile);
    const err = lightValidate(doc);
    if (err) {
      setValidationError(err);
      return;
    }
    setValidationError(null);
    saveMutation.mutate({ payload: normalizePatternLabDoc(doc), profile });
  };

  const handlePreviewSelectedCpe = () => {
    if (!cpeId) {
      setValidationError("Select a CPE in the sidebar to preview.");
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

  const handleFleetScan = () => {
    const err = lightValidate(doc);
    if (err) {
      setValidationError(err);
      return;
    }
    setValidationError(null);
    fleetScanMutation.mutate(normalizePatternLabDoc(doc));
  };

  const handleDeleteProfile = () => {
    if (!activeProfile) return;
    const ok = window.confirm(
      `Delete profile "${activeProfile}"? This cannot be undone.`,
    );
    if (ok) deleteProfileMutation.mutate(activeProfile);
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

  const sourceLabel = labQuery.data?.source === "profile" ? "User profile" : "Generic starter example";

  const saveError =
    saveMutation.data && !saveMutation.data.success
      ? saveMutation.data.error
      : saveMutation.isError
        ? patternLabRequestError(saveMutation.error)
        : null;

  return (
    <div className="bg-card rounded-lg border border-border shadow-sm">
      <header
        className="border-b border-border px-3 py-1.5 flex flex-wrap items-center gap-x-2 gap-y-1.5 min-h-[2.25rem]"
        aria-labelledby="pattern-lab-heading"
      >
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 flex-1 min-w-0">
        <div className="flex items-center gap-1.5 shrink-0">
          <ScienceIcon className="h-4 w-4 text-primary" aria-hidden />
          <h3 id="pattern-lab-heading" className="text-sm font-medium">
            Pattern lab
          </h3>
          <span
            className="text-[10px] text-muted-foreground hidden sm:inline"
            title={`Loaded from: ${sourceLabel}${labQuery.isFetching ? " (refreshing)" : ""}`}
          >
            · {sourceLabel}
            {labQuery.isFetching ? " …" : null}
          </span>
        </div>

        <div className="hidden sm:block h-4 w-px bg-border shrink-0" aria-hidden />

        <input
          type="text"
          value={profileInput}
          onChange={(e) => setProfileInput(e.target.value)}
          placeholder="Profile name"
          title="Profile name to save (letters, numbers, underscore, hyphen)"
          aria-label="Profile name"
          className="h-8 w-[9.5rem] min-w-0 px-2 border border-input rounded-md text-xs font-mono bg-background"
        />
        <select
          value={activeProfile}
          title="Saved profiles for this user"
          aria-label="Saved profiles"
          onChange={(e) => {
            const p = e.target.value;
            setActiveProfile(p);
            if (p) setActiveMutation.mutate(p);
          }}
          className="h-8 w-[9.5rem] min-w-0 px-2 border border-input rounded-md text-xs font-mono bg-background"
        >
          <option value="">(starter)</option>
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.id}
            </option>
          ))}
        </select>

        <div className="flex items-center gap-0.5 shrink-0">
          <PatternLabIconButton
            label="New profile — blank events and rules"
            disabled={!projectId}
            onClick={handleNewProfile}
          >
            <NoteAddOutlinedIcon style={{ fontSize: 18 }} />
          </PatternLabIconButton>
          <PatternLabIconButton
            label="Duplicate as… — save a copy under a new profile name"
            disabled={duplicateProfileMutation.isPending || !projectId}
            onClick={handleDuplicateAs}
          >
            <FileCopyOutlinedIcon style={{ fontSize: 18 }} />
          </PatternLabIconButton>
          <PatternLabIconButton
            label="Save profile — writes pattern_lab_profiles/<name>.yaml and sets active for this project"
            variant="primary"
            disabled={saveMutation.isPending || !projectId}
            onClick={handleSave}
          >
            <SaveIcon style={{ fontSize: 18 }} />
          </PatternLabIconButton>
          <PatternLabIconButton
            label="Delete active profile"
            variant="destructive"
            disabled={!activeProfile || deleteProfileMutation.isPending}
            onClick={handleDeleteProfile}
          >
            <DeleteOutlineIcon style={{ fontSize: 18 }} />
          </PatternLabIconButton>
        </div>
        </div>

        <div className="flex items-center gap-2 shrink-0 ml-auto">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 text-xs"
            disabled={
              previewMutation.isPending ||
              fleetScanMutation.isPending ||
              !projectId ||
              !cpeId
            }
            title={
              cpeId
                ? `Preview current profile on selected CPE (${cpeId})`
                : "Select a CPE in the sidebar to preview"
            }
            onClick={handlePreviewSelectedCpe}
          >
            {previewMutation.isPending ? "Previewing…" : "Preview"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 text-xs"
            disabled={
              previewMutation.isPending ||
              fleetScanMutation.isPending ||
              !projectId
            }
            onClick={handleFleetScan}
          >
            {fleetScanMutation.isPending ? "Scanning…" : "Scan/re-scan all CPE's"}
          </Button>
        </div>
      </header>

      <div className="px-3 py-3 space-y-3">
        {(validationError || saveError) && (
          <div className="rounded border border-destructive/30 bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
            {validationError ?? saveError}
          </div>
        )}

        {saveMutation.data?.success === true && (
          <p className="text-[11px] text-emerald-700 dark:text-emerald-400" role="status">
            Saved.
          </p>
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

        {(previewMutation.isPending || fleetScanMutation.isPending) && (
          <p className="text-sm text-muted-foreground" role="status">
            {fleetScanMutation.isPending ? "Scanning all CPEs…" : "Previewing selected CPE…"}
          </p>
        )}

        {(previewError || previewStats || previewResult) && (
          <PatternLabResultsPanel
            result={previewResult}
            stats={previewStats}
            error={previewError}
            cpeSerial={previewTotalCpes === 1 ? cpeId ?? undefined : undefined}
            totalCpes={previewTotalCpes}
          />
        )}
      </div>
    </div>
  );
}
