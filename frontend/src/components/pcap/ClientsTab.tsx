import { useState, useMemo } from "react";
import type { PcapClientSummary } from "@/api/endpoints";
import ClientDetailPanel from "./ClientDetailPanel";

type SortKey = "mac" | "status" | "avg_rssi" | "retry_pct" | "frame_count" | "deauth_count" | "power_save_pct" | "seq_gaps_count";

const STATUS_ORDER: Record<string, number> = { critical: 0, warning: 1, healthy: 2 };

interface Props {
  clients: PcapClientSummary[];
  filename: string;
}

export default function ClientsTab({ clients, filename }: Props) {
  const [selectedMac, setSelectedMac] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("status");
  const [sortAsc, setSortAsc] = useState(true);
  const [search, setSearch] = useState("");

  const nonApClients = useMemo(() => clients.filter((c) => !c.is_ap), [clients]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return nonApClients;
    return nonApClients.filter((c) =>
      c.mac.toLowerCase().includes(q) ||
      (c.ssid && c.ssid.toLowerCase().includes(q)) ||
      (c.primary_bssid && c.primary_bssid.toLowerCase().includes(q)) ||
      c.status.toLowerCase().includes(q)
    );
  }, [nonApClients, search]);

  const sorted = useMemo(() => {
    const list = [...filtered];
    list.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "status") cmp = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
      else if (sortKey === "mac") cmp = a.mac.localeCompare(b.mac);
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
    else { setSortKey(key); setSortAsc(key === "status"); }
  };

  const panelOpen = !!selectedMac;

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
            placeholder="Filter by MAC, SSID, AP, or status..."
            className="w-full pl-8 pr-8 py-1.5 text-xs rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          )}
        </div>
        {search && <p className="text-[10px] text-muted-foreground mt-1">{sorted.length} of {nonApClients.length} clients</p>}
      </div>

      {/* Client Table */}
      <div className={`border-b border-border overflow-auto shrink-0 ${panelOpen ? "max-h-[160px]" : "flex-1"}`}>
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-muted z-10">
            <tr>
              <TH k="status" label="Status" />
              <TH k="mac" label="MAC" />
              <th className="text-left px-2 py-1.5 font-semibold text-muted-foreground text-[10px] uppercase">AP</th>
              <th className="text-left px-2 py-1.5 font-semibold text-muted-foreground text-[10px] uppercase">SSID</th>
              <TH k="avg_rssi" label="RSSI" />
              <TH k="retry_pct" label="Retry%" />
              <TH k="power_save_pct" label="PS%" />
              <TH k="seq_gaps_count" label="Seq Gaps" />
              <TH k="frame_count" label="Frames" />
              <TH k="deauth_count" label="Deauths" />
              <th className="text-left px-2 py-1.5 font-semibold text-muted-foreground text-[10px] uppercase">EAPOL</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {sorted.map((c) => (
              <tr
                key={c.mac}
                onClick={() => setSelectedMac(selectedMac === c.mac ? null : c.mac)}
                className={`cursor-pointer transition-colors ${selectedMac === c.mac ? "bg-accent" : "hover:bg-muted/50"}`}
              >
                <td className="px-2 py-1">{statusDot(c.status)}</td>
                <td className="px-2 py-1 font-mono">{c.mac}</td>
                <td className="px-2 py-1 font-mono text-muted-foreground">{c.primary_bssid || "—"}</td>
                <td className="px-2 py-1 truncate max-w-[100px]">{c.ssid || "—"}</td>
                <td className="px-2 py-1 tabular-nums">{c.avg_rssi != null ? c.avg_rssi.toFixed(0) : "—"}</td>
                <td className="px-2 py-1 tabular-nums">{c.retry_pct.toFixed(1)}</td>
                <td className="px-2 py-1 tabular-nums">{c.power_save_pct.toFixed(0)}</td>
                <td className="px-2 py-1 tabular-nums">{c.seq_gaps_count}</td>
                <td className="px-2 py-1 tabular-nums">{c.frame_count}</td>
                <td className="px-2 py-1 tabular-nums">{c.deauth_count}</td>
                <td className="px-2 py-1">
                  {c.eapol_status === "complete" ? <span className="text-emerald-400 font-medium">4/4</span>
                   : c.eapol_status === "incomplete" ? <span className="text-amber-400 font-medium">Fail</span>
                   : "—"}
                </td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr><td colSpan={11} className="text-center py-6 text-muted-foreground">No clients found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Detail Panel */}
      {selectedMac && (
        <div className="flex-1 overflow-y-auto border-t border-border">
          <ClientDetailPanel mac={selectedMac} filename={filename} />
        </div>
      )}
    </div>
  );
}
