import api from "@/api/client";
import type {
  PatternAnalyzerScanResult,
  RegexScanProgressPayload,
  UserPattern,
} from "@/api/endpoints";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function axiosErrorMessage(err: unknown): string {
  if (typeof err === "object" && err !== null && "response" in err) {
    const data = (err as { response?: { data?: { error?: string } } }).response?.data;
    if (data?.error) return data.error;
  }
  if (err instanceof Error) return err.message;
  return "Scan failed";
}

export async function runPatternAnalyzerScan(
  mode: "user" | "admin",
  params: {
    projectId: string;
    cpeId?: string | null;
    patterns: UserPattern[];
    bucketMinutes: number;
    filterPreNtp: boolean;
    filterShortReboots: boolean;
    onProgress?: (p: RegexScanProgressPayload) => void;
    signal?: AbortSignal;
  },
): Promise<PatternAnalyzerScanResult> {
  const base =
    mode === "user"
      ? `/projects/${params.projectId}`
      : `/admin/projects/${params.projectId}`;
  const q = params.cpeId ? { cpe_id: params.cpeId } : undefined;

  const body = {
    patterns: params.patterns,
    bucket_minutes: params.bucketMinutes,
    filter_pre_ntp: params.filterPreNtp,
    filter_short_reboots: params.filterShortReboots,
    cpe_id: params.cpeId || undefined,
  };

  let postRes;
  try {
    postRes = await api.post<{ scan_id: string }>(`${base}/regex-scan`, body, { params: q });
  } catch (e: unknown) {
    throw new Error(axiosErrorMessage(e));
  }

  if (postRes.status !== 202) {
    const msg = (postRes.data as { error?: string } | undefined)?.error;
    throw new Error(msg || `Unexpected response status ${postRes.status}`);
  }

  const scan_id = postRes.data.scan_id;
  const pollInterval = 380;
  const maxPolls = 900;

  await sleep(80);

  let sawComplete = false;
  for (let i = 0; i < maxPolls; i++) {
    if (params.signal?.aborted) {
      throw new DOMException("Scan cancelled", "AbortError");
    }

    const progRes = await api.get<RegexScanProgressPayload>(
      `${base}/regex-scan/${scan_id}/progress`,
      {
        params: q,
        validateStatus: () => true,
      },
    );

    if (progRes.status === 404) {
      await sleep(pollInterval);
      continue;
    }

    if (progRes.status !== 200) {
      throw new Error(
        (progRes.data as { error?: string })?.error ||
          `Progress request failed (${progRes.status})`,
      );
    }

    const p = progRes.data;
    params.onProgress?.(p);

    if (p.status === "complete") {
      sawComplete = true;
      break;
    }
    if (p.status === "error") {
      throw new Error(p.error || "Scan failed");
    }

    await sleep(pollInterval);
  }

  if (!sawComplete) {
    throw new Error("Scan timed out waiting for ripgrep to finish");
  }

  let resultsRes;
  try {
    resultsRes = await api.get<PatternAnalyzerScanResult>(
      `${base}/regex-scan/${scan_id}/results`,
      { params: q },
    );
  } catch (e: unknown) {
    throw new Error(axiosErrorMessage(e));
  }

  return resultsRes.data;
}
