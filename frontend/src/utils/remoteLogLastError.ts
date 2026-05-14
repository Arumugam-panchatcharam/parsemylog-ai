/**
 * Remote fetch units store last_error as plain text (legacy) or JSON from RemoteLogFetchError
 * { error_code, message, remediation? }.
 */

export type ParsedRemoteLogLastError = {
  message: string;
  errorCode?: string;
  remediation?: string;
};

export function parseRemoteLogLastError(
  raw: string | null | undefined
): ParsedRemoteLogLastError {
  if (!raw?.trim()) {
    return { message: "" };
  }
  const t = raw.trim();
  if (t.startsWith("{")) {
    try {
      const o = JSON.parse(t) as {
        error_code?: string;
        message?: string;
        remediation?: string;
      };
      if (typeof o.message === "string") {
        return {
          message: o.message,
          errorCode: typeof o.error_code === "string" ? o.error_code : undefined,
          remediation: o.remediation?.trim() || undefined,
        };
      }
    } catch {
      /* fall through — treat as legacy single-line error */
    }
  }
  return { message: t };
}
