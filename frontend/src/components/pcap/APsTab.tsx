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

  const sorted = useMemo(() => {
    const list = [...aps];
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
  }, [aps, sortKey, sortAsc]);

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
