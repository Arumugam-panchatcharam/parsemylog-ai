"""
Reboot Root-Cause LLM Summary Builder
======================================

Assembles structured, LLM-ready evidence for reboot root-cause analysis
across batch-processed CPE log sets.  Produces two artifacts:

- ``reboot_summary_per_cpe.jsonl``  -- one JSON line per CPE
- ``fleet_reboot_summary.json``     -- fleet-wide aggregate

The module reuses existing parsers and never re-invents parsing logic:

- :mod:`logai.info_extractor`  -- reboot events from BootTime/PARODUS
- :mod:`logai.telemetry_parser` -- telemetry context (T2 > dcmscript > marker)
- ``*_rg.parquet`` files        -- domain pattern matches from Drain3
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from logai.info_extractor import (
    find_and_extract_reboots,
    find_and_parse_version_txt,
    find_and_build_fallback_device_info,
)
from logai.telemetry_parser import parse_telemetry_file

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Evidence category definitions
# ---------------------------------------------------------------------------

EVIDENCE_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "wifi_driver_errors": {
        "domains": ["wireless", "platform", "common"],
        "keywords": [
            r"dhd_prot_ioctl", r"STA\s+INFO\s+failed", r"status\s+ret\s+value",
            r"driver\s+(crash|recovery|reset|stuck|hang)",
            r"radio\s+(reset|restart|down|fail)",
            r"VAP\s+(down|fail|destroy)",
            r"unexpected\s+fatal\s+signal\s+11",
        ],
    },
    "wifi_disconnect_storm": {
        "domains": ["wireless"],
        "keywords": [
            r"\bdisassoc", r"\bdeauth", r"disconnected\s+event",
            r"STA\s+(left|removed|kicked|rejected)",
            r"wifi_hal_cb_assoc_dev_evt_handler",
            r"invoke\s+disassoc\s+callback",
        ],
    },
    "dfs_cac_events": {
        "domains": ["wireless"],
        "keywords": [
            r"\bDFS\b", r"\bradar\b", r"\bCAC\b",
            r"channel\s+(switch|change|dfs)",
        ],
    },
    "btm_steering": {
        "domains": ["wireless", "mesh"],
        "keywords": [
            r"\bBTM\b", r"BSS\s+transition", r"\b11v\b",
            r"steer(ing)?\s+(fail|reject|timeout|abort)",
            r"band\s*steering",
        ],
    },
    "wan_disconnections": {
        "domains": ["core_router"],
        "keywords": [
            r"PPP.*(down|fail|terminated)",
            r"DSL\s*(retrain|sync.?loss|down|drop)",
            r"GPON\s*(deactivat|alarm|down)",
            r"WAN\s*(down|lost|disconnect|fail|flap)",
            r"IPv[46]\s*(unreachable|lost|timeout)",
            r"CONNECTION_LOST",
        ],
    },
    "memory_crisis": {
        "domains": ["platform", "common"],
        "keywords": [
            r"Out\s+of\s+memory", r"\bOOM\b", r"\boom\b",
            r"memory\s*(leak|exhausted|low)",
        ],
    },
    "kernel_crash": {
        "domains": ["platform", "common"],
        "keywords": [
            r"kernel\s+panic", r"\boops\b", r"\bBUG\b",
            r"Segmentation\s+fault", r"unexpected\s+fatal\s+signal\s+11",
            r"\bwatchdog\b", r"hung_task", r"soft\s+lockup",
            r"(process|daemon|service)\s+(crash|exit|kill|died|terminated)",
            r"SSP\s+(restart|crash|exit)",
            r"core\s+dump",
        ],
    },
    "ccsp_bus_failures": {
        "domains": ["core_router", "platform", "common"],
        "keywords": [
            r"CCSP_ERR", r"CCSP_CRASH",
            r"ccsp\s*(error|fail|crash|timeout)",
            r"0x232D", r"GetParameterValues.*fail",
            r"PSM\s*(error|fail)",
        ],
    },
    "mesh_backhaul": {
        "domains": ["mesh"],
        "keywords": [
            r"backhaul\s+(down|fail|lost|disconnect|degrade)",
            r"(agent|controller)\s+(disconnect|fail|lost|crash)",
            r"(satellite|extender|pod)\s+(disconnect|lost|offline)",
            r"(1905|ieee1905)\s+(fail|error|timeout)",
            r"topology\s+(change|lost|unstable)",
        ],
    },
    "cellular_failover": {
        "domains": ["cellular"],
        "keywords": [
            r"\bfailover\b", r"\bfallback\b", r"\bswitchover\b",
            r"no\s+signal", r"signal\s+lost",
            r"SIM\s+(error|fail)", r"modem\s+(reset|crash|stuck)",
        ],
    },
    "cpu_thermal": {
        "domains": ["platform", "common"],
        "keywords": [
            r"(cpu|load)\s+(high|spike|100|stuck)",
        ],
    },
    "firmware_upgrade": {
        "domains": ["platform", "core_router", "telemetry"],
        "keywords": [
            r"(firmware|upgrade|update)\s+(fail|error|abort|corrupt)",
            r"download\s+(fail|timeout)",
        ],
    },
    "selfheal_actions": {
        "domains": ["platform", "common"],
        "keywords": [
            r"\bselfheal\b",
        ],
    },
}

_COMPILED_CATS: Dict[str, List[re.Pattern]] = {}
for _cat, _cfg in EVIDENCE_CATEGORIES.items():
    _COMPILED_CATS[_cat] = [re.compile(kw, re.IGNORECASE) for kw in _cfg["keywords"]]

# Mapping from domain file names to category sets for faster lookup
_DOMAIN_TO_CATS: Dict[str, List[str]] = defaultdict(list)
for _cat, _cfg in EVIDENCE_CATEGORIES.items():
    for _dom in _cfg["domains"]:
        _DOMAIN_TO_CATS[_dom].append(_cat)

# Chain-of-failure templates (ordered sequences to look for)
FAILURE_CHAINS = [
    {
        "name": "wifi_cascade",
        "sequence": ["wifi_driver_errors", "wifi_disconnect_storm", "wan_disconnections", "kernel_crash"],
    },
    {
        "name": "memory_cascade",
        "sequence": ["memory_crisis", "kernel_crash"],
    },
    {
        "name": "wan_cascade",
        "sequence": ["wan_disconnections", "ccsp_bus_failures", "kernel_crash"],
    },
    {
        "name": "dfs_disconnect_cascade",
        "sequence": ["dfs_cac_events", "wifi_disconnect_storm"],
    },
    {
        "name": "btm_disconnect_cascade",
        "sequence": ["btm_steering", "wifi_disconnect_storm"],
    },
]

# Telemetry field keys to extract from parsed report fields dicts
_SYSTEM_FIELDS = {
    "CPUUsage", "Device.DeviceInfo.ProcessStatus.CPUUsage",
    "DeviceUpTime", "Device.DeviceInfo.UpTime",
    "MemInfoFree", "Device.DeviceInfo.MemoryStatus.Free",
    "MemInfoTotal", "Device.DeviceInfo.MemoryStatus.Total",
    "meminfoavailable_split",
    "shmem_split", "slab_memory_split",
    "cpu_temp_split",
    "flash_usage_nvram_free_split", "flash_usage_nvram_total_split",
    "last_reboot_reason_split", "Device.DeviceInfo.X_RDKCENTRAL-COM_LastRebootReason",
}

_GPON_WAN_FIELDS = {
    "gpon_connectionStatus", "gpon_rxSignalLevel", "gpon_txSignalLevel",
    "gpon_signalDegrade", "gpon_signalFail", "gpon_framesLost",
    "gpon_downstreamSpeed", "gpon_upstreamSpeed",
    "wanoe_connectionStatus", "wanoe_lastConnError",
    "wanoe_downstreamSpeed", "wanoe_upstreamSpeed",
    "ppp_interface_1_status",
    "wan_errorsReceived", "wan_errorsSent",
    "wan_access_mode_split",
}

_WIFI_FIELDS = {
    "wifi_radio_1_channel", "wifi_radio_2_channel",
    "wifi_radio_1_operatingfrequencyband", "wifi_radio_2_operatingfrequencyband",
    "wifi_radio_1_stats_noise", "wifi_radio_2_stats_noise",
    "wifi_radio_1_transmitpower", "wifi_radio_2_transmitpower",
    "wifi_radio_1_status", "wifi_radio_2_status",
    "wifi_x_rdkcentralcom_bandsteering_enable",
    "wifi_x_rdkcentralcom_bandsteering_bandsetting_1_rssithreshold",
    "wifi_x_rdkcentralcom_bandsteering_bandsetting_2_rssithreshold",
    "wifi_x_rdkcentralcom_bandsteering_bandsetting_1_utilizationthreshold",
    "wifi_x_rdkcentralcom_bandsteering_bandsetting_2_utilizationthreshold",
    "hosts_connected_device_number", "Device.Hosts.X_CISCO_COM_ConnectedDeviceNumber",
}

_ALL_TELEMETRY_KEYS = _SYSTEM_FIELDS | _GPON_WAN_FIELDS | _WIFI_FIELDS

OUTPUT_DIR_NAME = "llm_reboot_summary"
PER_CPE_FILE = "reboot_summary_per_cpe.jsonl"
FLEET_FILE = "fleet_reboot_summary.json"


# ---------------------------------------------------------------------------
# Per-CPE evidence extraction
# ---------------------------------------------------------------------------

def _classify_parquet_lines(cpe_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Read all ``*_rg.parquet`` files and classify lines into evidence categories."""
    evidence: Dict[str, Dict[str, Any]] = {}
    for cat in EVIDENCE_CATEGORIES:
        evidence[cat] = {
            "count": 0,
            "sample_lines": [],
            "first_ts": None,
            "last_ts": None,
            "timestamps": [],
        }

    for pq_path in sorted(cpe_dir.glob("*_rg.parquet")):
        domain = pq_path.stem.replace("_rg", "")
        cats_for_domain = _DOMAIN_TO_CATS.get(domain, [])
        if not cats_for_domain:
            continue

        try:
            df = pd.read_parquet(pq_path)
        except Exception as exc:
            logger.warning(f"Could not read {pq_path}: {exc}")
            continue

        if df.empty:
            continue

        logline_col = "loglines" if "loglines" in df.columns else None
        template_col = "template" if "template" in df.columns else None
        ts_col = "timestamp" if "timestamp" in df.columns else None

        if not logline_col:
            continue

        for _, row in df.iterrows():
            text = str(row.get(logline_col, ""))
            tmpl = str(row.get(template_col, "")) if template_col else text
            ts = str(row.get(ts_col, "")) if ts_col else ""
            combined = f"{text} {tmpl}"

            for cat in cats_for_domain:
                for pat in _COMPILED_CATS[cat]:
                    if pat.search(combined):
                        ev = evidence[cat]
                        ev["count"] += 1
                        if ts:
                            ev["timestamps"].append(ts)
                        if len(ev["sample_lines"]) < 3:
                            ev["sample_lines"].append(text[:300])
                        break  # one category match per line is enough

    # Post-process: first/last ts, rate
    for cat, ev in evidence.items():
        tss = sorted(ev.pop("timestamps"))
        if tss:
            ev["first_ts"] = tss[0]
            ev["last_ts"] = tss[-1]

    return evidence


def _detect_disconnect_storm(evidence: Dict[str, Dict[str, Any]], cpe_dir: Path) -> Dict[str, Any]:
    """Analyse wireless parquet for disconnect storm (>8 disassoc/min sustained)."""
    storm_info: Dict[str, Any] = {"detected": False, "peak_rate_per_min": 0, "sustained": False}
    pq = cpe_dir / "wireless_rg.parquet"
    if not pq.exists():
        return storm_info

    try:
        df = pd.read_parquet(pq)
    except Exception:
        return storm_info

    if df.empty or "timestamp" not in df.columns or "loglines" not in df.columns:
        return storm_info

    disassoc_re = re.compile(
        r"disassoc|deauth|disconnected\s+event|STA\s+(left|removed|kicked)", re.IGNORECASE
    )

    ts_list: List[datetime] = []
    for _, row in df.iterrows():
        text = str(row.get("loglines", ""))
        if not disassoc_re.search(text):
            continue
        ts_str = str(row.get("timestamp", ""))
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                ts_list.append(datetime.strptime(ts_str[:19], fmt))
                break
            except ValueError:
                continue

    if len(ts_list) < 2:
        return storm_info

    ts_list.sort()

    # Sliding 1-minute window
    max_rate = 0
    sustained_minutes = 0
    i = 0
    for j in range(len(ts_list)):
        while ts_list[j] - ts_list[i] > timedelta(minutes=1):
            i += 1
        window_count = j - i + 1
        if window_count > max_rate:
            max_rate = window_count
        if window_count > 8:
            sustained_minutes += 1

    storm_info["peak_rate_per_min"] = max_rate
    storm_info["detected"] = max_rate > 8
    storm_info["sustained"] = sustained_minutes >= 3

    return storm_info


def _collect_telemetry_context(
    cpe_dir: Path,
) -> Tuple[Dict[str, Any], str]:
    """
    Collect telemetry context using the priority chain:
    telemetry2_0.txt -> dcmscript.log -> PARODUS/marker/version fallback.

    Returns (context_dict, source_name).
    """
    t2_path = cpe_dir / "telemetry2_0.txt"
    dcm_path = cpe_dir / "dcmscript.log"

    reports, merged, summary = parse_telemetry_file(t2_path, dcmscript_path=dcm_path)

    if not reports:
        return _build_marker_fallback_context(cpe_dir), "parodus_marker_fallback"

    # Determine source
    source = "telemetry2_0"
    if reports and reports[0].get("profile") == "dcmscript":
        source = "dcmscript"

    context: Dict[str, Any] = {
        "report_count": len(reports),
        "cpu_usage": [],
        "memory_free": [],
        "memory_total": [],
        "memory_pct": [],
        "uptime": [],
        "temperature": [],
        "gpon": {},
        "wan": {},
        "wifi": {},
        "band_steering": {},
        "connected_devices": [],
    }

    for r in reports:
        fields = r.get("fields", {})
        ts = r.get("time")
        ts_str = ts.isoformat() if ts else r.get("log_timestamp", "")

        # CPU
        cpu_raw = fields.get("Device.DeviceInfo.ProcessStatus.CPUUsage",
                             fields.get("CPUUsage"))
        if cpu_raw is not None:
            try:
                context["cpu_usage"].append({"ts": ts_str, "value": int(cpu_raw)})
            except (ValueError, TypeError):
                pass

        # Memory
        mem_free_raw = fields.get("Device.DeviceInfo.MemoryStatus.Free",
                                  fields.get("MemInfoFree"))
        mem_total_raw = fields.get("Device.DeviceInfo.MemoryStatus.Total",
                                   fields.get("MemInfoTotal"))
        if mem_free_raw is not None and mem_total_raw is not None:
            try:
                mf, mt = int(mem_free_raw), int(mem_total_raw)
                if mt > 0:
                    pct = round((mt - mf) / mt * 100, 1)
                    context["memory_free"].append({"ts": ts_str, "value": mf})
                    context["memory_total"].append({"ts": ts_str, "value": mt})
                    context["memory_pct"].append({"ts": ts_str, "value": pct})
            except (ValueError, TypeError):
                pass

        # Uptime
        uptime_val = r.get("uptime", 0)
        if uptime_val:
            context["uptime"].append({"ts": ts_str, "value": uptime_val})

        # Temperature
        temp_raw = fields.get("cpu_temp_split")
        if temp_raw is not None:
            try:
                context["temperature"].append({"ts": ts_str, "value": float(temp_raw)})
            except (ValueError, TypeError):
                pass

        # Connected devices
        cd = fields.get("Device.Hosts.X_CISCO_COM_ConnectedDeviceNumber",
                        fields.get("hosts_connected_device_number"))
        if cd is not None:
            try:
                context["connected_devices"].append({"ts": ts_str, "value": int(cd)})
            except (ValueError, TypeError):
                pass

    # Extract GPON/WAN from last report (snapshot)
    if reports:
        last_fields = reports[-1].get("fields", {})

        for gk in ("gpon_connectionStatus", "gpon_rxSignalLevel", "gpon_txSignalLevel",
                    "gpon_signalDegrade", "gpon_signalFail", "gpon_framesLost",
                    "gpon_downstreamSpeed", "gpon_upstreamSpeed"):
            v = last_fields.get(gk)
            if v is not None:
                context["gpon"][gk] = v

        for wk in ("wanoe_connectionStatus", "wanoe_lastConnError",
                    "wanoe_downstreamSpeed", "wanoe_upstreamSpeed",
                    "ppp_interface_1_status",
                    "wan_errorsReceived", "wan_errorsSent",
                    "wan_access_mode_split"):
            v = last_fields.get(wk)
            if v is not None:
                context["wan"][wk] = v

        for wfk in ("wifi_radio_1_channel", "wifi_radio_2_channel",
                     "wifi_radio_1_stats_noise", "wifi_radio_2_stats_noise",
                     "wifi_radio_1_transmitpower", "wifi_radio_2_transmitpower",
                     "wifi_radio_1_status", "wifi_radio_2_status"):
            v = last_fields.get(wfk)
            if v is not None:
                context["wifi"][wfk] = v

        for bk in ("wifi_x_rdkcentralcom_bandsteering_enable",
                    "wifi_x_rdkcentralcom_bandsteering_bandsetting_1_rssithreshold",
                    "wifi_x_rdkcentralcom_bandsteering_bandsetting_2_rssithreshold"):
            v = last_fields.get(bk)
            if v is not None:
                context["band_steering"][bk] = v

    return context, source


def _build_marker_fallback_context(cpe_dir: Path) -> Dict[str, Any]:
    """Minimal telemetry context from PARODUS/marker/version when T2 and dcmscript are absent."""
    ctx: Dict[str, Any] = {"report_count": 0}
    try:
        from logai.info_extractor import (
            parse_selfheal_txt,
            parse_telemetry_marker_extended,
        )
        marker_path = cpe_dir / "telemetry_marker.txt"
        selfheal_path = cpe_dir / "selfHeal.txt"

        if marker_path.exists():
            content = marker_path.read_text(encoding="utf-8", errors="replace")
            marker_info = parse_telemetry_marker_extended(content)
            ctx["marker"] = marker_info

        if selfheal_path.exists():
            content = selfheal_path.read_text(encoding="utf-8", errors="replace")
            sh_info = parse_selfheal_txt(content)
            ctx["selfheal"] = sh_info
    except Exception as exc:
        logger.warning(f"Marker fallback parsing error: {exc}")

    return ctx


def _compute_memory_trend(context: Dict[str, Any]) -> Dict[str, Any]:
    """Compute memory trend stats from telemetry context."""
    mem_pcts = context.get("memory_pct", [])
    if not mem_pcts:
        return {}

    values = [m["value"] for m in mem_pcts if isinstance(m.get("value"), (int, float))]
    if not values:
        return {}

    avg_pct = round(sum(values) / len(values), 1)
    peak_pct = round(max(values), 1)
    first_pct = values[0]
    last_pct = values[-1]

    trend = "stable"
    if last_pct - first_pct > 5:
        trend = "increasing"
    elif first_pct - last_pct > 5:
        trend = "decreasing"

    result: Dict[str, Any] = {
        "avg_pct": avg_pct,
        "peak_pct": peak_pct,
        "first_pct": first_pct,
        "last_pct": last_pct,
        "trend_direction": trend,
        "samples": len(values),
    }

    if trend == "increasing" and len(values) >= 3:
        # Estimate days to critical (98%) based on linear extrapolation
        rate_per_sample = (last_pct - first_pct) / max(len(values) - 1, 1)
        if rate_per_sample > 0:
            remaining = 98.0 - last_pct
            if remaining > 0:
                samples_to_critical = remaining / rate_per_sample
                # Approximate 15-min intervals (T2 or dcmscript)
                days_to_critical = round(samples_to_critical * 15 / 1440, 1)
                result["days_to_critical"] = days_to_critical

    return result


def _detect_uptime_resets(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Detect uptime drops to zero (reboots) from telemetry uptime time-series."""
    uptime_series = context.get("uptime", [])
    if len(uptime_series) < 2:
        return []

    resets = []
    prev = uptime_series[0]
    for cur in uptime_series[1:]:
        prev_val = prev.get("value", 0)
        cur_val = cur.get("value", 0)
        if isinstance(prev_val, (int, float)) and isinstance(cur_val, (int, float)):
            if cur_val < prev_val and prev_val > 300:
                resets.append({
                    "timestamp": cur.get("ts", ""),
                    "reason": "uptime_reset_detected",
                    "prev_uptime": prev_val,
                })
        prev = cur

    return resets


def _detect_failure_chains(
    evidence: Dict[str, Dict[str, Any]],
    reboots: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """Detect temporal failure chains based on evidence category presence."""
    chains: List[Dict[str, Any]] = []

    # Categories with events present
    active_cats = {cat for cat, ev in evidence.items() if ev.get("count", 0) > 0}

    for chain_def in FAILURE_CHAINS:
        seq = chain_def["sequence"]
        matched = [cat for cat in seq if cat in active_cats]
        if len(matched) >= 2:
            chains.append({
                "chain_name": chain_def["name"],
                "matched_categories": matched,
                "full_sequence": seq,
                "coverage": round(len(matched) / len(seq), 2),
            })

    return chains


def _determine_top_cause(
    evidence: Dict[str, Dict[str, Any]],
    chains: List[Dict[str, Any]],
    memory_trend: Dict[str, Any],
    reboots: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Determine the most likely root cause category with confidence."""
    if not reboots:
        return {"category": "no_reboots_detected", "confidence": 0, "rationale": "No reboot events found"}

    # Score categories by event count and chain involvement
    scores: Dict[str, float] = {}
    for cat, ev in evidence.items():
        if ev["count"] == 0:
            continue
        scores[cat] = ev["count"]

    # Boost categories that appear in chains
    for chain in chains:
        for cat in chain["matched_categories"]:
            if cat in scores:
                scores[cat] *= 1.5

    # Special handling for memory trend
    if memory_trend.get("peak_pct", 0) > 85:
        scores["memory_crisis"] = scores.get("memory_crisis", 0) + 50
    if memory_trend.get("peak_pct", 0) > 98:
        scores["memory_crisis"] = scores.get("memory_crisis", 0) + 100

    if not scores:
        return {"category": "unknown", "confidence": 0.1, "rationale": "Reboots detected but no matching evidence patterns"}

    top_cat = max(scores, key=scores.get)  # type: ignore[arg-type]
    total_score = sum(scores.values())
    confidence = round(scores[top_cat] / total_score, 2) if total_score > 0 else 0

    return {
        "category": top_cat,
        "confidence": confidence,
        "rationale": f"{evidence[top_cat]['count']} events in {top_cat}, "
                     f"{len(chains)} failure chain(s) detected",
    }


def _get_device_identity(cpe_dir: Path, serial: str) -> Dict[str, Any]:
    """Extract device identity info from version.txt and fallback sources."""
    identity: Dict[str, Any] = {"cpe_serial": serial}

    try:
        version_info = find_and_parse_version_txt(cpe_dir)
        if version_info:
            identity["firmware"] = version_info.get("imagename", "")
            identity["kernel_version"] = version_info.get("kernel_version", "")
            identity["model"] = version_info.get("model", "")
    except Exception:
        pass

    try:
        fallback = find_and_build_fallback_device_info(cpe_dir)
        if fallback:
            identity.setdefault("mac", fallback.get("mac", ""))
            identity.setdefault("model", fallback.get("model", ""))
    except Exception:
        pass

    return identity


def _compute_rate_per_hour(count: int, first_ts: Optional[str], last_ts: Optional[str]) -> float:
    """Compute event rate per hour from first/last timestamps."""
    if count == 0 or not first_ts or not last_ts:
        return 0.0
    try:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                t1 = datetime.strptime(first_ts[:19], fmt)
                t2 = datetime.strptime(last_ts[:19], fmt)
                break
            except ValueError:
                continue
        else:
            return 0.0
        delta_hours = max((t2 - t1).total_seconds() / 3600, 0.01)
        return round(count / delta_hours, 2)
    except Exception:
        return 0.0


def build_per_cpe_summary(
    cpe_dir: Path,
    serial: str,
    project_id: str = "",
    job_id: str = "",
) -> Dict[str, Any]:
    """
    Build a single CPE's reboot evidence summary.

    Args:
        cpe_dir: Path to the CPE directory (contains merged logs, parquets).
        serial: CPE serial number.
        project_id: Parent project ID.
        job_id: Batch job ID.

    Returns:
        Dict suitable for writing as a single JSONL line.
    """
    identity = _get_device_identity(cpe_dir, serial)
    identity["project_id"] = project_id
    identity["job_id"] = job_id

    # Reboot events
    reboots = find_and_extract_reboots(cpe_dir)

    # Evidence from parquets
    evidence = _classify_parquet_lines(cpe_dir)

    # Add rate_per_hour to each category
    for cat, ev in evidence.items():
        ev["rate_per_hour"] = _compute_rate_per_hour(
            ev["count"], ev.get("first_ts"), ev.get("last_ts")
        )

    # Disconnect storm analysis
    storm = _detect_disconnect_storm(evidence, cpe_dir)
    evidence["wifi_disconnect_storm"]["peak_rate_per_min"] = storm["peak_rate_per_min"]
    evidence["wifi_disconnect_storm"]["sustained_storm"] = storm["sustained"]

    # Telemetry context
    telemetry_context, telemetry_source = _collect_telemetry_context(cpe_dir)

    # Memory trend
    memory_trend = _compute_memory_trend(telemetry_context)

    # Uptime-based reboot detection
    uptime_reboots = _detect_uptime_resets(telemetry_context)

    # Merge uptime-detected reboots with log-based reboots
    all_reboots = list(reboots)
    existing_ts = {r["timestamp"][:16] for r in reboots}
    for ur in uptime_reboots:
        if ur["timestamp"][:16] not in existing_ts:
            all_reboots.append({"timestamp": ur["timestamp"], "reason": ur["reason"]})
    all_reboots.sort(key=lambda r: r.get("timestamp", ""))

    # WAN disconnection summary
    wan_ev = evidence.get("wan_disconnections", {})
    wan_summary = {
        "total_disconnections": wan_ev.get("count", 0),
        "first_ts": wan_ev.get("first_ts"),
        "last_ts": wan_ev.get("last_ts"),
    }

    # Failure chains
    chains = _detect_failure_chains(evidence, all_reboots)

    # Top suspected cause
    top_cause = _determine_top_cause(evidence, chains, memory_trend, all_reboots)

    # Data quality assessment
    domains_indexed = [p.stem.replace("_rg", "") for p in cpe_dir.glob("*_rg.parquet")]
    data_quality = {
        "domains_indexed": domains_indexed,
        "has_telemetry": telemetry_source != "parodus_marker_fallback" or bool(telemetry_context.get("marker")),
        "telemetry_source": telemetry_source,
        "has_boottime_log": (cpe_dir / "BootTime.log").exists(),
        "has_parodus_log": (cpe_dir / "PARODUSlog.txt").exists(),
    }

    return {
        "identity": identity,
        "reboot_summary": {
            "total_count": len(all_reboots),
            "events": all_reboots,
        },
        "wan_summary": wan_summary,
        "evidence": evidence,
        "failure_chains": chains,
        "memory_trend": memory_trend,
        "telemetry_context": _compact_telemetry(telemetry_context),
        "telemetry_source": telemetry_source,
        "top_suspected_cause": top_cause,
        "data_quality": data_quality,
    }


def _compact_telemetry(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce telemetry context to summary stats to keep JSONL lines compact."""
    compact: Dict[str, Any] = {"report_count": ctx.get("report_count", 0)}

    for series_key in ("cpu_usage", "memory_pct", "temperature"):
        series = ctx.get(series_key, [])
        if series:
            values = [s["value"] for s in series if isinstance(s.get("value"), (int, float))]
            if values:
                compact[series_key] = {
                    "avg": round(sum(values) / len(values), 1),
                    "peak": round(max(values), 1),
                    "min": round(min(values), 1),
                    "samples": len(values),
                }

    for snapshot_key in ("gpon", "wan", "wifi", "band_steering"):
        v = ctx.get(snapshot_key)
        if v:
            compact[snapshot_key] = v

    cd = ctx.get("connected_devices", [])
    if cd:
        vals = [c["value"] for c in cd if isinstance(c.get("value"), (int, float))]
        if vals:
            compact["connected_devices"] = {"avg": round(sum(vals) / len(vals), 1), "peak": max(vals)}

    return compact


# ---------------------------------------------------------------------------
# Fleet aggregate
# ---------------------------------------------------------------------------

def build_fleet_summary(
    per_cpe_records: List[Dict[str, Any]],
    project_id: str = "",
    job_id: str = "",
) -> Dict[str, Any]:
    """
    Build fleet-wide aggregate summary from per-CPE records.

    Args:
        per_cpe_records: List of per-CPE summary dicts.
        project_id: Project ID.
        job_id: Batch job ID.

    Returns:
        Dict for fleet_reboot_summary.json.
    """
    total_cpes = len(per_cpe_records)
    if total_cpes == 0:
        return {"error": "No CPE records provided", "total_cpes": 0}

    # Sample info
    models: Counter = Counter()
    firmware_versions: Counter = Counter()
    for rec in per_cpe_records:
        ident = rec.get("identity", {})
        model = ident.get("model", "unknown")
        fw = ident.get("firmware", "unknown")
        if model:
            models[model] += 1
        if fw:
            firmware_versions[fw] += 1

    # Reboot overview
    total_reboots = 0
    cpes_with_reboots = 0
    for rec in per_cpe_records:
        cnt = rec.get("reboot_summary", {}).get("total_count", 0)
        total_reboots += cnt
        if cnt > 0:
            cpes_with_reboots += 1

    # WAN overview
    total_wan_disconnections = 0
    cpes_with_wan_issues = 0
    for rec in per_cpe_records:
        wan_cnt = rec.get("wan_summary", {}).get("total_disconnections", 0)
        total_wan_disconnections += wan_cnt
        if wan_cnt > 0:
            cpes_with_wan_issues += 1

    # Problem categories (Beegol-style)
    wifi_problem_cpes = []
    wan_problem_cpes = []
    memory_problem_cpes = []

    for rec in per_cpe_records:
        serial = rec.get("identity", {}).get("cpe_serial", "")
        ev = rec.get("evidence", {})

        wifi_issues = (
            ev.get("wifi_driver_errors", {}).get("count", 0)
            + ev.get("wifi_disconnect_storm", {}).get("count", 0)
            + ev.get("dfs_cac_events", {}).get("count", 0)
            + ev.get("btm_steering", {}).get("count", 0)
        )
        if wifi_issues > 0:
            wifi_problem_cpes.append({"serial": serial, "total_events": wifi_issues})

        wan_issues = ev.get("wan_disconnections", {}).get("count", 0)
        if wan_issues > 0:
            wan_problem_cpes.append({"serial": serial, "total_events": wan_issues})

        mem_trend = rec.get("memory_trend", {})
        if mem_trend.get("peak_pct", 0) > 85:
            memory_problem_cpes.append({
                "serial": serial,
                "avg_pct": mem_trend.get("avg_pct"),
                "peak_pct": mem_trend.get("peak_pct"),
                "days_to_critical": mem_trend.get("days_to_critical"),
            })

    # Cause distribution
    cause_dist: Counter = Counter()
    for rec in per_cpe_records:
        cat = rec.get("top_suspected_cause", {}).get("category", "unknown")
        cause_dist[cat] += 1

    # Failure chain distribution
    chain_dist: Counter = Counter()
    for rec in per_cpe_records:
        for chain in rec.get("failure_chains", []):
            chain_dist[chain["chain_name"]] += 1

    # Top templates from all parquets (fleet-wide)
    template_counts: Counter = Counter()
    for rec in per_cpe_records:
        for cat, ev in rec.get("evidence", {}).items():
            for line in ev.get("sample_lines", []):
                template_counts[line[:200]] += 1

    # Client churn stats
    cpes_with_storms = 0
    peak_rates = []
    for rec in per_cpe_records:
        storm_data = rec.get("evidence", {}).get("wifi_disconnect_storm", {})
        if storm_data.get("sustained_storm"):
            cpes_with_storms += 1
        pr = storm_data.get("peak_rate_per_min", 0)
        if pr > 0:
            peak_rates.append(pr)

    # BTM stats
    cpes_with_btm = 0
    total_btm = 0
    for rec in per_cpe_records:
        btm = rec.get("evidence", {}).get("btm_steering", {}).get("count", 0)
        total_btm += btm
        if btm > 0:
            cpes_with_btm += 1

    # GPON/WAN health
    gpon_degrade_count = 0
    wan_error_cpes = 0
    for rec in per_cpe_records:
        tc = rec.get("telemetry_context", {})
        gpon = tc.get("gpon", {})
        if gpon.get("gpon_signalDegrade") or gpon.get("gpon_signalFail"):
            gpon_degrade_count += 1
        wan = tc.get("wan", {})
        if wan.get("wanoe_lastConnError"):
            wan_error_cpes += 1

    # Telemetry source distribution
    source_dist: Counter = Counter()
    for rec in per_cpe_records:
        source_dist[rec.get("telemetry_source", "none")] += 1

    # Unknown cohort
    unknown_cpes = []
    for rec in per_cpe_records:
        if (rec.get("reboot_summary", {}).get("total_count", 0) > 0
                and rec.get("top_suspected_cause", {}).get("category") in ("unknown", "no_reboots_detected")):
            unknown_cpes.append(rec.get("identity", {}).get("cpe_serial", ""))

    # Data quality
    has_telemetry = sum(1 for rec in per_cpe_records if rec.get("data_quality", {}).get("has_telemetry"))
    domains_coverage: Counter = Counter()
    for rec in per_cpe_records:
        for d in rec.get("data_quality", {}).get("domains_indexed", []):
            domains_coverage[d] += 1

    return {
        "project_id": project_id,
        "job_id": job_id,
        "generated_at": datetime.utcnow().isoformat(),
        "sample_info": {
            "total_cpes": total_cpes,
            "hardware_breakdown": dict(models.most_common(20)),
            "firmware_breakdown": dict(firmware_versions.most_common(20)),
        },
        "reboot_overview": {
            "total_reboots": total_reboots,
            "cpes_with_reboots": cpes_with_reboots,
            "pct_with_reboots": round(cpes_with_reboots / total_cpes * 100, 1) if total_cpes else 0,
            "avg_reboots_per_affected": round(total_reboots / max(cpes_with_reboots, 1), 2),
        },
        "wan_overview": {
            "total_disconnections": total_wan_disconnections,
            "cpes_affected": cpes_with_wan_issues,
            "pct_affected": round(cpes_with_wan_issues / total_cpes * 100, 1) if total_cpes else 0,
        },
        "problem_categories": {
            "wifi": {
                "cpes_affected": len(wifi_problem_cpes),
                "pct_affected": round(len(wifi_problem_cpes) / total_cpes * 100, 1) if total_cpes else 0,
                "worst_case": sorted(wifi_problem_cpes, key=lambda x: x["total_events"], reverse=True)[:3],
            },
            "wan": {
                "cpes_affected": len(wan_problem_cpes),
                "pct_affected": round(len(wan_problem_cpes) / total_cpes * 100, 1) if total_cpes else 0,
                "worst_case": sorted(wan_problem_cpes, key=lambda x: x["total_events"], reverse=True)[:3],
            },
            "memory": {
                "cpes_above_85pct": len(memory_problem_cpes),
                "pct_above_85pct": round(len(memory_problem_cpes) / total_cpes * 100, 1) if total_cpes else 0,
                "worst_case": sorted(memory_problem_cpes, key=lambda x: x.get("peak_pct", 0), reverse=True)[:3],
            },
        },
        "cause_distribution": dict(cause_dist.most_common()),
        "failure_chain_distribution": dict(chain_dist.most_common()),
        "top_templates": [{"template": t, "count": c} for t, c in template_counts.most_common(20)],
        "client_churn_stats": {
            "cpes_with_sustained_storms": cpes_with_storms,
            "pct_with_storms": round(cpes_with_storms / total_cpes * 100, 1) if total_cpes else 0,
            "avg_peak_rate": round(sum(peak_rates) / len(peak_rates), 1) if peak_rates else 0,
        },
        "btm_steering_stats": {
            "cpes_with_btm_events": cpes_with_btm,
            "total_btm_events": total_btm,
        },
        "gpon_wan_health": {
            "cpes_with_signal_degrade": gpon_degrade_count,
            "cpes_with_wan_errors": wan_error_cpes,
        },
        "telemetry_source_distribution": dict(source_dist),
        "unknown_cohort": unknown_cpes,
        "data_quality": {
            "pct_with_telemetry": round(has_telemetry / total_cpes * 100, 1) if total_cpes else 0,
            "domain_coverage": {d: round(c / total_cpes * 100, 1) for d, c in domains_coverage.most_common()},
        },
    }


# ---------------------------------------------------------------------------
# Orchestration: generate + persist
# ---------------------------------------------------------------------------

def generate_batch_reboot_summary(
    project_dir: Path,
    project_id: str,
    job_id: str,
    cpe_serials: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Generate reboot LLM summary for a batch job.

    Scans all CPE subdirectories under *project_dir*, builds per-CPE
    evidence, then aggregates fleet-wide.

    Args:
        project_dir: Path to the project directory
                     (e.g. ``UPLOAD_DIRECTORY/{user_id}/{project_id}``).
        project_id: Project UUID.
        job_id: Batch job UUID.
        cpe_serials: Optional list of serials to include.
                     If None, discovers all subdirectories.

    Returns:
        Dict with ``per_cpe_count``, ``fleet_summary_path``, ``per_cpe_path``.
    """
    start = time.time()
    logger.info(f"[RebootSummary] Starting for project={project_id}, job={job_id}")

    # Discover CPE directories
    if cpe_serials:
        cpe_dirs = [(project_dir / s, s) for s in cpe_serials if (project_dir / s).is_dir()]
    else:
        cpe_dirs = [
            (d, d.name)
            for d in sorted(project_dir.iterdir())
            if d.is_dir() and not d.name.startswith(".") and d.name not in (
                "raw", "staging", "telemetry", OUTPUT_DIR_NAME
            )
        ]

    logger.info(f"[RebootSummary] Found {len(cpe_dirs)} CPE directories")

    # Build per-CPE records
    per_cpe_records: List[Dict[str, Any]] = []
    errors: List[str] = []

    for cpe_dir, serial in cpe_dirs:
        try:
            record = build_per_cpe_summary(cpe_dir, serial, project_id, job_id)
            per_cpe_records.append(record)
        except Exception as exc:
            logger.warning(f"[RebootSummary] Error processing {serial}: {exc}")
            errors.append(f"{serial}: {exc}")

    # Build fleet aggregate
    fleet_summary = build_fleet_summary(per_cpe_records, project_id, job_id)

    # Save outputs
    output_dir = project_dir / OUTPUT_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    per_cpe_path = output_dir / PER_CPE_FILE
    with open(per_cpe_path, "w", encoding="utf-8") as fh:
        for rec in per_cpe_records:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    fleet_path = output_dir / FLEET_FILE
    with open(fleet_path, "w", encoding="utf-8") as fh:
        json.dump(fleet_summary, fh, indent=2, ensure_ascii=False, default=str)

    elapsed = time.time() - start
    logger.info(
        f"[RebootSummary] Completed in {elapsed:.1f}s: "
        f"{len(per_cpe_records)} CPEs, {len(errors)} errors"
    )

    return {
        "per_cpe_count": len(per_cpe_records),
        "fleet_summary_path": str(fleet_path),
        "per_cpe_path": str(per_cpe_path),
        "errors": errors,
        "elapsed_sec": round(elapsed, 1),
    }


def load_summary_outputs(project_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Load previously generated summary artifacts.

    Returns None if no summary exists.
    """
    output_dir = project_dir / OUTPUT_DIR_NAME
    fleet_path = output_dir / FLEET_FILE
    per_cpe_path = output_dir / PER_CPE_FILE

    if not fleet_path.exists():
        return None

    try:
        fleet = json.loads(fleet_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    per_cpe_count = 0
    if per_cpe_path.exists():
        with open(per_cpe_path, "r", encoding="utf-8") as fh:
            per_cpe_count = sum(1 for _ in fh)

    return {
        "fleet_summary": fleet,
        "per_cpe_count": per_cpe_count,
        "per_cpe_path": str(per_cpe_path),
        "fleet_path": str(fleet_path),
    }
