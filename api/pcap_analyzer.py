"""
PCAP Analyzer
=============

Fast tshark CSV export → pandas analysis for 802.11 and IEEE 1905.1.
One tshark pass, cached CSV, pure pandas (no ML). Overview-first UX
with drill-down per client/AP and Plotly-ready timelines.
"""

import io
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

pd.set_option("future.no_silent_downcasting", True)

logger = logging.getLogger(__name__)

# ── tshark fields (verified for Wireshark 4.x) ─────────────────────────────────

TSHARK_FIELDS = [
    "frame.number",
    "frame.time_epoch",
    "frame.len",
    "frame.interface_id",
    "frame.interface_name",
    "eth.src",
    "eth.dst",
    "eth.type",
    "wlan.sa",
    "wlan.da",
    "wlan.ta",
    "wlan.ra",
    "wlan.bssid",
    "wlan.fc.type",
    "wlan.fc.subtype",
    "wlan.fc.retry",
    "wlan.fc.protected",
    "wlan.fc.pwrmgt",
    "wlan.duration",
    "wlan.seq",
    "wlan.frag",
    "radiotap.dbm_antsignal",
    "radiotap.dbm_antnoise",
    "radiotap.antenna",
    "radiotap.datarate",
    "radiotap.channel.freq",
    "radiotap.channel.flags",
    "radiotap.mcs.index",
    "radiotap.mcs.bw",
    "radiotap.vht.mcs.0",
    "radiotap.vht.nss.0",
    "radiotap.he.data_3.data_mcs",
    "radiotap.he.data_6.nsts",
    "wlan_radio.channel",
    "wlan_radio.frequency",
    "wlan_radio.phy",
    "wlan.ssid",
    "wlan.fixed.status_code",
    "wlan.fixed.reason_code",
    "wlan.fixed.auth.alg",
    "wlan.fixed.auth_seq",
    "wlan.fixed.capabilities",
    "wlan.rsn.version",
    "wlan.rsn.akms.type",
    "wlan.rsn.pcs.type",
    "wlan.qos.tid",
    "wlan.qos.priority",
    "eapol.type",
    "eapol.keydes.type",
    "wlan_rsna_eapol.keydes.msgnr",
    "ip.src",
    "ip.dst",
    "ip.proto",
    "arp.opcode",
    "icmp.type",
    "tcp.analysis.retransmission",
    "tcp.analysis.lost_segment",
    "ieee1905.message_type",
    "ieee1905.message_id",
    "ieee1905.1905_al_mac_addr",
]

BROADCAST = {"ff:ff:ff:ff:ff:ff", ""}

DEAUTH_REASONS: dict[int, str] = {
    0: "Reserved",
    1: "Unspecified reason",
    2: "Previous auth no longer valid",
    3: "Station leaving BSS",
    4: "Inactivity timeout",
    5: "AP unable to handle STAs",
    6: "Class 2 frame from non-auth STA",
    7: "Class 3 frame from non-assoc STA",
    8: "STA leaving BSS (roaming)",
    9: "STA not authenticated",
    10: "Disassoc - power capability unacceptable",
    11: "Disassoc - supported channels unacceptable",
    12: "Invalid BSSID",
    13: "Invalid auth seq",
    14: "Challenge failure",
    15: "4-Way Handshake timeout",
    16: "Group Key Handshake timeout",
    17: "4-Way Handshake mismatch",
    18: "Invalid group cipher",
    19: "Invalid pairwise cipher",
    20: "Invalid AKMP",
    21: "Unsupported RSN IE version",
    22: "Invalid RSN IE capabilities",
    23: "802.1X auth failed",
    24: "Cipher suite rejected",
    25: "TDLS teardown unreachable",
    26: "TDLS unreachable",
    27: "QoS policy violation",
    39: "Requested mechanism unavailable",
    45: "Peer STA not ISTA",
    46: "Peer STA not ESTA",
}

ASSOC_STATUS_CODES: dict[int, str] = {
    0: "Successful",
    1: "Unspecified failure",
    2: "TDLS rejected - alternative provisioned",
    3: "TDLS rejected - refused",
    4: "Security disabled",
    5: "Unacceptable lifetime",
    6: "Not in same BSS",
    7: "Capabilities mismatch",
    8: "No association",
    9: "Auth algorithm not supported",
    10: "Cannot support all requested capabilities",
    11: "Reassoc denied - could not confirm",
    12: "Denied - not in same BSS",
    13: "Refused - outside scope",
    14: "Auth rejected (challenge failure)",
    15: "Auth rejected (seq timeout)",
    16: "Auth rejected (4-way timeout)",
    17: "Assoc denied - AP busy",
    18: "Assoc denied - bad power capability",
    19: "Assoc denied - bad channel",
    20: "Assoc denied - short preamble",
    21: "Assoc denied - PBCC",
    22: "Assoc denied - channel agility",
    23: "Assoc denied - spectrum mgmt required",
    24: "Assoc denied - power capability unacceptable",
    25: "Assoc denied - supported channels unacceptable",
    26: "Assoc denied - short slot time",
    27: "Assoc denied - DSSS OFDM",
    28: "Assoc denied - no HT support",
    29: "Assoc denied - R0KH unreachable",
    30: "Refused - TS not created",
    31: "Refused - direct link not allowed",
    32: "Refused - destination STA not present",
    33: "Refused - destination STA not QSTA",
    34: "Refused - PMKSA invalid",
    35: "Refused - insufficient bandwidth",
    36: "Refused - poor channel conditions",
    37: "Rejected - R0KH unreachable",
    38: "Refused - per-station policy",
    39: "Refused - not authorized",
    40: "Refused - not successful",
    41: "Refused - not sufficient bandwidth",
    42: "Refused - excessive frames",
    43: "Assoc denied (HT capabilities)",
    44: "Refused - R0KH unreachable",
    45: "Refused - authorization delegation",
    46: "Refused - BSS transition",
    47: "Refused - invalid RSNE",
    48: "Refused - U-APSD coexistence",
    49: "Refused - restricted access",
    50: "Refused - bad FT action frame count",
    51: "Refused - bad pairwise cipher",
    52: "Refused - unsupported RSNE version",
    53: "Invalid RSNE",
    54: "Refused - U-APSD coexistence",
    55: "Refused - invalid FT action frame count",
    56: "Refused - policy",
    57: "Refused - not authorized",
    58: "Refused - service change",
    59: "Refused - extended schedule",
    60: "Refused - pending admittance",
    61: "Refused - per-station policy",
    62: "Refused - not authorized",
    67: "Refused - TCLAS",
    68: "Refused - TCLAS resource",
    69: "Refused - TCLAS processing",
    70: "Refused - no suitable TCLAS",
    71: "Refused - TCLAS rejected",
    72: "Refused - invalid parameters",
    73: "Refused - not authorized",
    82: "Refused - not authorized",
}

PHY_NAMES: dict[int, str] = {
    0: "Unknown",
    1: "802.11 FHSS",
    2: "802.11 IR",
    3: "802.11 DSSS",
    4: "802.11b",
    5: "802.11a",
    6: "802.11g",
    7: "802.11n (HT)",
    8: "802.11ac (VHT)",
    9: "802.11ad (DMG)",
    10: "802.11ah",
    11: "802.11ax (HE)",
    12: "802.11be (EHT)",
}

MSG_1905_TYPES: dict[int, str] = {
    0x0000: "Topology Discovery",
    0x0001: "Topology Notification",
    0x0002: "Topology Query",
    0x0003: "Topology Response",
    0x0004: "Vendor Specific",
    0x0005: "Link Metric Query",
    0x0006: "Link Metric Response",
    0x0007: "AP-Autoconfiguration Search",
    0x0008: "AP-Autoconfiguration Response",
    0x0009: "AP-Autoconfiguration WSC",
    0x000A: "AP-Autoconfiguration Renew",
    0x8000: "1905 ACK",
    0x8001: "AP Capability Query",
    0x8002: "AP Capability Response",
    0x8003: "Multi-AP Config",
    0x8004: "Channel Selection Request",
    0x8005: "Channel Selection Response",
    0x8006: "Channel Scan Request",
    0x8007: "Channel Scan Report",
    0x8008: "Channel Scan Results",
    0x8009: "STA Capability Query",
    0x800A: "STA Capability Response",
    0x800B: "AP Metrics Query",
    0x800C: "AP Metrics Response",
    0x800D: "STA Link Metrics Query",
    0x800E: "STA Link Metrics Response",
    0x800F: "Unassoc STA Metrics Query",
    0x8010: "Unassoc STA Metrics Response",
    0x8011: "Beacon Metrics Query",
    0x8012: "Beacon Metrics Response",
    0x8013: "Combined Infra Metrics",
    0x8014: "Client Steering Request",
    0x8015: "Client Steering Response",
    0x8016: "Client Steering BTM",
    0x8017: "Client Steering ACK",
    0x8019: "BH Optimization Request",
    0x801A: "BH Optimization Response",
    0x801B: "Channel Scan Request",
    0x801C: "Channel Scan Report",
    0x8020: "DFS CAC Request",
    0x8021: "DFS CAC Response",
    0x8044: "MLD Config Request",
    0x8045: "MLD Config Response",
    0x8046: "MLD Config Report",
    0x8047: "MLD Config ACK",
}

_REQUEST_RESPONSE_PAIRS: dict[int, int] = {
    0x0002: 0x0003,
    0x0003: 0x0002,
    0x0005: 0x0006,
    0x0006: 0x0005,
    0x0007: 0x0008,
    0x0008: 0x0007,
    0x0009: 0x000A,
    0x000A: 0x0009,
    0x8001: 0x8002,
    0x8002: 0x8001,
    0x8004: 0x8005,
    0x8005: 0x8004,
    0x8006: 0x8007,
    0x8007: 0x8006,
    0x8009: 0x800A,
    0x800A: 0x8009,
    0x800B: 0x800C,
    0x800C: 0x800B,
    0x800D: 0x800E,
    0x800E: 0x800D,
    0x800F: 0x8010,
    0x8010: 0x800F,
    0x8011: 0x8012,
    0x8012: 0x8011,
    0x8014: 0x8015,
    0x8015: 0x8014,
    0x8019: 0x801A,
    0x801A: 0x8019,
    0x801B: 0x801C,
    0x801C: 0x801B,
    0x8020: 0x8021,
    0x8021: 0x8020,
    0x8044: 0x8045,
    0x8045: 0x8044,
    0x8046: 0x8047,
    0x8047: 0x8046,
}

MSG_CATEGORY: dict[int, str] = {
    0x0000: "Topology",
    0x0001: "Topology",
    0x0002: "Topology",
    0x0003: "Topology",
    0x0004: "Vendor Specific",
    0x0005: "Link Metric",
    0x0006: "Link Metric",
    0x0007: "AP Config",
    0x0008: "AP Config",
    0x0009: "AP Config",
    0x000A: "AP Config",
    0x8001: "AP Capability",
    0x8002: "AP Capability",
    0x8003: "Multi-AP Config",
    0x8004: "Channel Selection",
    0x8005: "Channel Selection",
    0x8006: "Channel Selection",
    0x8007: "Channel Selection",
    0x8008: "Channel Selection",
    0x8009: "STA Capability",
    0x800A: "STA Capability",
    0x800B: "AP Metrics",
    0x800C: "AP Metrics",
    0x800D: "STA Link Metrics",
    0x800E: "STA Link Metrics",
    0x800F: "Unassoc STA Metrics",
    0x8010: "Unassoc STA Metrics",
    0x8011: "Beacon Metrics",
    0x8012: "Beacon Metrics",
    0x8013: "Combined Infra Metrics",
    0x8014: "Client Steering",
    0x8015: "Client Steering",
    0x8016: "Client Steering",
    0x8017: "Client Steering",
    0x8019: "BH Optimization",
    0x801A: "BH Optimization",
    0x801B: "Channel Scan",
    0x801C: "Channel Scan",
    0x8020: "DFS CAC",
    0x8021: "DFS CAC",
    0x8044: "MLD Config",
    0x8045: "MLD Config",
    0x8046: "MLD Config",
    0x8047: "MLD Config",
}

PERIODIC_MSG_TYPES: set[int] = {0x0000, 0x0001, 0x800C}

MAX_TIMELINE_POINTS = 1000
BUCKET_SECONDS = 30


# ── Helper functions ─────────────────────────────────────────────────────────

def _to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(0, index=df.index)
    s = df[col].fillna("").astype(str).str.strip().str.lower()
    return s.isin(("1", "true", "yes")).astype(int)


def _safe_col(df: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index)
    return df[col].fillna(default).astype(str).str.strip()


def _downsample(rows: list, max_n: int = MAX_TIMELINE_POINTS) -> list:
    if len(rows) <= max_n:
        return rows
    step = max(1, len(rows) // max_n)
    return [rows[i] for i in range(0, len(rows), step)]


def _cache_is_valid(pcap_path: str, cache_path: Path) -> bool:
    if not cache_path.exists():
        return False
    return cache_path.stat().st_mtime >= Path(pcap_path).stat().st_mtime


def _decode_hex_ssid(hex_str: str) -> str:
    if not hex_str or hex_str.strip() == "":
        return ""
    try:
        h = hex_str.strip().replace(":", "").replace(" ", "")
        if len(h) % 2:
            return hex_str
        b = bytes.fromhex(h)
        return b.decode("utf-8", errors="replace")
    except Exception:
        return hex_str


def _decode_ssid_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).apply(_decode_hex_ssid)


def _reason_desc(reason: Optional[int]) -> str:
    if reason is None:
        return ""
    return DEAUTH_REASONS.get(reason, f"Unknown ({reason})")


def _parse_bad_fields(stderr: str) -> set[str]:
    return set(re.findall(r"^\s+(\S+)\s*$", stderr, re.MULTILINE))


def _run_tshark(pcap_path: str, fields: list[str]) -> subprocess.CompletedProcess:
    field_args: list[str] = []
    for f in fields:
        field_args += ["-e", f]
    cmd = [
        "tshark",
        "-r", pcap_path,
        "-T", "fields",
        *field_args,
        "-E", "header=y",
        "-E", "separator=,",
        "-E", "quote=d",
        "-E", "occurrence=f",
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)


# ── Standalone protocol detection ─────────────────────────────────────────────

def detect_protocol(filepath: str, max_packets: int = 200) -> str:
    """
    Detect protocol from first N packets using tshark.
    Returns "802.11", "easymesh", "mixed", or "unknown".
    """
    try:
        cmd = [
            "tshark",
            "-r", filepath,
            "-c", str(max_packets),
            "-T", "fields",
            "-e", "eth.type",
            "-e", "wlan.fc.type",
            "-e", "ieee1905.message_type",
            "-E", "header=n",
            "-E", "separator=,",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0 or not result.stdout.strip():
            return "unknown"

        has_1905 = False
        has_wlan = False
        for line in result.stdout.strip().split("\n"):
            parts = line.split(",")
            eth_type = (parts[0].strip() if len(parts) > 0 else "").lower()
            wlan_type = (parts[1].strip() if len(parts) > 1 else "")
            ieee1905 = (parts[2].strip() if len(parts) > 2 else "")

            if "893a" in eth_type or ieee1905:
                has_1905 = True
            if wlan_type or "wlan" in str(parts).lower():
                has_wlan = True

        if has_1905 and has_wlan:
            return "mixed"
        if has_1905:
            return "easymesh"
        if has_wlan:
            return "802.11"
        return "unknown"
    except Exception as exc:
        logger.warning("detect_protocol failed: %s", exc)
        return "unknown"


# ── PcapFastAnalyzer ──────────────────────────────────────────────────────────

class PcapFastAnalyzer:
    """
    Fast PCAP analysis via tshark CSV export + pandas.
    One tshark pass, cached CSV, pure pandas (no ML).
    """

    def __init__(self, pcap_path: str):
        self._path = pcap_path
        self._df: Optional[pd.DataFrame] = None
        self._cache_path = Path(pcap_path).parent / f"{Path(pcap_path).name}.pcap_cache.csv"

    def ensure_exported(self, force: bool = False) -> pd.DataFrame:
        """Run tshark export, cache CSV, load into DataFrame."""
        if self._df is not None and not force:
            return self._df

        if not force and _cache_is_valid(self._path, self._cache_path):
            logger.info("Cache hit for %s", self._path)
            self._df = pd.read_csv(str(self._cache_path), dtype=str, keep_default_na=False)
            if "wlan.ssid" in self._df.columns:
                self._df["wlan.ssid"] = _decode_ssid_series(self._df["wlan.ssid"])
            return self._df

        logger.info("Running tshark export for %s", self._path)
        result = _run_tshark(self._path, TSHARK_FIELDS)

        if result.returncode != 0 and "fields aren't valid" in result.stderr:
            bad = _parse_bad_fields(result.stderr)
            if bad:
                good_fields = [f for f in TSHARK_FIELDS if f not in bad]
                logger.warning("Retrying tshark without invalid fields: %s", bad)
                result = _run_tshark(self._path, good_fields)

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if not result.stdout.strip():
                raise RuntimeError(f"tshark failed (rc={result.returncode}): {stderr}")
            logger.warning("tshark returned rc=%d but produced output", result.returncode)

        self._cache_path.write_text(result.stdout)
        self._df = pd.read_csv(io.StringIO(result.stdout), dtype=str, keep_default_na=False)
        if "wlan.ssid" in self._df.columns:
            self._df["wlan.ssid"] = _decode_ssid_series(self._df["wlan.ssid"])
        return self._df

    def _detect_aps(self, df: pd.DataFrame) -> set[str]:
        fc_type = _to_num(_safe_col(df, "wlan.fc.type", "0"))
        fc_sub = _to_num(_safe_col(df, "wlan.fc.subtype", "0"))
        beacon = (fc_type == 0) & (fc_sub == 8)
        probe_resp = (fc_type == 0) & (fc_sub == 5)
        bssid_col = _safe_col(df, "wlan.bssid", "")
        ap_macs = set()
        for idx in df[beacon | probe_resp].index:
            b = bssid_col.iloc[idx] if idx < len(bssid_col) else ""
            if b and b.lower() not in BROADCAST:
                ap_macs.add(b.strip().lower())
        return ap_macs

    def _detect_protocol(self, df: pd.DataFrame) -> str:
        has_1905 = _safe_col(df, "ieee1905.message_type", "").str.strip().ne("").any()
        has_wlan = _safe_col(df, "wlan.sa", "").str.strip().ne("").any()
        if has_1905 and has_wlan:
            return "mixed"
        if has_1905:
            return "easymesh"
        if has_wlan:
            return "802.11"
        return "unknown"

    def get_overview(self) -> dict:
        df = self.ensure_exported()
        if df.empty:
            return {
                "capture_info": {"total_frames": 0, "duration": 0, "frame_rate": 0},
                "network_summary": {"ap_count": 0, "client_count": 0, "ssids": [], "channels": []},
                "health": {"status": "HEALTHY", "score": 100, "issues": [], "recommendations": []},
                "activity_timeline": [],
                "channel_distribution": [],
                "protocol_detected": "unknown",
                "eapol_per_pair": [],
            }

        epoch = _to_num(df["frame.time_epoch"])
        epoch = epoch.dropna()
        if epoch.empty:
            duration = 0.0
        else:
            duration = float(epoch.max() - epoch.min())

        ap_set = self._detect_aps(df)
        sa_col = _safe_col(df, "wlan.sa", "").str.strip().str.lower()
        clients = set(sa_col[~sa_col.isin(BROADCAST) & sa_col.ne("")]) - ap_set

        ssid_col = _safe_col(df, "wlan.ssid", "")
        ssids = list(ssid_col[ssid_col.ne("")].unique())[:20]

        ch_col = _to_num(_safe_col(df, "wlan_radio.channel", ""))
        channels = sorted(ch_col.dropna().unique().astype(int).tolist())

        retry_col = _bool_col(df, "wlan.fc.retry")
        total = len(df)
        retry_pct = (retry_col.sum() / total * 100) if total > 0 else 0

        fc_type = _to_num(_safe_col(df, "wlan.fc.type", "0"))
        fc_sub = _to_num(_safe_col(df, "wlan.fc.subtype", "0"))
        deauth_count = int(((fc_type == 0) & (fc_sub == 12)).sum())

        eapol_msg = _safe_col(df, "wlan_rsna_eapol.keydes.msgnr", "").replace("", np.nan).dropna()
        incomplete_eapol = 0
        if len(eapol_msg) > 0:
            msgs = set(eapol_msg.astype(str).str.strip().str.lower())
            if "4" not in msgs and len(msgs) > 0:
                incomplete_eapol = 1

        critical = 0
        warning = 0
        issues: list[dict] = []
        if retry_pct > 30:
            critical += 1
            issues.append({"severity": "critical", "description": f"Retry rate {retry_pct:.1f}%", "affected_mac": None, "metric_value": round(retry_pct, 1)})
        elif retry_pct > 15:
            warning += 1
            issues.append({"severity": "warning", "description": f"Retry rate {retry_pct:.1f}%", "affected_mac": None, "metric_value": round(retry_pct, 1)})
        if deauth_count > 5:
            critical += 1
            issues.append({"severity": "critical", "description": f"{deauth_count} deauth frames", "affected_mac": None, "metric_value": deauth_count})
        elif deauth_count > 0:
            warning += 1
            issues.append({"severity": "warning", "description": f"{deauth_count} deauth frames", "affected_mac": None, "metric_value": deauth_count})
        if incomplete_eapol:
            warning += 1
            issues.append({"severity": "warning", "description": "Incomplete EAPOL handshake(s)", "affected_mac": None, "metric_value": 0})

        score = max(0, min(100, 100 - critical * 25 - warning * 10))
        status = "CRITICAL" if critical > 0 else "WARNING" if warning > 0 else "HEALTHY"

        df_time = df.copy()
        df_time["epoch"] = epoch
        df_time = df_time.dropna(subset=["epoch"])
        if df_time.empty:
            activity_timeline = []
        else:
            df_time["datetime"] = pd.to_datetime(df_time["epoch"], unit="s", utc=True)
            df_time = df_time.set_index("datetime")
            bucket = df_time.resample(f"{BUCKET_SECONDS}s").agg(
                mgmt=("wlan.fc.type", lambda x: (pd.to_numeric(x, errors="coerce") == 0).sum()),
                ctrl=("wlan.fc.type", lambda x: (pd.to_numeric(x, errors="coerce") == 1).sum()),
                data=("wlan.fc.type", lambda x: (pd.to_numeric(x, errors="coerce") == 2).sum()),
            ).fillna(0)
            activity_timeline = _downsample([
                {"epoch": int(idx.timestamp()), "mgmt_count": int(r.mgmt), "ctrl_count": int(r.ctrl), "data_count": int(r.data)}
                for idx, r in bucket.iterrows()
            ])

        ch_dist = []
        for ch in channels:
            mask = ch_col == ch
            cnt = int(mask.sum())
            if cnt > 0:
                rp = (retry_col[mask].sum() / cnt * 100) if cnt > 0 else 0
                ch_dist.append({"channel": ch, "frame_count": cnt, "retry_pct": round(rp, 2), "client_count": 0})

        eapol_pairs = []
        if "wlan.sa" in df.columns and "wlan.da" in df.columns and "wlan_rsna_eapol.keydes.msgnr" in df.columns:
            eapol_df = df[_safe_col(df, "wlan_rsna_eapol.keydes.msgnr", "").ne("")].copy()
            if not eapol_df.empty:
                for (ap, client), grp in eapol_df.groupby(["wlan.sa", "wlan.da"]):
                    msgs = set(grp["wlan_rsna_eapol.keydes.msgnr"].astype(str).str.strip())
                    eapol_pairs.append({
                        "ap_mac": str(ap),
                        "client_mac": str(client),
                        "messages_seen": sorted(msgs),
                        "complete": "4" in msgs and "1" in msgs and "2" in msgs and "3" in msgs,
                    })

        mgmt_frames = int((fc_type == 0).sum())
        ctrl_frames = int((fc_type == 1).sum())
        data_frames = int((fc_type == 2).sum())
        disassoc_count = int(((fc_type == 0) & (fc_sub == 10)).sum())
        retry_frames = int(retry_col.sum())

        start_time = round(float(epoch.min()), 3) if not epoch.empty else 0
        end_time = round(float(epoch.max()), 3) if not epoch.empty else 0

        recommendations = []
        if deauth_count > 0:
            recommendations.append({"action": "Investigate deauth source", "reason": f"{deauth_count} deauth frames detected"})
        if retry_pct > 15:
            recommendations.append({"action": "Check signal/interference", "reason": f"High retry rate {retry_pct:.1f}%"})
        if incomplete_eapol:
            recommendations.append({"action": "Review EAPOL handshakes", "reason": "Incomplete 4-way handshakes detected"})
        if not recommendations:
            recommendations.append({"action": "No action needed", "reason": "Network looks healthy"})

        eapol_handshakes = []
        for ep in eapol_pairs:
            steps = sorted(int(m) for m in ep["messages_seen"] if m.isdigit())
            eapol_handshakes.append({
                "client": ep["client_mac"],
                "ap": ep["ap_mac"],
                "steps_seen": steps,
                "complete": ep["complete"],
            })

        return {
            "capture_info": {
                "total_frames": total,
                "duration": round(duration, 2),
                "frame_rate": round(total / duration, 1) if duration > 0 else 0,
                "start_time": start_time,
                "end_time": end_time,
                "mgmt_frames": mgmt_frames,
                "ctrl_frames": ctrl_frames,
                "data_frames": data_frames,
                "deauth_frames": deauth_count,
                "disassoc_frames": disassoc_count,
                "retry_frames": retry_frames,
                "retry_pct": round(retry_pct, 2),
            },
            "network_summary": {
                "ap_count": len(ap_set),
                "client_count": len(clients),
                "ssids": ssids,
                "channels": channels,
            },
            "health": {
                "status": status,
                "score": score,
                "critical_count": critical,
                "warning_count": warning,
                "issues": issues,
                "recommendations": recommendations,
            },
            "eapol_handshakes": eapol_handshakes,
            "activity_timeline": activity_timeline,
            "channel_distribution": ch_dist,
            "protocol_detected": self._detect_protocol(df),
            "cache_used": _cache_is_valid(self._path, self._cache_path),
        }

    def get_client_list(self) -> list[dict]:
        df = self.ensure_exported()
        ap_set = self._detect_aps(df)
        sa_col = _safe_col(df, "wlan.sa", "").str.strip().str.lower()
        clients = set(sa_col[~sa_col.isin(BROADCAST) & sa_col.ne("")]) - ap_set

        retry_col = _bool_col(df, "wlan.fc.retry")
        rssi_col = _to_num(_safe_col(df, "radiotap.dbm_antsignal", ""))
        pwrmgt_col = _bool_col(df, "wlan.fc.pwrmgt")
        bssid_col = _safe_col(df, "wlan.bssid", "").str.strip().str.lower()
        ssid_col = _safe_col(df, "wlan.ssid", "")
        fc_type = _to_num(_safe_col(df, "wlan.fc.type", "0"))
        fc_sub = _to_num(_safe_col(df, "wlan.fc.subtype", "0"))
        deauth_mask = (fc_type == 0) & (fc_sub == 12)

        result = []
        for mac in clients:
            mask = sa_col == mac
            total = int(mask.sum())
            if total == 0:
                continue
            retries = int(retry_col[mask].sum())
            retry_pct = round(retries / total * 100, 2)
            rssi_vals = rssi_col[mask].dropna()
            avg_rssi = round(float(rssi_vals.mean()), 1) if len(rssi_vals) > 0 else None
            ps_pct = round(float(pwrmgt_col[mask].sum()) / total * 100, 2) if total > 0 else 0
            bssids = bssid_col[mask].unique()
            primary_bssid = next((b for b in bssids if b and b not in BROADCAST), "")
            ssids = ssid_col[mask][ssid_col[mask].ne("")].unique()
            ssid = ssids[0] if len(ssids) > 0 else ""
            deauth_n = int((deauth_mask & (df["wlan.da"].fillna("").astype(str).str.strip().str.lower() == mac)).sum())

            seq_col = _to_num(_safe_col(df, "wlan.seq", ""))
            seq_vals = seq_col[mask].dropna()
            seq_gaps = 0
            if len(seq_vals) > 1:
                s = seq_vals.sort_index().values
                for i in range(1, len(s)):
                    d = (int(s[i]) - int(s[i - 1])) % 4096
                    if d > 1 and d < 4090:
                        seq_gaps += 1

            status = "critical" if retry_pct > 20 or deauth_n > 5 else "warning" if retry_pct > 10 or deauth_n > 0 else "healthy"
            result.append({
                "mac": mac,
                "is_ap": False,
                "status": status,
                "primary_bssid": primary_bssid,
                "ssid": ssid,
                "avg_rssi": avg_rssi,
                "retry_pct": retry_pct,
                "frame_count": total,
                "deauth_count": deauth_n,
                "channels": [],
                "power_save_pct": ps_pct,
                "seq_gaps_count": seq_gaps,
                "eapol_status": "complete" if deauth_n == 0 else "incomplete",
            })

        result.sort(key=lambda x: (0 if x["status"] == "critical" else 1 if x["status"] == "warning" else 2, -x["retry_pct"]))
        return result

    def get_ap_list(self) -> list[dict]:
        df = self.ensure_exported()
        ap_set = self._detect_aps(df)
        if not ap_set:
            return []

        sa_col = _safe_col(df, "wlan.sa", "").str.strip().str.lower()
        retry_col = _bool_col(df, "wlan.fc.retry")
        rssi_col = _to_num(_safe_col(df, "radiotap.dbm_antsignal", ""))
        bssid_col = _safe_col(df, "wlan.bssid", "").str.strip().str.lower()
        ssid_col = _safe_col(df, "wlan.ssid", "")
        ch_col = _to_num(_safe_col(df, "wlan_radio.channel", ""))
        fc_type = _to_num(_safe_col(df, "wlan.fc.type", "0"))
        fc_sub = _to_num(_safe_col(df, "wlan.fc.subtype", "0"))
        beacon_mask = (fc_type == 0) & (fc_sub == 8)

        result = []
        for bssid in ap_set:
            mask = bssid_col == bssid
            total = int(mask.sum())
            if total == 0:
                continue
            retries = int(retry_col[mask].sum())
            retry_pct = round(retries / total * 100, 2)
            rssi_vals = rssi_col[mask].dropna()
            avg_rssi = round(float(rssi_vals.mean()), 1) if len(rssi_vals) > 0 else None
            ssids = ssid_col[mask][ssid_col[mask].ne("")].unique()
            ssid = ssids[0] if len(ssids) > 0 else ""
            ch_vals = ch_col[mask].dropna()
            channel = int(ch_vals.mode().iloc[0]) if len(ch_vals) > 0 else 0
            beacons = int(beacon_mask[mask].sum())
            clients = set(sa_col[mask & (sa_col.ne(bssid)) & (~sa_col.isin(BROADCAST))])
            client_count = len(clients)

            status = "critical" if retry_pct > 20 else "warning" if retry_pct > 10 else "healthy"
            result.append({
                "bssid": bssid,
                "ssid": ssid,
                "channel": channel,
                "client_count": client_count,
                "avg_retry_pct": retry_pct,
                "avg_rssi": avg_rssi,
                "beacon_count": beacons,
                "status": status,
            })

        return result

    def get_client_detail(self, mac: str) -> dict:
        df = self.ensure_exported()
        mac = mac.strip().lower()
        sa_col = _safe_col(df, "wlan.sa", "").str.strip().str.lower()
        mask = sa_col == mac
        if not mask.any():
            return {"error": "Client not found"}

        sub = df[mask].copy()
        epoch_col = _to_num(sub["frame.time_epoch"])
        rssi_col = _to_num(_safe_col(sub, "radiotap.dbm_antsignal", ""))
        retry_col = _bool_col(sub, "wlan.fc.retry")
        bssid_col = _safe_col(sub, "wlan.bssid", "").str.strip().str.lower()
        ssid_col = _safe_col(sub, "wlan.ssid", "")
        fc_type = _to_num(_safe_col(sub, "wlan.fc.type", "0"))
        fc_sub = _to_num(_safe_col(sub, "wlan.fc.subtype", "0"))
        pwrmgt_col = _bool_col(sub, "wlan.fc.pwrmgt")
        seq_col = _to_num(_safe_col(sub, "wlan.seq", ""))
        status_col = _safe_col(sub, "wlan.fixed.status_code", "")
        reason_col = _to_num(_safe_col(sub, "wlan.fixed.reason_code", ""))
        eapol_col = _safe_col(sub, "wlan_rsna_eapol.keydes.msgnr", "")

        sub = sub.dropna(subset=["frame.time_epoch"])
        if sub.empty:
            return {"error": "No valid timestamps"}

        sub["epoch"] = _to_num(sub["frame.time_epoch"])
        sub = sub.sort_values("epoch")

        rssi_timeline = _downsample([
            {"epoch": round(float(r["epoch"]), 3), "rssi": float(rssi_col.loc[idx])}
            for idx, r in sub.iterrows() if idx in rssi_col.index and pd.notna(rssi_col.loc[idx]) and -120 <= rssi_col.loc[idx] <= 0
        ])

        window = max(1, len(sub) // 50)
        retry_rolling = retry_col.rolling(window, min_periods=1).mean() * 100
        retry_timeline = _downsample([
            {"epoch": round(float(sub.loc[idx, "epoch"]), 3), "retry_pct": round(float(retry_rolling.loc[idx]), 2)}
            for idx in sub.index
        ])

        frame_type_dist = {
            "mgmt": int((fc_type == 0).sum()),
            "ctrl": int((fc_type == 1).sum()),
            "data": int((fc_type == 2).sum()),
        }

        events = []
        for idx, row in sub.iterrows():
            ft = fc_type.loc[idx] if idx in fc_type.index else 0
            fs = fc_sub.loc[idx] if idx in fc_sub.index else 0
            ep = row.get("epoch", 0)
            if ft == 0 and fs == 11:
                events.append({"epoch": ep, "event_type": "auth", "peer": "", "direction": "", "status_code": status_col.loc[idx] if idx in status_col.index else "", "reason_desc": "", "desc": "Authentication"})
            elif ft == 0 and fs in (0, 1):
                sc = status_col.loc[idx] if idx in status_col.index else ""
                sc_int = int(sc, 0) if sc and sc.startswith("0x") else (int(sc) if sc else None)
                events.append({"epoch": ep, "event_type": "assoc", "peer": "", "direction": "", "status_code": sc, "reason_desc": "", "desc": _sc_str(sc_int)})
            elif ft == 0 and fs == 12:
                ri = reason_col.loc[idx] if idx in reason_col.index else None
                events.append({"epoch": ep, "event_type": "deauth", "peer": "", "direction": "", "status_code": "", "reason_desc": _reason_desc(int(ri) if pd.notna(ri) else None), "desc": "Deauth"})
            elif ft == 0 and fs == 10:
                ri = reason_col.loc[idx] if idx in reason_col.index else None
                events.append({"epoch": ep, "event_type": "disassoc", "peer": "", "direction": "", "status_code": "", "reason_desc": _reason_desc(int(ri) if pd.notna(ri) else None), "desc": "Disassoc"})
            elif eapol_col.loc[idx] if idx in eapol_col.index else "":
                events.append({"epoch": ep, "event_type": "eapol", "peer": "", "direction": "", "status_code": "", "reason_desc": "", "desc": f"EAPOL msg {eapol_col.loc[idx]}"})

        ap_convos = []
        for bssid, grp in sub.groupby(bssid_col):
            if not bssid or bssid in BROADCAST:
                continue
            first = grp["epoch"].min()
            last = grp["epoch"].max()
            cnt = len(grp)
            rv = rssi_col[grp.index].dropna()
            avg_r = round(float(rv.mean()), 1) if len(rv) > 0 else None
            ssids = ssid_col[grp.index][ssid_col[grp.index].ne("")].unique()
            ssid = ssids[0] if len(ssids) > 0 else ""
            ap_convos.append({"bssid": bssid, "ssid": ssid, "first_seen": first, "last_seen": last, "frame_count": cnt, "avg_rssi": avg_r})

        roaming = []
        bssid_seq = bssid_col[sub.index].tolist()
        prev = None
        for i, b in enumerate(bssid_seq):
            if b and b not in BROADCAST and b != prev:
                if prev:
                    roaming.append({"epoch": float(sub["epoch"].iloc[i]), "from_bssid": prev, "to_bssid": b})
                prev = b

        eapol_handshakes = []
        eapol_mask = eapol_col.ne("")
        eapol_sub = sub[eapol_mask]
        for peer, grp in eapol_sub.groupby(bssid_col.loc[eapol_sub.index]):
            msgs = set(grp["wlan_rsna_eapol.keydes.msgnr"].astype(str).str.strip())
            eapol_handshakes.append({"peer": peer, "steps_seen": sorted(msgs), "complete": "4" in msgs, "start_epoch": float(grp["epoch"].min())})

        power_mgmt_timeline = _downsample([
            {"epoch": round(float(r["epoch"]), 3), "state": int(pwrmgt_col.loc[idx]) if idx in pwrmgt_col.index else 0}
            for idx, r in sub.iterrows()
        ])

        seq_vals = seq_col[sub.index].dropna()
        seq_timeline = _downsample([
            {"epoch": round(float(sub.loc[idx, "epoch"]), 3), "seq_num": int(seq_vals.loc[idx])}
            for idx in seq_vals.index
        ]) if len(seq_vals) > 0 else []

        seq_gaps = []
        duplicate_frames = 0
        if len(seq_vals) > 1:
            s = seq_vals.sort_values().values
            idxs = seq_vals.sort_values().index.tolist()
            for i in range(1, len(s)):
                d = (int(s[i]) - int(s[i - 1])) % 4096
                if d > 1 and d < 4090:
                    seq_gaps.append({"epoch": float(sub.loc[idxs[i], "epoch"]), "expected_seq": int(s[i - 1]) + 1, "actual_seq": int(s[i]), "gap_size": d})
                if retry_col.loc[idxs[i]] == 1 and int(s[i]) == int(s[i - 1]):
                    duplicate_frames += 1

        retry_vs_power = _downsample([
            {"epoch": round(float(r["epoch"]), 3), "retry": int(retry_col.loc[idx]) if idx in retry_col.index else 0, "pwrmgt": int(pwrmgt_col.loc[idx]) if idx in pwrmgt_col.index else 0}
            for idx, r in sub.iterrows()
        ])

        return {
            "rssi_timeline": rssi_timeline,
            "retry_timeline": retry_timeline,
            "frame_type_dist": frame_type_dist,
            "events": events[:100],
            "ap_conversations": ap_convos,
            "roaming": roaming,
            "eapol_handshakes": eapol_handshakes,
            "power_mgmt_timeline": power_mgmt_timeline,
            "sequence_analysis": {"seq_timeline": seq_timeline, "seq_gaps": seq_gaps, "duplicate_frames": duplicate_frames},
            "retry_vs_power": retry_vs_power,
        }

    def get_ap_detail(self, bssid: str) -> dict:
        df = self.ensure_exported()
        bssid = bssid.strip().lower()
        bssid_col = _safe_col(df, "wlan.bssid", "").str.strip().str.lower()
        mask = bssid_col == bssid
        if not mask.any():
            return {"error": "AP not found"}

        sa_col = _safe_col(df, "wlan.sa", "").str.strip().str.lower()
        da_col = _safe_col(df, "wlan.da", "").str.strip().str.lower()
        clients = (set(sa_col[mask]) | set(da_col[mask])) - BROADCAST - {bssid, ""}

        rssi_col = _to_num(_safe_col(df, "radiotap.dbm_antsignal", ""))
        retry_col = _bool_col(df, "wlan.fc.retry")
        ch_col = _to_num(_safe_col(df, "wlan_radio.channel", ""))
        epoch_col = _to_num(df["frame.time_epoch"])

        client_metrics = []
        rssi_distribution = []
        for mac in clients:
            cmask = mask & (sa_col == mac)
            cnt = int(cmask.sum())
            if cnt == 0:
                continue
            rv = rssi_col[cmask].dropna()
            avg_r = round(float(rv.mean()), 1) if len(rv) > 0 else None
            retries = int(retry_col[cmask].sum())
            rp = round(retries / cnt * 100, 2)
            ep = epoch_col[cmask].dropna()
            first = float(ep.min()) if len(ep) > 0 else None
            last = float(ep.max()) if len(ep) > 0 else None
            client_metrics.append({"mac": mac, "avg_rssi": avg_r, "retry_pct": rp, "frame_count": cnt, "first_seen": first, "last_seen": last})
            if len(rv) >= 1:
                q = rv.quantile([0, 0.25, 0.5, 0.75, 1])
                rssi_distribution.append({
                    "mac": mac,
                    "min": float(q.iloc[0]),
                    "q1": float(q.iloc[1]),
                    "median": float(q.iloc[2]),
                    "q3": float(q.iloc[3]),
                    "max": float(q.iloc[4]),
                })

        ch_vals = ch_col[mask].dropna()
        channel = int(ch_vals.mode().iloc[0]) if len(ch_vals) > 0 else 0
        phy_vals = _to_num(_safe_col(df, "wlan_radio.phy", ""))[mask].dropna()
        phy_modes = list(set(PHY_NAMES.get(int(p), f"Unknown({p})") for p in phy_vals.unique()))

        return {
            "client_metrics": client_metrics,
            "rssi_distribution": rssi_distribution,
            "client_timeline": [],
            "channel_info": {"channel": channel, "frequency": 0, "phy_modes": phy_modes},
        }

    def get_1905_overview(self) -> dict:
        df = self.ensure_exported()
        al_col = _safe_col(df, "ieee1905.1905_al_mac_addr", "")
        msg_col = _safe_col(df, "ieee1905.message_type", "")
        has_1905 = msg_col.str.strip().ne("")
        df1905 = df[has_1905].copy()
        if df1905.empty:
            return {
                "has_1905": False,
                "devices": [],
                "message_distribution": {},
                "category_distribution": {},
                "per_device_categories": {},
                "unanswered_queries": [],
                "timeline": [],
            }

        eth_src = _safe_col(df1905, "eth.src", "").str.strip().str.lower()
        eth_dst = _safe_col(df1905, "eth.dst", "").str.strip().str.lower()
        msg_id_col = _safe_col(df1905, "ieee1905.message_id", "")
        epoch_col = _to_num(df1905["frame.time_epoch"])

        devices = []
        for al in al_col[al_col.ne("")].unique():
            amask = al_col == al
            devices.append({
                "al_mac": al,
                "eth_src": eth_src[amask].iloc[0] if amask.any() else "",
                "message_count": int(amask.sum()),
                "last_seen": float(epoch_col[amask].max()) if amask.any() else None,
            })

        msg_dist = {}
        cat_dist = {}
        for _, row in df1905.iterrows():
            m = row.get("ieee1905.message_type", "")
            try:
                mi = int(m, 0) if m else 0
                name = MSG_1905_TYPES.get(mi, f"Unknown(0x{mi:X})")
                msg_dist[name] = msg_dist.get(name, 0) + 1
                cat = MSG_CATEGORY.get(mi, "Other")
                cat_dist[cat] = cat_dist.get(cat, 0) + 1
            except (ValueError, TypeError):
                pass

        unanswered = []
        for idx, row in df1905.iterrows():
            m = row.get("ieee1905.message_type", "")
            mid = row.get("ieee1905.message_id", "")
            try:
                mi = int(m, 0) if m else 0
                if mi in _REQUEST_RESPONSE_PAIRS:
                    resp_type = _REQUEST_RESPONSE_PAIRS[mi]
                    resp_str = f"0x{resp_type:04x}".lower()
                    resp_mask = (msg_col.astype(str).str.strip().str.lower() == resp_str) & (msg_id_col == mid)
                    if not resp_mask.any():
                        unanswered.append({"query_type": MSG_1905_TYPES.get(mi, str(mi)), "query_id": mid, "sender": eth_src.loc[idx], "epoch": float(epoch_col.loc[idx])})
            except (ValueError, TypeError):
                pass

        timeline = _downsample([
            {
                "epoch": float(epoch_col.loc[idx]),
                "message_type": MSG_1905_TYPES.get(int(row.get("ieee1905.message_type", "0"), 0), "Unknown"),
                "src": eth_src.loc[idx],
                "dst": eth_dst.loc[idx],
                "message_id": msg_id_col.loc[idx],
            }
            for idx, row in df1905.iterrows()
        ])

        per_dev_cat: dict[str, dict[str, int]] = {}
        for al in al_col[al_col.ne("")].unique():
            amask = al_col.loc[df1905.index] == al
            for m in msg_col.loc[df1905.index][amask]:
                try:
                    mi = int(m, 0) if m else 0
                    cat = MSG_CATEGORY.get(mi, "Other")
                    per_dev_cat.setdefault(al, {})[cat] = per_dev_cat.get(al, {}).get(cat, 0) + 1
                except (ValueError, TypeError):
                    pass

        return {
            "has_1905": True,
            "devices": devices,
            "message_distribution": msg_dist,
            "category_distribution": cat_dist,
            "per_device_categories": per_dev_cat,
            "unanswered_queries": unanswered,
            "timeline": timeline,
        }

    def get_1905_conversation(
        self,
        al_mac: Optional[str] = None,
        src_mac: Optional[str] = None,
        dst_mac: Optional[str] = None,
        exclude_periodic: bool = False,
    ) -> dict:
        df = self.ensure_exported()
        has_1905 = _safe_col(df, "ieee1905.message_type", "").str.strip().ne("")
        df1905 = df[has_1905].copy()
        _empty = {"has_1905": False, "devices": [], "message_distribution": {}, "category_distribution": {}, "per_device_categories": {}, "unanswered_queries": [], "timeline": []}
        if df1905.empty:
            return _empty

        al_col = _safe_col(df1905, "ieee1905.1905_al_mac_addr", "")
        eth_src = _safe_col(df1905, "eth.src", "").str.strip().str.lower()
        eth_dst = _safe_col(df1905, "eth.dst", "").str.strip().str.lower()
        msg_col = _safe_col(df1905, "ieee1905.message_type", "")
        msg_id_col = _safe_col(df1905, "ieee1905.message_id", "")
        epoch_col = _to_num(df1905["frame.time_epoch"])

        mask = pd.Series(True, index=df1905.index)
        if al_mac:
            mask &= (al_col == al_mac.strip().lower())
        if src_mac:
            mask &= (eth_src == src_mac.strip().lower())
        if dst_mac:
            mask &= (eth_dst == dst_mac.strip().lower())
        if exclude_periodic:
            for idx in df1905.index:
                m = msg_col.loc[idx]
                try:
                    mi = int(m, 0) if m else 0
                    if mi in PERIODIC_MSG_TYPES:
                        mask.loc[idx] = False
                except (ValueError, TypeError):
                    pass

        filtered = df1905[mask]
        if filtered.empty:
            return _empty

        al_f = al_col[mask]
        msg_f = msg_col[mask]
        msg_id_f = msg_id_col[mask]
        eth_src_f = eth_src[mask]
        eth_dst_f = eth_dst[mask]
        epoch_f = epoch_col[mask]

        devices = []
        for al in al_f[al_f.ne("")].unique():
            amask = al_f == al
            devices.append({
                "al_mac": al,
                "eth_src": eth_src_f[amask].iloc[0] if amask.any() else "",
                "message_count": int(amask.sum()),
                "last_seen": float(epoch_f[amask].max()) if amask.any() else None,
            })

        msg_dist = {}
        cat_dist = {}
        for m in msg_f:
            try:
                mi = int(m, 0) if m else 0
                name = MSG_1905_TYPES.get(mi, f"Unknown(0x{mi:X})")
                msg_dist[name] = msg_dist.get(name, 0) + 1
                cat = MSG_CATEGORY.get(mi, "Other")
                cat_dist[cat] = cat_dist.get(cat, 0) + 1
            except (ValueError, TypeError):
                pass

        unanswered = []
        for idx in filtered.index:
            m = msg_f.loc[idx] if idx in msg_f.index else ""
            mid = msg_id_f.loc[idx] if idx in msg_id_f.index else ""
            try:
                mi = int(m, 0) if m else 0
                if mi in _REQUEST_RESPONSE_PAIRS:
                    resp_type = _REQUEST_RESPONSE_PAIRS[mi]
                    resp_str = f"0x{resp_type:04x}".lower()
                    resp_mask = (msg_f == resp_str) & (msg_id_f == mid)
                    if not resp_mask.any():
                        unanswered.append({"query_type": MSG_1905_TYPES.get(mi, str(mi)), "query_id": mid, "sender": eth_src_f.loc[idx], "epoch": float(epoch_f.loc[idx])})
            except (ValueError, TypeError):
                pass

        timeline = _downsample([
            {
                "epoch": float(epoch_f.loc[idx]),
                "message_type": MSG_1905_TYPES.get(int(msg_f.loc[idx], 0) if msg_f.loc[idx] else 0, "Unknown"),
                "src": eth_src_f.loc[idx],
                "dst": eth_dst_f.loc[idx],
                "message_id": msg_id_f.loc[idx],
            }
            for idx in filtered.index
        ])

        per_dev_cat = {}
        for al in al_f[al_f.ne("")].unique():
            amask = al_f == al
            for m in msg_f[amask]:
                try:
                    mi = int(m, 0) if m else 0
                    cat = MSG_CATEGORY.get(mi, "Other")
                    if al not in per_dev_cat:
                        per_dev_cat[al] = {}
                    per_dev_cat[al][cat] = per_dev_cat[al].get(cat, 0) + 1
                except (ValueError, TypeError):
                    pass

        return {
            "has_1905": True,
            "devices": devices,
            "message_distribution": msg_dist,
            "category_distribution": cat_dist,
            "per_device_categories": per_dev_cat,
            "unanswered_queries": unanswered,
            "timeline": timeline,
        }


# ── Module-level helpers ─────────────────────────────────────────────────────

def _ep(s: str) -> Optional[int]:
    try:
        return int(s, 0) if s and str(s).strip() else None
    except (ValueError, TypeError):
        return None


def _sc_str(status: Optional[int]) -> str:
    if status is None:
        return "Unknown"
    return ASSOC_STATUS_CODES.get(status, f"Unknown ({status})")
