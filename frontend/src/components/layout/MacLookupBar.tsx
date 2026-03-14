import { useState, useCallback, useMemo, useEffect } from "react";
import RouterIcon from "@mui/icons-material/Router";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import SearchIcon from "@mui/icons-material/Search";
import ClearIcon from "@mui/icons-material/Clear";
import RefreshIcon from "@mui/icons-material/Refresh";
import { cn } from "@/lib/utils";
import { utilitiesApi, type MacLookupResult, type OuiStatus } from "@/api/endpoints";

export default function MacLookupBar() {
  const [expanded, setExpanded] = useState(() => {
    try {
      return localStorage.getItem("mac-lookup-expanded") === "true";
    } catch {
      return false;
    }
  });

  const [inputText, setInputText] = useState("");
  const [results, setResults] = useState<MacLookupResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showLAA, setShowLAA] = useState(true);
  const [searchFilter, setSearchFilter] = useState("");
  const [ouiStatus, setOuiStatus] = useState<OuiStatus | null>(null);
  const [updating, setUpdating] = useState(false);
  const [reloading, setReloading] = useState(false);

  // Load OUI status on mount
  useEffect(() => {
    if (expanded) {
      utilitiesApi.ouiStatus().then(
        (response) => setOuiStatus(response.data),
        () => { /* ignore errors */ }
      );
    }
  }, [expanded]);

  const toggleExpanded = useCallback(() => {
    setExpanded((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("mac-lookup-expanded", String(next));
      } catch { /* ignore */ }
      return next;
    });
  }, []);

  const handleLookup = useCallback(async () => {
    if (!inputText.trim()) {
      setError("Please enter MAC addresses");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Split by comma and trim whitespace
      const macs = inputText
        .split(",")
        .map((m) => m.trim())
        .filter((m) => m.length > 0);

      if (macs.length === 0) {
        setError("No valid MAC addresses found");
        setLoading(false);
        return;
      }

      if (macs.length > 100) {
        setError("Maximum 100 MAC addresses per lookup");
        setLoading(false);
        return;
      }

      const response = await utilitiesApi.macLookup(macs);
      setResults(response.data);
    } catch (err: any) {
      setError(err.response?.data?.error || err.message || "Lookup failed");
    } finally {
      setLoading(false);
    }
  }, [inputText]);

  const handleClear = useCallback(() => {
    setInputText("");
    setResults([]);
    setError(null);
    setSearchFilter("");
  }, []);

  const handleUpdateOui = useCallback(async () => {
    setUpdating(true);
    setError(null);

    try {
      const response = await utilitiesApi.ouiUpdate();
      if (response.data.status === "success") {
        // Refresh status
        const statusResponse = await utilitiesApi.ouiStatus();
        setOuiStatus(statusResponse.data);
        setError(null);
        // Show success message briefly
        const successMsg = `✓ Updated: ${response.data.entries?.toLocaleString()} entries (${response.data.size_mb} MB)`;
        setError(successMsg);
        setTimeout(() => setError(null), 5000);
      } else {
        setError(response.data.message || "Update failed");
      }
    } catch (err: any) {
      setError(err.response?.data?.message || err.message || "Update failed");
    } finally {
      setUpdating(false);
    }
  }, []);

  const handleReloadOui = useCallback(async () => {
    setReloading(true);
    setError(null);

    try {
      const response = await utilitiesApi.ouiReload();
      if (response.data.status === "success") {
        // Refresh status
        const statusResponse = await utilitiesApi.ouiStatus();
        setOuiStatus(statusResponse.data);
        setError(null);
        // Show success message briefly
        const successMsg = `✓ Reloaded: ${response.data.entries?.toLocaleString()} entries`;
        setError(successMsg);
        setTimeout(() => setError(null), 5000);
      } else {
        setError(response.data.message || "Reload failed");
      }
    } catch (err: any) {
      setError(err.response?.data?.message || err.message || "Reload failed");
    } finally {
      setReloading(false);
    }
  }, []);

  // Filter results based on LAA toggle and search
  const filteredResults = useMemo(() => {
    let filtered = results;

    // Filter by LAA if toggle is off
    if (!showLAA) {
      filtered = filtered.filter((r) => r.vendor !== "LAA (Locally Administered)");
    }

    // Filter by search text
    if (searchFilter.trim()) {
      const search = searchFilter.toLowerCase();
      filtered = filtered.filter((r) =>
        r.original.toLowerCase().includes(search) ||
        r.mac?.toLowerCase().includes(search) ||
        r.oui?.toLowerCase().includes(search) ||
        r.vendor?.toLowerCase().includes(search)
      );
    }

    return filtered;
  }, [results, showLAA, searchFilter]);

  const formatLastModified = useCallback((timestamp: number | null) => {
    if (!timestamp) return "Unknown";
    const date = new Date(timestamp * 1000);
    const now = new Date();
    const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 30) return `${diffDays} days ago`;
    if (diffDays < 365) return `${Math.floor(diffDays / 30)} months ago`;
    return `${Math.floor(diffDays / 365)} years ago`;
  }, []);

  const summaryText = useMemo(() => {
    if (results.length === 0) return "";
    const successCount = results.filter((r) => r.mac && !r.error).length;
    const errorCount = results.filter((r) => r.error).length;
    const laaCount = results.filter((r) => r.vendor === "LAA (Locally Administered)").length;
    return `${successCount} MAC${successCount !== 1 ? "s" : ""} (${laaCount} LAA)${errorCount > 0 ? `, ${errorCount} error${errorCount !== 1 ? "s" : ""}` : ""}`;
  }, [results]);

  return (
    <div className="border-b border-border bg-card">
      {/* Toggle button row */}
      <button
        onClick={toggleExpanded}
        className="flex items-center gap-1.5 w-full px-4 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
      >
        <RouterIcon style={{ fontSize: 14 }} />
        <span className="font-medium">MAC OUI Lookup</span>
        {!expanded && results.length > 0 && (
          <span className="ml-2 text-muted-foreground/70">{summaryText}</span>
        )}
        <span className="ml-auto">
          {expanded ? (
            <ExpandLessIcon style={{ fontSize: 16 }} />
          ) : (
            <ExpandMoreIcon style={{ fontSize: 16 }} />
          )}
        </span>
      </button>

      {/* Expanded panel */}
      {expanded && (
        <div className="px-4 pb-3 pt-1">
          <div className="flex flex-col gap-3">
            {/* OUI Database Status */}
            {ouiStatus && (
              <div className="flex items-center justify-between px-3 py-2 rounded-md bg-muted/30 text-xs">
                <div className="flex items-center gap-3">
                  <span className="text-muted-foreground">
                    Local Database: <span className={cn(
                      "font-medium",
                      ouiStatus.entries === 0 ? "text-destructive" : "text-foreground"
                    )}>{ouiStatus.entries.toLocaleString()} vendors</span>
                  </span>
                  {ouiStatus.entries > 0 && (
                    <>
                      <span className="text-muted-foreground">
                        Size: <span className="font-medium text-foreground">{ouiStatus.file_size_mb} MB</span>
                      </span>
                      <span className="text-muted-foreground">
                        Updated: <span className="font-medium text-foreground">{formatLastModified(ouiStatus.last_modified)}</span>
                      </span>
                    </>
                  )}
                  {ouiStatus.entries === 0 && ouiStatus.file_exists && (
                    <span className="text-destructive text-xs">
                      ⚠️ Database file exists but not loaded - click Reload
                    </span>
                  )}
                  {ouiStatus.entries === 0 && !ouiStatus.file_exists && (
                    <span className="text-destructive text-xs">
                      ⚠️ Database not downloaded - click Update to download
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {ouiStatus.entries === 0 && ouiStatus.file_exists && (
                    <button
                      onClick={handleReloadOui}
                      disabled={reloading}
                      className={cn(
                        "flex items-center gap-1.5 h-7 px-3 rounded-md text-xs font-medium transition-colors",
                        reloading
                          ? "bg-muted text-muted-foreground cursor-wait"
                          : "bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20 dark:text-emerald-400"
                      )}
                      title="Reload database from existing file"
                    >
                      <RefreshIcon style={{ fontSize: 12 }} className={reloading ? "animate-spin" : ""} />
                      {reloading ? "Reloading..." : "Reload Database"}
                    </button>
                  )}
                  <button
                    onClick={handleUpdateOui}
                    disabled={updating}
                    className={cn(
                      "flex items-center gap-1.5 h-7 px-3 rounded-md text-xs font-medium transition-colors",
                      updating
                        ? "bg-muted text-muted-foreground cursor-wait"
                        : "bg-primary/10 text-primary hover:bg-primary/20"
                    )}
                    title="Download latest OUI database from IEEE"
                  >
                    <RefreshIcon style={{ fontSize: 12 }} className={updating ? "animate-spin" : ""} />
                    {updating ? "Updating..." : ouiStatus.entries === 0 ? "Download Database" : "Update Database"}
                  </button>
                </div>
              </div>
            )}

            {/* Input section */}
            <div className="flex flex-col gap-2">
              <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                MAC Addresses (comma-separated)
              </label>
              <div className="flex gap-2">
                <textarea
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  placeholder="Paste MAC addresses: 6a e1 95 7a 04 18, 6e 8b 3e 3f e9 18, ..."
                  className="flex-1 h-20 px-3 py-2 rounded-md border border-input bg-background text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                  disabled={loading}
                />
              </div>

              {/* Action buttons */}
              <div className="flex items-center gap-2">
                <button
                  onClick={handleLookup}
                  disabled={loading || !inputText.trim()}
                  className={cn(
                    "flex items-center gap-1.5 h-9 px-4 rounded-md text-xs font-medium transition-colors",
                    loading || !inputText.trim()
                      ? "bg-muted text-muted-foreground cursor-not-allowed"
                      : "bg-primary text-primary-foreground hover:bg-primary/90"
                  )}
                >
                  <SearchIcon style={{ fontSize: 14 }} />
                  {loading ? "Looking up..." : "Format & Lookup"}
                </button>

                <button
                  onClick={handleClear}
                  disabled={loading}
                  className="flex items-center gap-1.5 h-9 px-3 rounded-md bg-muted text-muted-foreground text-xs font-medium hover:bg-muted/70 transition-colors disabled:opacity-50"
                >
                  <ClearIcon style={{ fontSize: 14 }} />
                  Clear
                </button>

                {results.length > 0 && (
                  <span className="ml-auto text-xs text-muted-foreground">
                    {summaryText}
                  </span>
                )}
              </div>
            </div>

            {/* Error/Success message */}
            {error && (
              <div className={cn(
                "px-3 py-2 rounded-md text-xs",
                error.startsWith("✓") 
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : "bg-destructive/10 text-destructive"
              )}>
                {error}
              </div>
            )}

            {/* Filters */}
            {results.length > 0 && (
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={showLAA}
                    onChange={(e) => setShowLAA(e.target.checked)}
                    className="h-4 w-4 rounded border-input"
                  />
                  <span className="text-muted-foreground">Show LAA addresses</span>
                </label>

                <div className="flex-1 max-w-sm">
                  <input
                    type="text"
                    value={searchFilter}
                    onChange={(e) => setSearchFilter(e.target.value)}
                    placeholder="Search MACs, OUI, or vendor..."
                    className="w-full h-8 px-3 py-1 rounded-md border border-input bg-background text-xs focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>

                <span className="text-xs text-muted-foreground">
                  Showing {filteredResults.length} of {results.length}
                </span>
              </div>
            )}

            {/* Results table */}
            {results.length > 0 && (
              <div className="border border-border rounded-md overflow-hidden">
                <div className="max-h-[400px] overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/50 sticky top-0">
                      <tr>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground">#</th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground">Original</th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground">Formatted MAC</th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground">OUI</th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground">Vendor</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredResults.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="px-3 py-8 text-center text-muted-foreground">
                            No results match your filters
                          </td>
                        </tr>
                      ) : (
                        filteredResults.map((result, idx) => (
                        <tr
                          key={idx}
                          className={cn(
                            "border-t border-border hover:bg-muted/20 transition-colors",
                            result.error && "bg-destructive/5"
                          )}
                        >
                          <td className="px-3 py-2 text-muted-foreground">{idx + 1}</td>
                          <td className="px-3 py-2 font-mono text-muted-foreground">
                            {result.original}
                          </td>
                          <td className="px-3 py-2 font-mono font-medium">
                            {result.mac || (
                              <span className="text-destructive">Invalid</span>
                            )}
                          </td>
                          <td className="px-3 py-2 font-mono text-sm">
                            {result.oui || "-"}
                          </td>
                          <td className="px-3 py-2">
                            {result.error ? (
                              <span className="text-destructive text-xs">{result.error}</span>
                            ) : result.vendor ? (
                              <span className={cn(
                                result.vendor === "Unknown Vendor" && "text-muted-foreground italic",
                                result.vendor === "LAA (Locally Administered)" && "text-blue-600 dark:text-blue-400 font-medium"
                              )}>
                                {result.vendor}
                              </span>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </td>
                        </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Loading indicator */}
            {loading && (
              <div className="flex items-center justify-center gap-2 py-4 text-xs text-muted-foreground">
                <div className="animate-spin h-4 w-4 border-2 border-primary border-t-transparent rounded-full" />
                <span>Looking up vendors (this may take a moment)...</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
