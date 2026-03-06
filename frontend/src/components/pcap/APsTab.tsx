import { useState, useMemo } from "react";
import type { PcapApSummary } from "@/api/endpoints";
import APDetailPanel from "./APDetailPanel";

type SortKey = "bssid" | "status" | "client_count" | "avg_retry_pct" | "avg_rssi" | "beacon_count";
const STATUS_ORDER: Record<string, number> = { critical: 0, warning: 1, healthy: 2 };

interface Props {
  aps: PcapApSummary[];
  filename: string;
}

export default function APsTab({ aps, filename }: Props) {
  const [selectedBssid, setSelectedBssid] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("client_count");
  const [sortAsc, setSortAsc] = useState(false);
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return aps;
    return aps.filter((ap) =>
      ap.bssid.toLowerCase().includes(q) ||
      (ap.ssid && ap.ssid.toLowerCase().includes(q)) ||
      ap.status.toLowerCase().includes(q) ||
      (ap.channel != null && String(ap.channel).includes(q))
    );
  }, [aps, search]);

  const sorted = useMemo(() => {
    const list = [...filtered];
    list.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "status") cmp = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
      else if (sortKey === "bssid") cmp = a.bssid.localeCompare(b.bssid);
      else {
        const av = (a as unknown as Record<string, unknown>)[sortKey] as number ?? 0;
        const bv = (b as unknown as Record<string, unknown>)[sortKey] as number ?? 0;
        cmp = av - bv;
      }
      return sortAsc ? cmp : -cmp;
    });
    return list;
  }, [filtered, sortKey, sortAsc]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  const panelOpen = !!selectedBssid;

  const TH = ({ k, label }: { k: SortKey; label: string }) => (
    <th onClick={() => handleSort(k)} className="text-left px-2 py-1.5 font-semibold text-muted-foreground text-[10px] uppercase cursor-pointer hover:text-foreground whitespace-nowrap">
      {label}{sortKey === k ? (sortAsc ? " ▲" : " ▼") : ""}
    </th>
  );

  const statusDot = (s: string) => {
    const c = s === "critical" ? "bg-red-500" : s === "warning" ? "bg-amber-500" : "bg-emerald-500";
    return <span className={`inline-block w-2 h-2 rounded-full ${c}`} />;
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Search bar */}
      <div className="px-3 py-2 border-b border-border shrink-0">
        <div className="relative">
          <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter by BSSID, SSID, channel, or status..."
            className="w-full pl-8 pr-8 py-1.5 text-xs rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          )}
        </div>
        {search && <p className="text-[10px] text-muted-foreground mt-1">{sorted.length} of {aps.length} APs</p>}
      </div>

      {/* AP Table */}
      <div className={`border-b border-border overflow-auto shrink-0 ${panelOpen ? "max-h-[160px]" : "flex-1"}`}>
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-muted z-10">
            <tr>
              <TH k="status" label="Status" />
              <TH k="bssid" label="BSSID" />
              <th className="text-left px-2 py-1.5 font-semibold text-muted-foreground text-[10px] uppercase">SSID</th>
              <th className="text-left px-2 py-1.5 font-semibold text-muted-foreground text-[10px] uppercase">Channel</th>
              <TH k="client_count" label="Clients" />
              <TH k="avg_retry_pct" label="Avg Retry%" />
              <TH k="avg_rssi" label="Avg RSSI" />
              <TH k="beacon_count" label="Beacons" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {sorted.map((ap) => (
              <tr
                key={ap.bssid}
                onClick={() => setSelectedBssid(selectedBssid === ap.bssid ? null : ap.bssid)}
                className={`cursor-pointer transition-colors ${selectedBssid === ap.bssid ? "bg-accent" : "hover:bg-muted/50"}`}
              >
                <td className="px-2 py-1">{statusDot(ap.status)}</td>
                <td className="px-2 py-1 font-mono">{ap.bssid}</td>
                <td className="px-2 py-1 truncate max-w-[120px]">{ap.ssid || "—"}</td>
                <td className="px-2 py-1 tabular-nums">{ap.channel ?? "—"}</td>
                <td className="px-2 py-1 tabular-nums">{ap.client_count}</td>
                <td className="px-2 py-1 tabular-nums">{ap.avg_retry_pct.toFixed(1)}</td>
                <td className="px-2 py-1 tabular-nums">{ap.avg_rssi != null ? ap.avg_rssi.toFixed(0) : "—"}</td>
                <td className="px-2 py-1 tabular-nums">{ap.beacon_count}</td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr><td colSpan={8} className="text-center py-6 text-muted-foreground">No APs found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Detail Panel */}
      {selectedBssid && (
        <div className="flex-1 overflow-y-auto border-t border-border">
          <APDetailPanel bssid={selectedBssid} filename={filename} />
        </div>
      )}
    </div>
  );
}
