"""
SelfHeal API Routes
===================

Endpoints for SelfHeal.txt parsing, cross-CPE memory analytics, and charts.
Follows the same caching pattern as Telemetry: raw cache + API response cache.
"""

import hashlib
import io
import logging
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Set, Tuple
import json

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY
from logai.selfheal_parser import (
    extract_summary,
    parse_selfheal_file,
    process_application_key,
    sort_snapshots_chronologically,
)
from logai.selfheal_summary import build_cross_cpe_summary, build_single_cpe_summary
from logai.timestamp_parser import parse_timestamp, normalize_to_date_only
from logai.info_extractor import parse_version_txt

logger = logging.getLogger(__name__)

selfheal_bp = Blueprint("selfheal", __name__)

# Compact JSON for on.disk caches (indent=2 is very slow on large SelfHeal payloads).
_JSON_CACHE_SEP = (",", ":")


def _json_dumps_cache(payload: Any) -> str:
    return json.dumps(payload, separators=_JSON_CACHE_SEP, ensure_ascii=False)

# Fleet aggregation: ignore RSS trend noise below this (KB per snapshot step)
FLEET_LEAK_SLOPE_THRESHOLD_KB = 1.0
FLEET_TOP_PROCESS_ROWS = 40
FLEET_HEATMAP_MAX_PROCESSES = 24
FLEET_HEATMAP_MAX_CPES = 48
CROSS_CPE_MAX_WORKERS = 16

# Top-level project folders that are not CPE serial directories (fleet cache, issue analysis output, etc.)
_CROSS_CPE_EXCLUDED_TOP_LEVEL_DIRS = frozenset(
    {"selfheal", "issue_analysis", "staging", "raw", "telemetry"}
)

# Full fleet response cache (invalidated when CPE set or per-CPE parse artifacts change)
_FLEET_CROSS_CPE_OVERVIEW_CACHE = "cross_cpe_overview_cache.json"


def _selfheal_ts_to_utc_naive(ts: datetime) -> datetime:
    """Comparable local/UTC naive datetime for ordering (copy-aware safe)."""
    if ts.tzinfo is not None:
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def _selfheal_parse_timestamp(ts_str: str) -> Optional[datetime]:
    if not ts_str or not str(ts_str).strip():
        return None
    s = str(ts_str).strip()
    try:
        ts = parse_timestamp(s)
        if ts is not None:
            return ts
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _get_build_timestamps(project_dir: Path, cpe_dir: Optional[Path] = None) -> List[datetime]:
    """
    Same idea as Pattern Analyzer: firmware build dates from version.txt (date-only).

    Log lines on those calendar days are treated as pre-NTP. Checks project root,
    project merged_logs, and optionally the CPE folder (some uploads place version.txt per-CPE).
    """
    build_dates: List[datetime] = []
    version_paths: List[Path] = [
        project_dir / "version.txt",
        project_dir / "merged_logs" / "version.txt",
    ]
    if cpe_dir is not None:
        version_paths.extend(
            [
                cpe_dir / "version.txt",
                cpe_dir / "merged_logs" / "version.txt",
            ]
        )

    for version_path in version_paths:
        if not version_path.is_file():
            continue

        try:
            content = version_path.read_text(encoding="utf-8", errors="ignore")
            parsed = parse_version_txt(content)

            if not parsed.get("firmware_versions"):
                continue

            seen_dates: Set[date] = set()

            for fw in parsed["firmware_versions"]:
                build_time_str = fw.get("build_time")
                if not build_time_str:
                    continue
                try:
                    build_ts = parse_timestamp(str(build_time_str))
                    if build_ts is None:
                        continue
                    build_norm = normalize_to_date_only(
                        _selfheal_ts_to_utc_naive(build_ts)
                    )
                    dk = build_norm.date()
                    if dk not in seen_dates:
                        seen_dates.add(dk)
                        build_dates.append(build_norm)
                except (ValueError, TypeError, OSError):
                    continue

            build_dates.sort()
            if build_dates:
                return build_dates
        except Exception as e:
            logger.warning("Failed to extract build timestamps from %s: %s", version_path, e)
            continue

    return build_dates


def _pre_ntp_calendar_dates(project_dir: Path, cpe_dir: Optional[Path]) -> Set[date]:
    return {d.date() for d in _get_build_timestamps(project_dir, cpe_dir)}


def _filter_pre_ntp_data(
    snapshots: List[Dict[str, Any]],
    cpu_samples: List[Dict[str, Any]],
    project_dir: Path,
    cpe_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Filter pre-NTP samples: timestamps on any firmware build calendar day (Pattern Analyzer rule).

    Uses calendar dates so naive/aware datetimes match reliably.
    """
    pre_ntp_days = _pre_ntp_calendar_dates(project_dir, cpe_dir)
    if not pre_ntp_days:
        return snapshots, cpu_samples

    def _keep_sample(ts_raw: str) -> bool:
        ts = _selfheal_parse_timestamp(ts_raw)
        if ts is None:
            return True
        cal = _selfheal_ts_to_utc_naive(ts).date()
        return cal not in pre_ntp_days

    filtered_snapshots = [
        s for s in snapshots if not s.get("timestamp") or _keep_sample(str(s.get("timestamp")))
    ]
    filtered_cpu_samples = [
        c
        for c in cpu_samples
        if not c.get("timestamp") or _keep_sample(str(c.get("timestamp")))
    ]

    removed_snapshots = len(snapshots) - len(filtered_snapshots)
    removed_cpu = len(cpu_samples) - len(filtered_cpu_samples)
    if removed_snapshots or removed_cpu:
        logger.info(
            "Filtered pre-NTP (build-day) data: %s snapshots, %s CPU samples removed "
            "(build days: %s)",
            removed_snapshots,
            removed_cpu,
            ", ".join(sorted(d.isoformat() for d in pre_ntp_days)),
        )

    return filtered_snapshots, filtered_cpu_samples


def _clip_cpu_samples_after_earliest_snapshot(
    cpu_samples: List[Dict[str, Any]],
    snapshots: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Drop CPU samples strictly before the earliest meminfo snapshot time.

    RDK SelfHeal often logs CPU with an unsynced clock while snapshot blocks start later;
    this matches what the Meminfo charts cover without relying only on firmware build days.
    """
    if not snapshots or not cpu_samples:
        return cpu_samples

    min_snap: Optional[datetime] = None
    for s in snapshots:
        ts = _selfheal_parse_timestamp(str(s.get("timestamp", "")))
        if ts is None:
            continue
        tsn = _selfheal_ts_to_utc_naive(ts)
        if min_snap is None or tsn < min_snap:
            min_snap = tsn

    if min_snap is None:
        return cpu_samples

    kept: List[Dict[str, Any]] = []
    removed = 0
    for sample in cpu_samples:
        ts = _selfheal_parse_timestamp(str(sample.get("timestamp", "")))
        if ts is None:
            kept.append(sample)
            continue
        if _selfheal_ts_to_utc_naive(ts) >= min_snap:
            kept.append(sample)
        else:
            removed += 1

    if removed:
        logger.info(
            "Dropped %s CPU samples before earliest meminfo snapshot at %s",
            removed,
            min_snap.isoformat(),
        )

    return kept


def _cross_cpe_fingerprint(cpe_paths: List[Path]) -> str:
    """
    Stable signature from CPE folder names plus mtimes of parse inputs/caches.
    Any new log parse or cache write changes the fingerprint.
    """
    parts: List[str] = []
    for p in sorted(cpe_paths, key=lambda x: x.name):
        m = 0.0
        for rel in ("selfheal/response.json", "raw_selfheal_cache.json"):
            f = p / rel
            if f.is_file():
                m = max(m, f.stat().st_mtime)
        src = p / "SelfHeal.txt"
        if src.is_file():
            m = max(m, src.stat().st_mtime)
        parts.append(f"{p.name}:{m:.9f}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


_FLEET_CROSS_CPE_CACHE_VERSION = 2


def _load_fleet_cross_cpe_cache(
    project_dir: Path, fingerprint: str
) -> Optional[Dict[str, Any]]:
    path = project_dir / "selfheal" / _FLEET_CROSS_CPE_OVERVIEW_CACHE
    if not path.is_file():
        return None
    try:
        wrapper = json.loads(path.read_text())
    except Exception as e:
        logger.warning("Failed to read fleet cross-CPE overview cache: %s", e)
        return None
    if wrapper.get("fingerprint") != fingerprint:
        return None
    if int(wrapper.get("cache_version") or 0) != _FLEET_CROSS_CPE_CACHE_VERSION:
        return None
    payload = wrapper.get("payload")
    return payload if isinstance(payload, dict) else None


def _save_fleet_cross_cpe_cache(
    project_dir: Path, fingerprint: str, payload: Dict[str, Any]
) -> None:
    cache_dir = project_dir / "selfheal"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / _FLEET_CROSS_CPE_OVERVIEW_CACHE
    try:
        path.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "cache_version": _FLEET_CROSS_CPE_CACHE_VERSION,
                    "payload": payload,
                },
                indent=2,
            )
        )
    except Exception as e:
        logger.warning("Failed to write fleet cross-CPE overview cache: %s", e)


def _verify_project(project_id: str, user_id: str) -> tuple[Optional[Any], Optional[tuple]]:
    """Verify project ownership."""
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _project_dir(user_id: str, project_id: str, cpe_id: Optional[str] = None) -> Path:
    """Get project or CPE directory."""
    base = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    return base / cpe_id if cpe_id else base


def _find_selfheal_file(cpe_dir: Path) -> Optional[Path]:
    """Find SelfHeal.txt in CPE directory."""
    if cpe_dir.exists():
        for f in cpe_dir.iterdir():
            if f.is_file() and f.name.lower() == "selfheal.txt":
                return f
    return None


def _raw_cache_is_fresh(cpe_dir: Path) -> bool:
    """Check if raw cache is newer than source file."""
    cache_path = cpe_dir / "raw_selfheal_cache.json"
    if not cache_path.exists():
        return False

    source_path = _find_selfheal_file(cpe_dir)
    if not source_path:
        return False

    cache_mtime = cache_path.stat().st_mtime
    source_mtime = source_path.stat().st_mtime

    return cache_mtime > source_mtime


def _load_raw_selfheal_cache(cpe_dir: Path) -> Optional[Dict[str, Any]]:
    """Load raw cache if available."""
    cache_path = cpe_dir / "raw_selfheal_cache.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception as e:
            logger.warning(f"Failed to load raw selfheal cache: {e}")
    return None


def _save_raw_selfheal_cache(cpe_dir: Path, data: Dict[str, Any]) -> None:
    """Save raw cache."""
    cache_path = cpe_dir / "raw_selfheal_cache.json"
    try:
        cache_path.write_text(_json_dumps_cache(data))
    except Exception as e:
        logger.error(f"Failed to save raw selfheal cache: {e}")


def _invalidate_api_response_cache(cpe_dir: Path) -> None:
    """Delete API response cache to force rebuild."""
    response_path = cpe_dir / "selfheal" / "response.json"
    if response_path.exists():
        try:
            response_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete response cache: {e}")


def _load_api_response_cache(cpe_dir: Path) -> Optional[Dict[str, Any]]:
    """Load API response cache if available."""
    response_path = cpe_dir / "selfheal" / "response.json"
    if response_path.exists():
        try:
            return json.loads(response_path.read_text())
        except Exception as e:
            logger.warning(f"Failed to load API response cache: {e}")
    return None


def _save_api_response_cache(cpe_dir: Path, data: Dict[str, Any]) -> None:
    """Save API response cache (omit ephemeral keys such as cached)."""
    cache_dir = cpe_dir / "selfheal"
    cache_dir.mkdir(parents=True, exist_ok=True)
    response_path = cache_dir / "response.json"
    to_store = {k: v for k, v in data.items() if k != "cached"}
    try:
        response_path.write_text(_json_dumps_cache(to_store))
    except Exception as e:
        logger.error(f"Failed to save API response cache: {e}")


def _finalize_selfheal_parse_response(
    cpe_dir: Path,
    response: Dict[str, Any],
    *,
    skip_trend_realign: bool = False,
) -> Dict[str, Any]:
    """
    Align top_processes with snapshots, attach narrative_summary, persist cache.

    Call after _build_selfheal_response / _parse_and_build so summary matches trends.

    When *skip_trend_realign* is True (fresh parse in the same request), skip
    reloading raw_selfheal_cache.json and a redundant extract_summary — the
    response already matches the parsed snapshots and filters.
    """
    if skip_trend_realign:
        out = dict(response)
    else:
        out = _ensure_response_top_processes_trend(cpe_dir, dict(response))
    narrative = build_single_cpe_summary(out)
    merged = {**out, **narrative}
    _save_api_response_cache(cpe_dir, merged)
    return merged


def _persist_fleet_narrative_summary(
    project_dir: Path, body: Dict[str, Any], force: bool
) -> None:
    """Write Cross-CPE narrative alongside API response for audits."""
    cache_dir = project_dir / "selfheal"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "cross_cpe_narrative.json"
    ns = body.get("narrative_summary") or {}
    payload = {
        "narrative_summary": ns,
        "source_force": force,
        "overview": body.get("overview"),
    }
    try:
        path.write_text(json.dumps(payload, indent=2))
    except Exception as e:
        logger.warning("Failed to persist fleet narrative: %s", e)


def _ensure_raw_selfheal_data(cpe_dir: Path, force: bool = False) -> Dict[str, Any]:
    """Load or parse raw SelfHeal structures (snapshots, cpu_samples, summary)."""
    if not force and _raw_cache_is_fresh(cpe_dir):
        raw_data = _load_raw_selfheal_cache(cpe_dir)
        if raw_data:
            return raw_data
    raw_data = parse_selfheal_file(cpe_dir, force=force)
    if raw_data:
        _save_raw_selfheal_cache(cpe_dir, raw_data)
    return raw_data or {}


_EXCEL_SHEET_FORBIDDEN = '\\/*?:[]'
_RESERVED_SHEET_NAMES_LOWER = frozenset({"index", "meminfo"})


def _sanitize_excel_sheet_base(name: str) -> str:
    """Strip Excel-forbidden characters; max 31 chars for worksheet title."""
    s = str(name).strip()
    for ch in _EXCEL_SHEET_FORBIDDEN:
        s = s.replace(ch, "_")
    s = s.strip() or "App"
    return s[:31]


def _unique_excel_sheet_name(base: str, used: Set[str]) -> str:
    """Return a worksheet title unique in ``used`` and not reserved; mutates ``used``."""
    raw = _sanitize_excel_sheet_base(base)
    candidate = raw[:31]
    n = 2
    while True:
        c_low = candidate.lower()
        if candidate not in used and c_low not in _RESERVED_SHEET_NAMES_LOWER:
            used.add(candidate)
            return candidate
        suffix = f"_{n}"
        room = 31 - len(suffix)
        base_part = raw[:room] if room > 0 else ""
        candidate = (base_part if base_part else "x") + suffix
        n += 1


def _excel_sheet_location_a1(sheet_title: str) -> str:
    """Cell reference for an internal link's ``location`` (no leading ``#``)."""
    esc = str(sheet_title).replace("'", "''")
    return f"'{esc}'!A1"


def _set_internal_cell_link(cell: Any, sheet_title: str, display: str) -> None:
    """Same-workbook link: cell shows ``display`` (not a ``=HYPERLINK`` formula)."""
    from openpyxl.styles import Font
    from openpyxl.worksheet.hyperlink import Hyperlink

    cell.value = display
    cell.hyperlink = Hyperlink(
        ref=cell.coordinate,
        location=_excel_sheet_location_a1(sheet_title),
        display=display,
    )
    cell.font = Font(color="000000", underline=None)


def _excel_column_autosize_width(cell_value: Any, cap: int = 72) -> float:
    """Approximate display width for autosizing; uses HYPERLINK display text when present."""
    if cell_value is None:
        return 0.0
    s = str(cell_value)
    return float(min(len(s) + 2, cap))


def _autosize_sheet_columns(ws: Any, cap: int = 72, min_width: float = 10.0) -> None:
    from openpyxl.utils import get_column_letter

    if ws.max_column == 0 or ws.max_row == 0:
        return
    for col_cells in ws.iter_cols(
        min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column
    ):
        if not col_cells:
            continue
        letter = get_column_letter(col_cells[0].column)
        best = min_width
        for cell in col_cells:
            best = max(best, _excel_column_autosize_width(cell.value, cap=cap))
        ws.column_dimensions[letter].width = best


def _build_selfheal_xlsx(raw_data: Dict[str, Any], cpe_serial: str) -> io.BytesIO:
    """
    Build an Excel workbook: **Index** (one column: in-workbook links; cell text is the label),
    **meminfo**, and one sheet per normalized application (``process_application_key``)
    with that app's rows.

    Rows with no normalized process key are omitted from per-app sheets (no aggregate
    **process** worksheet).
    """
    from openpyxl import Workbook

    snapshots: List[Dict[str, Any]] = raw_data.get("snapshots") or []
    wb = Workbook()
    ws_index = wb.active
    assert ws_index is not None
    ws_index.title = "Index"
    ws_mem = wb.create_sheet("meminfo")
    used_sheet_titles: Set[str] = {"Index", "meminfo"}

    mem_keys: Set[str] = set()
    for snap in snapshots:
        ma = snap.get("meminfo_all")
        if isinstance(ma, dict):
            mem_keys.update(ma.keys())
        elif snap.get("meminfo") and isinstance(snap["meminfo"], dict):
            mem_keys.update(snap["meminfo"].keys())

    sorted_mem_keys = sorted(mem_keys)
    mem_headers = [
        "snapshot_iso",
        "wall_clock",
        "mem_total_summary_kb",
        "mem_free_summary_kb",
        "cached_memory_kb",
    ] + sorted_mem_keys
    ws_mem.append(mem_headers)

    proc_headers = [
        "snapshot_iso",
        "wall_clock",
        "pid",
        "vsz_kb",
        "rss_kb",
        "shr_kb",
        "dirty_kb",
        "stack_kb",
        "command",
    ]
    rows_by_app: Dict[str, List[List[Any]]] = defaultdict(list)

    for snap in snapshots:
        ts = str(snap.get("timestamp", ""))
        wc = str(snap.get("wall_clock", ""))
        mt_sum = snap.get("mem_total", 0)
        mf_sum = snap.get("mem_free_summary", 0)
        cmem = snap.get("cached_memory", 0)
        ma = snap.get("meminfo_all")
        if not isinstance(ma, dict):
            ma = {}
            inner = snap.get("meminfo")
            if isinstance(inner, dict):
                ma = {k: inner[k] for k in sorted_mem_keys if k in inner}

        row_m = [ts, wc, mt_sum, mf_sum, cmem]
        for k in sorted_mem_keys:
            row_m.append(ma.get(k, ""))
        ws_mem.append(row_m)

        for proc in snap.get("processes") or []:
            cmd = str(proc.get("command", ""))
            row_p = [
                ts,
                wc,
                proc.get("pid", ""),
                proc.get("vsz_kb", ""),
                proc.get("rss_kb", ""),
                proc.get("shr_kb", ""),
                proc.get("dirty_kb", ""),
                proc.get("stack_kb", ""),
                cmd,
            ]
            app = process_application_key(cmd)
            if app is not None:
                rows_by_app[app].append(row_p)

    proc_header_labels = [h.replace("_", " ").title() for h in proc_headers]
    header_fill_color = "4472C4"
    from openpyxl.styles import Font, PatternFill

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(
        start_color=header_fill_color,
        end_color=header_fill_color,
        fill_type="solid",
    )

    app_to_sheet: List[tuple[str, str]] = []
    for app in sorted(rows_by_app.keys()):
        sheet_title = _unique_excel_sheet_name(app, used_sheet_titles)
        app_to_sheet.append((app, sheet_title))
        ws_app = wb.create_sheet(sheet_title)
        ws_app.append(proc_header_labels)
        for cell in ws_app[1]:
            cell.font = header_font
            cell.fill = header_fill
        ws_app.freeze_panes = "A2"
        for row in rows_by_app[app]:
            ws_app.append(row)

    idx_row = 1
    cell_m = ws_index.cell(row=idx_row, column=1)
    _set_internal_cell_link(cell_m, "meminfo", "Meminfo")
    idx_row += 1
    for app, sheet_title in app_to_sheet:
        cell_a = ws_index.cell(row=idx_row, column=1)
        _set_internal_cell_link(cell_a, sheet_title, app)
        idx_row += 1

    _autosize_sheet_columns(ws_index)
    _autosize_sheet_columns(ws_mem)
    for app, sheet_title in app_to_sheet:
        _autosize_sheet_columns(wb[sheet_title])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _build_latest_process_table(snapshots: list) -> Dict[str, Any]:
    """
    Most recent snapshot's process table (all parsed fields), RSS descending.

    UI may re-sort client-side; server default is highest RSS first.
    """
    if not snapshots:
        return {
            "snapshot_timestamp": "",
            "snapshot_wall_clock": "",
            "rows": [],
        }
    last = snapshots[-1]
    processes = last.get("processes") or []
    rows: List[Dict[str, Any]] = []
    for p in processes:
        rows.append(
            {
                "pid": int(p.get("pid", 0)),
                "vsz_kb": int(p.get("vsz_kb", 0)),
                "rss_kb": int(p.get("rss_kb", 0)),
                "shr_kb": int(p.get("shr_kb", 0)),
                "dirty_kb": int(p.get("dirty_kb", 0)),
                "stack_kb": int(p.get("stack_kb", 0)),
                "command": str(p.get("command", "")),
            }
        )
    rows.sort(key=lambda r: r["rss_kb"], reverse=True)
    return {
        "snapshot_timestamp": str(last.get("timestamp", "")),
        "snapshot_wall_clock": str(last.get("wall_clock", "")),
        "rows": rows,
    }


def _build_memory_chart(snapshots: list) -> Dict[str, Any]:
    """
    Build memory trends chart (/proc/meminfo fields).

    Shows MemTotal, MemAvailable, MemFree, Active, Inactive, Slab, SReclaimable, SUnreclaim.
    """
    if not snapshots:
        return {"group": "System Memory", "traces": []}

    traces = []
    times = []
    meminfo_fields = {
        "mem_total": "MemTotal",
        "mem_available": "MemAvailable",
        "mem_free": "MemFree",
        "active": "Active",
        "inactive": "Inactive",
        "slab": "Slab",
        "sreclaimable": "SReclaimable",
        "sunreclaim": "SUnreclaim (Kernel)",
        "buffers": "Buffers",
        "cached": "Cached",
    }

    # Collect values per field
    field_values: Dict[str, list] = {field: [] for field in meminfo_fields.keys()}

    for snapshot in snapshots:
        timestamp = snapshot.get("timestamp", "")
        times.append(timestamp)

        meminfo = snapshot.get("meminfo", {})
        for field_key, field_label in meminfo_fields.items():
            field_values[field_key].append(meminfo.get(field_key, 0))

    # Build traces (limit to 10 most important fields)
    priority_fields = [
        "mem_available",
        "mem_free",
        "active",
        "slab",
        "sunreclaim",
        "sreclaimable",
        "buffers",
        "cached",
    ]

    for field_key in priority_fields:
        if field_key in field_values:
            traces.append(
                {
                    "label": meminfo_fields[field_key],
                    "unit": "KB",
                    "times": times,
                    "values": field_values[field_key],
                }
            )

    return {"group": "System Memory", "traces": traces}


# Smooth dense CPU telemetry: time-bucket mean keeps trends readable in Plotly.
_CPU_CHART_TARGET_POINTS = 480
_CPU_CHART_MIN_BUCKET_SEC = 60


def _cpu_sample_unix_seconds(ts: datetime) -> float:
    """UTC-naive seconds since epoch for bucketing (device timestamps treated as UTC wall)."""
    base = datetime(1970, 1, 1)
    n = _selfheal_ts_to_utc_naive(ts)
    return (n - base).total_seconds()


def _format_cpu_chart_time(ts: datetime) -> str:
    """ISO-like string consistent with SelfHeal.txt CPU lines."""
    n = _selfheal_ts_to_utc_naive(ts)
    return n.strftime("%Y-%m-%dT%H:%M:%S")


def _build_cpu_chart(cpu_samples: list) -> Optional[Dict[str, Any]]:
    """Build CPU usage chart from continuous samples (time-bucket average when very dense)."""
    if not cpu_samples:
        return None

    parsed: List[Tuple[datetime, float, str]] = []
    for s in cpu_samples:
        ts_raw = str(s.get("timestamp", "")).strip()
        ts = _selfheal_parse_timestamp(ts_raw) if ts_raw else None
        val = float(s.get("cpu_usage_pct", 0) or 0)
        if ts is None:
            continue
        parsed.append((ts, val, ts_raw))

    if not parsed:
        times = [str(s.get("timestamp", "")) for s in cpu_samples]
        values = [float(s.get("cpu_usage_pct", 0) or 0) for s in cpu_samples]
        if not any(times):
            return None
        return {
            "group": "CPU Usage",
            "traces": [{"label": "CPU Usage", "unit": "%", "times": times, "values": values}],
        }

    if len(parsed) <= _CPU_CHART_TARGET_POINTS:
        times = [t_raw for _, _, t_raw in parsed]
        values = [v for _, v, _ in parsed]
        return {
            "group": "CPU Usage",
            "traces": [{"label": "CPU Usage", "unit": "%", "times": times, "values": values}],
        }

    # Time span → bucket size for ~target display points
    naive_times = [_selfheal_ts_to_utc_naive(t) for t, _, _ in parsed]
    t_min = min(naive_times)
    t_max = max(naive_times)
    span_sec = max(1.0, (t_max - t_min).total_seconds())
    bucket_sec = max(
        _CPU_CHART_MIN_BUCKET_SEC,
        int(math.ceil(span_sec / float(_CPU_CHART_TARGET_POINTS))),
    )

    buckets: Dict[int, List[float]] = defaultdict(list)
    for ts, val, _ in parsed:
        key = int(_cpu_sample_unix_seconds(ts) // bucket_sec)
        buckets[key].append(val)

    ordered = sorted(buckets.items(), key=lambda kv: kv[0])
    times_out: List[str] = []
    values_out: List[float] = []
    epoch = datetime(1970, 1, 1)
    for bkey, vals in ordered:
        if not vals:
            continue
        bucket_start = epoch + timedelta(seconds=bkey * bucket_sec)
        times_out.append(_format_cpu_chart_time(bucket_start))
        values_out.append(round(mean(vals), 2))

    if not times_out:
        return None

    return {
        "group": "CPU Usage",
        "display": {
            "smoothed": True,
            "source_samples": len(cpu_samples),
            "chart_points": len(times_out),
            "bucket_seconds": bucket_sec,
        },
        "traces": [
            {
                "label": "CPU Usage",
                "unit": "%",
                "times": times_out,
                "values": values_out,
            }
        ],
    }


def _build_memory_pressure_chart(snapshots: list) -> Dict[str, Any]:
    """
    Build memory pressure indicators chart.

    Shows: Committed_AS, CommitLimit, SUnreclaim/Slab ratio.
    """
    if not snapshots:
        return {"group": "Memory Pressure", "traces": []}

    traces = []
    times = []
    committed_as_vals = []
    commit_limit_vals = []
    sunreclaim_pct_vals = []

    for snapshot in snapshots:
        timestamp = snapshot.get("timestamp", "")
        times.append(timestamp)

        meminfo = snapshot.get("meminfo", {})
        committed_as = meminfo.get("committed_as", 0)
        commit_limit = meminfo.get("commit_limit", 0)
        slab = meminfo.get("slab", 0)
        sunreclaim = meminfo.get("sunreclaim", 0)

        committed_as_vals.append(committed_as)
        commit_limit_vals.append(commit_limit)

        # SUnreclaim as % of Slab
        if slab > 0:
            sunreclaim_pct = round(100 * sunreclaim / slab, 2)
        else:
            sunreclaim_pct = 0
        sunreclaim_pct_vals.append(sunreclaim_pct)

    if times:
        traces.append(
            {
                "label": "Committed_AS",
                "unit": "KB",
                "times": times,
                "values": committed_as_vals,
            }
        )
        traces.append(
            {
                "label": "CommitLimit",
                "unit": "KB",
                "times": times,
                "values": commit_limit_vals,
            }
        )
        traces.append(
            {
                "label": "SUnreclaim (% of Slab)",
                "unit": "%",
                "times": times,
                "values": sunreclaim_pct_vals,
            }
        )

    return {"group": "Memory Pressure", "traces": traces}


_PROCESS_SERIES_APP_CAP = 120
_INCREASING_RSS_TRACE_LIMIT = 10


def _build_process_series_by_app(
    snapshots: list,
    mandatory_app_keys: Set[str],
    max_apps: int = _PROCESS_SERIES_APP_CAP,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Per-application time series from process rows (one entry per snapshot row).

    Keys are capped by max observed RSS; ``mandatory_app_keys`` are always kept.
    """
    series: Dict[str, List[Dict[str, Any]]] = {}
    for snapshot in snapshots:
        ts = str(snapshot.get("timestamp", ""))
        wc = str(snapshot.get("wall_clock", ""))
        for proc in snapshot.get("processes") or []:
            cmd = str(proc.get("command", ""))
            app = process_application_key(cmd)
            if app is None:
                continue
            row = {
                "timestamp": ts,
                "wall_clock": wc,
                "pid": int(proc.get("pid", 0)),
                "vsz_kb": int(proc.get("vsz_kb", 0)),
                "rss_kb": int(proc.get("rss_kb", 0)),
                "shr_kb": int(proc.get("shr_kb", 0)),
                "dirty_kb": int(proc.get("dirty_kb", 0)),
                "stack_kb": int(proc.get("stack_kb", 0)),
                "command": cmd,
            }
            series.setdefault(app, []).append(row)

    if not series:
        return {}

    max_rss_by_app: Dict[str, int] = {}
    for app, rows in series.items():
        max_rss_by_app[app] = max((r["rss_kb"] for r in rows), default=0)

    ranked = sorted(max_rss_by_app.keys(), key=lambda a: max_rss_by_app[a], reverse=True)
    keep = set(ranked[:max_apps]) | set(mandatory_app_keys)
    return {app: rows for app, rows in series.items() if app in keep}


def _build_increasing_rss_processes(
    process_series_by_app: Dict[str, List[Dict[str, Any]]],
    max_traces: int = _INCREASING_RSS_TRACE_LIMIT,
) -> Dict[str, Any]:
    """Apps whose last RSS exceeds first RSS; top traces by delta for Plotly."""
    candidates: List[tuple[str, int, List[Dict[str, Any]]]] = []
    for app, rows in process_series_by_app.items():
        if len(rows) < 2:
            continue
        first = rows[0]["rss_kb"]
        last = rows[-1]["rss_kb"]
        delta = last - first
        if delta > 0:
            candidates.append((app, delta, rows))

    candidates.sort(key=lambda x: x[1], reverse=True)
    traces: List[Dict[str, Any]] = []
    for app, _delta, rows in candidates[:max_traces]:
        traces.append(
            {
                "label": app,
                "unit": "KB",
                "times": [r["timestamp"] for r in rows],
                "values": [r["rss_kb"] for r in rows],
            }
        )

    return {"group": "Increasing RSS (by application)", "traces": traces}


def _cached_response_needs_process_series(response: Dict[str, Any]) -> bool:
    """
    True if API response cache predates process_series / increasing_rss fields,
    or has an empty series while process rows exist (should rebuild from raw).
    """
    if "process_series_by_app" not in response or "increasing_rss_processes" not in response:
        return True
    ps = response.get("process_series_by_app")
    if not isinstance(ps, dict):
        return True
    if ps:
        return False
    km = response.get("key_metrics") or {}
    return int(km.get("process_row_count") or 0) > 0


def _enrich_cached_response_process_series(
    cpe_dir: Path, response: Dict[str, Any]
) -> Dict[str, Any]:
    """Fill process_series_by_app and increasing_rss_processes from raw snapshot cache."""
    raw_data = _ensure_raw_selfheal_data(cpe_dir, force=False)
    snapshots = sort_snapshots_chronologically(list(raw_data.get("snapshots") or []))
    cpu_samples = raw_data.get("cpu_samples") or []
    summary = extract_summary(snapshots, cpu_samples)
    top_list = summary.get("top_processes_by_rss") or []
    mandatory_apps: Set[str] = {
        str(p.get("command", "")).strip()
        for p in top_list
        if isinstance(p, dict) and str(p.get("command", "")).strip()
    }
    for p in summary.get("top_processes_by_rss_trend") or []:
        c = str(p.get("command", "")).strip()
        if isinstance(p, dict) and c:
            mandatory_apps.add(c)
    process_series = _build_process_series_by_app(snapshots, mandatory_apps)
    increasing_rss = _build_increasing_rss_processes(process_series)
    trend_list = summary.get("top_processes_by_rss_trend") or []
    km = dict(response.get("key_metrics") or {})
    if summary.get("overall_time_range"):
        km["overall_time_range"] = summary["overall_time_range"]
    if summary.get("snapshot_count") is not None:
        km["snapshot_count"] = summary["snapshot_count"]
    out = {
        **response,
        "process_series_by_app": process_series,
        "increasing_rss_processes": increasing_rss,
        "top_processes": trend_list,
        "key_metrics": km,
    }
    return out


def _ensure_response_top_processes_trend(
    cpe_dir: Path, response: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Align ``top_processes`` (RSS trend rows) with the current raw snapshot list.

    Always runs :func:`extract_summary` on chronological snapshots instead of reusing
    ``summary[\"top_processes_by_rss_trend\"]`` from the raw JSON cache, which could drift
    from stored snapshots (e.g. after parser changes) while ``process_series_by_app`` was
    rebuilt from snapshots—matching hover first/last ΣRSS to the per-application table.
    """
    try:
        raw_data = _ensure_raw_selfheal_data(cpe_dir, force=False)
    except Exception:
        return response
    snapshots = sort_snapshots_chronologically(list(raw_data.get("snapshots") or []))
    if not snapshots:
        return response
    fresh_summary = extract_summary(snapshots, raw_data.get("cpu_samples") or [])
    trend_list = fresh_summary.get("top_processes_by_rss_trend") or []
    km = dict(response.get("key_metrics") or {})
    if fresh_summary.get("overall_time_range"):
        km["overall_time_range"] = fresh_summary["overall_time_range"]
    if fresh_summary.get("snapshot_count") is not None:
        km["snapshot_count"] = fresh_summary["snapshot_count"]
    return {**response, "top_processes": trend_list, "key_metrics": km}


def _build_selfheal_response(
    raw_data: Dict[str, Any],
    cpe_serial: Optional[str] = None,
    project_dir: Optional[Path] = None,
    cpe_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Build the complete API response from raw parsed data.

    Includes charts, key metrics, device info, and alerts.
    """
    snapshots = sort_snapshots_chronologically(list(raw_data.get("snapshots") or []))
    cpu_samples = raw_data.get("cpu_samples", [])
    
    # Pattern Analyzer rule: drop samples on firmware build-day; clip CPU to meminfo timeline
    if project_dir:
        snapshots, cpu_samples = _filter_pre_ntp_data(
            snapshots, cpu_samples, project_dir, cpe_dir
        )
    cpu_samples = _clip_cpu_samples_after_earliest_snapshot(cpu_samples, snapshots)

    device_flags = raw_data.get("device_flags", {})
    summary = extract_summary(snapshots, cpu_samples)

    charts = []
    cpu_chart = _build_cpu_chart(cpu_samples)
    if cpu_chart:
        charts.append(cpu_chart)

    charts.append(_build_memory_chart(snapshots))
    charts.append(_build_memory_pressure_chart(snapshots))

    # Build status based on alerts
    status = "OK"
    alerts = summary.get("alerts", [])
    if "KERNEL_LEAK" in alerts or "OVERCOMMIT_RISK" in alerts:
        status = "CRITICAL"
    elif "NO_SWAP" in alerts or "LOW_MEMORY" in alerts:
        status = "WARNING"

    time_range = summary.get("overall_time_range") or {}
    top_list = summary.get("top_processes_by_rss") or []
    trend_list = summary.get("top_processes_by_rss_trend") or []
    mandatory_apps: Set[str] = {
        str(p.get("command", "")).strip()
        for p in top_list
        if isinstance(p, dict) and str(p.get("command", "")).strip()
    }
    for p in trend_list:
        c = str(p.get("command", "")).strip()
        if isinstance(p, dict) and c:
            mandatory_apps.add(c)
    process_series = _build_process_series_by_app(snapshots, mandatory_apps)
    increasing_rss = _build_increasing_rss_processes(process_series)

    response = {
        "device_info": {
            "serial": cpe_serial or "Unknown",
            "telemetry2_enabled": device_flags.get("telemetry2_enabled"),
            "ipv6_support": device_flags.get("ipv6_support", False),
        },
        "charts": charts,
        "latest_process_table": _build_latest_process_table(snapshots),
        "process_series_by_app": process_series,
        "increasing_rss_processes": increasing_rss,
        "key_metrics": {
            "snapshot_count": summary.get("snapshot_count", 0),
            "process_row_count": summary.get("process_row_count", 0),
            "cpu_sample_count": summary.get("cpu_sample_count", 0),
            "peak_memory_usage_pct": summary.get("peak_memory_usage_pct", 0),
            "min_memory_available_kb": summary.get("min_memory_available_kb"),
            "avg_memory_available_kb": summary.get("avg_memory_available_kb"),
            "mem_available_min_pct": summary.get("mem_available_min_pct"),
            "mem_available_avg_pct": summary.get("mem_available_avg_pct"),
            "slab_ols_slope_kb_per_step": summary.get("slab_ols_slope_kb_per_step"),
            "total_user_rss_ols_slope_kb_per_step": summary.get(
                "total_user_rss_ols_slope_kb_per_step"
            ),
            "peak_cpu_usage_pct": summary.get("peak_cpu_usage_pct", 0),
            "avg_cpu_usage_pct": summary.get("avg_cpu_usage_pct"),
            "overall_time_range": time_range,
        },
        "memory_pressure": summary.get("memory_pressure_indicators", {}),
        "top_processes": trend_list,
        "alerts": alerts,
        "status": status,
    }

    return response


def _parse_and_build(
    cpe_dir: Path,
    cpe_serial: Optional[str] = None,
    force: bool = False,
    *,
    persist_api_cache: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Parse SelfHeal.txt and build full response.

    Uses caching: raw cache + API response cache.

    Returns:
        (api_response_dict, raw_data_dict) — *raw_data* is the parsed payload
        (same as written to raw_selfheal_cache.json) for callers that finalize
        in the same request without re-reading disk.

    Args:
        persist_api_cache: When False, skip writing selfheal/response.json here
            (e.g. single-CPE parse defers to _finalize_selfheal_parse_response
            to avoid a second serialize + write of the same body).
    """
    # Try to load from raw cache if not forced
    if not force and _raw_cache_is_fresh(cpe_dir):
        raw_data = _load_raw_selfheal_cache(cpe_dir)
        if raw_data:
            logger.info(f"Using cached raw selfheal data from {cpe_dir}")
        else:
            raw_data = parse_selfheal_file(cpe_dir, force=force)
    else:
        raw_data = parse_selfheal_file(cpe_dir, force=force)

    if not raw_data:
        raw_data = {}

    # Save raw cache
    if raw_data:
        _save_raw_selfheal_cache(cpe_dir, raw_data)

    # Build and cache API response
    if force:
        _invalidate_api_response_cache(cpe_dir)

    # Pass project_dir (parent of CPE directory) to enable pre-NTP filtering
    project_dir = cpe_dir.parent
    response = _build_selfheal_response(
        raw_data, cpe_serial, project_dir=project_dir, cpe_dir=cpe_dir
    )
    if persist_api_cache:
        _save_api_response_cache(cpe_dir, response)

    return response, raw_data


@selfheal_bp.route("/<project_id>/selfheal/parse", methods=["POST"])
@jwt_required()
def parse_selfheal(project_id: str):
    """
    Parse SelfHeal.txt for a specific CPE.

    Query params:
        - cpe_serial: CPE serial number (required)
        - force: If 1, force re-parse (skip cache)

    Returns:
        Parsed data with charts, metrics, and alerts.
    """
    user_id = get_user_id()
    project, error = _verify_project(project_id, user_id)
    if error:
        return error

    cpe_serial = request.args.get("cpe_serial")
    if not cpe_serial:
        return jsonify({"error": "cpe_serial parameter required"}), 400

    force = request.args.get("force") == "1"

    cpe_dir = _project_dir(user_id, project_id, cpe_serial)
    if not cpe_dir.exists():
        return jsonify({"error": "CPE directory not found"}), 404

    try:
        # Try to load from API response cache first
        if not force:
            cached_response = _load_api_response_cache(cpe_dir)
            if cached_response:
                if _cached_response_needs_process_series(cached_response):
                    try:
                        enriched = _enrich_cached_response_process_series(
                            cpe_dir, cached_response
                        )
                        _save_api_response_cache(cpe_dir, enriched)
                        cached_response = enriched
                    except Exception as enrich_err:
                        logger.warning(
                            "Could enrich selfheal cache with process series: %s",
                            enrich_err,
                        )
                out = dict(cached_response)
                out["cached"] = True
                out = _finalize_selfheal_parse_response(cpe_dir, out)
                out["cached"] = True
                return jsonify(out), 200

        # Parse and build (defer API cache write until finalize — one compact JSON write)
        response, _raw_data = _parse_and_build(
            cpe_dir, cpe_serial, force=force, persist_api_cache=False
        )
        response = _finalize_selfheal_parse_response(
            cpe_dir, response, skip_trend_realign=True
        )
        response = {**response, "cached": False}
        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Failed to parse selfheal for {cpe_serial}: {e}")
        return jsonify({"error": str(e)}), 500


@selfheal_bp.route("/<project_id>/selfheal/export-xlsx", methods=["GET"])
@jwt_required()
def export_selfheal_xlsx(project_id: str):
    """
    Export SelfHeal snapshots as Excel: Index (links; process name as link text),
    meminfo, and one sheet per normalized process name (same key as process_application_key).

    Query: cpe_serial (required), force=1 to bypass raw cache freshness.
    """
    user_id = get_user_id()
    project, error = _verify_project(project_id, user_id)
    if error:
        return error

    cpe_serial = request.args.get("cpe_serial")
    if not cpe_serial:
        return jsonify({"error": "cpe_serial parameter required"}), 400

    force = request.args.get("force") == "1"
    cpe_dir = _project_dir(user_id, project_id, cpe_serial)
    if not cpe_dir.exists():
        return jsonify({"error": "CPE directory not found"}), 404

    try:
        raw_data = _ensure_raw_selfheal_data(cpe_dir, force=force)
        if not raw_data.get("snapshots"):
            return jsonify({"error": "No SelfHeal snapshots found"}), 404

        buf = _build_selfheal_xlsx(raw_data, cpe_serial)
        safe_serial = "".join(c if c.isalnum() or c in "-_" else "_" for c in cpe_serial)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        fname = f"selfheal-{safe_serial}-{stamp}.xlsx"
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=fname,
        )
    except Exception as e:
        logger.error(f"Failed SelfHeal XLSX export for {cpe_serial}: {e}")
        return jsonify({"error": str(e)}), 500


def _derive_cross_cpe_status(alerts: List[str]) -> str:
    if "KERNEL_LEAK" in alerts:
        return "KERNEL_LEAK"
    if "OVERCOMMIT_RISK" in alerts:
        return "OVERCOMMIT_RISK"
    if "NO_SWAP" in alerts:
        return "NO_SWAP"
    if "LOW_MEMORY" in alerts:
        return "LOW_MEMORY"
    return "OK"


def _build_cross_cpe_entry(
    cpe_serial: str, response: Dict[str, Any]
) -> Dict[str, Any]:
    alerts = response.get("alerts", [])
    metrics = response.get("key_metrics", {})
    memory_pressure = response.get("memory_pressure", {})
    status = _derive_cross_cpe_status(alerts)
    return {
        "serial": cpe_serial,
        "status": status,
        "peak_memory_usage_pct": metrics.get("peak_memory_usage_pct", 0),
        "min_memory_available_kb": metrics.get("min_memory_available_kb"),
        "avg_memory_available_kb": metrics.get("avg_memory_available_kb"),
        "mem_available_min_pct": metrics.get("mem_available_min_pct"),
        "mem_available_avg_pct": metrics.get("mem_available_avg_pct"),
        "peak_cpu_usage_pct": metrics.get("peak_cpu_usage_pct", 0),
        "avg_cpu_usage_pct": metrics.get("avg_cpu_usage_pct"),
        "cpu_sample_count": metrics.get("cpu_sample_count", 0),
        "snapshot_count": metrics.get("snapshot_count", 0),
        "slab_ols_slope_kb_per_step": metrics.get("slab_ols_slope_kb_per_step"),
        "total_user_rss_ols_slope_kb_per_step": metrics.get(
            "total_user_rss_ols_slope_kb_per_step"
        ),
        "alerts": alerts,
        "memory_pressure": memory_pressure,
        "sunreclaim_pct": memory_pressure.get("sunreclaim_pct", 0),
        "overcommit_ratio": memory_pressure.get("overcommit_ratio", 0),
        "pressure_score_0_100": memory_pressure.get("pressure_score_0_100"),
        "cached_pct_of_memtotal": memory_pressure.get("cached_pct_of_memtotal"),
    }


def _process_cross_cpe_one(
    cpe_path: Path, force: bool
) -> Optional[Dict[str, Any]]:
    cpe_serial = cpe_path.name
    try:
        if not force:
            cached = _load_api_response_cache(cpe_path)
            if cached and isinstance(cached.get("key_metrics"), dict):
                response = dict(cached)
                entry = _build_cross_cpe_entry(cpe_serial, response)
                trends = response.get("top_processes") or []
                return {"entry": entry, "trends": trends}
        response, _raw_data = _parse_and_build(cpe_path, cpe_serial, force=force)
        entry = _build_cross_cpe_entry(cpe_serial, response)
        trends = response.get("top_processes") or []
        return {"entry": entry, "trends": trends}
    except Exception as e:
        logger.warning("Failed to parse selfheal for CPE %s: %s", cpe_serial, e)
        return None


def _aggregate_fleet_process_leaks(
    trend_rows_per_cpe: List[Tuple[str, List[Dict[str, Any]]]],
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Tuple[str, float]]]]:
    """
    Returns sorted fleet table rows and proc -> [(serial, slope), ...] for heatmap.
    """
    proc_slopes: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    for serial, rows in trend_rows_per_cpe:
        for row in rows:
            if not isinstance(row, dict):
                continue
            cmd = str(row.get("command", "")).strip()
            if not cmd:
                continue
            slope = row.get("rss_trend_slope_kb")
            if not isinstance(slope, (int, float)):
                continue
            if float(slope) <= FLEET_LEAK_SLOPE_THRESHOLD_KB:
                continue
            proc_slopes[cmd].append((serial, float(slope)))

    fleet_rows: List[Dict[str, Any]] = []
    for cmd, pairs in proc_slopes.items():
        slopes = [s for _, s in pairs]
        cpe_serials = sorted({str(s) for s, _ in pairs if s})
        fleet_rows.append(
            {
                "process": cmd,
                "cpes_affected": len(cpe_serials),
                "cpe_serials": cpe_serials,
                "avg_slope_kb": round(mean(slopes), 2),
                "max_slope_kb": round(max(slopes), 2),
            }
        )
    fleet_rows.sort(key=lambda r: (r["cpes_affected"], r["max_slope_kb"]), reverse=True)
    fleet_rows = fleet_rows[:FLEET_TOP_PROCESS_ROWS]
    return fleet_rows, dict(proc_slopes)


def _build_fleet_heatmap(
    proc_slopes: Dict[str, List[Tuple[str, float]]],
    fleet_rows: List[Dict[str, Any]],
    cpe_entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Capped process × CPE matrix; z = RSS trend slope (KB/step).
    
    Heatmap includes top processes and the CPEs where they leak most.
    Each process shows up to FLEET_HEATMAP_MAX_CPES (sorted by slope for that process).
    """
    if not fleet_rows or not cpe_entries:
        return {
            "processes": [],
            "cpes": [],
            "z": [],
            "heatmap_max_processes": FLEET_HEATMAP_MAX_PROCESSES,
            "heatmap_max_cpes": FLEET_HEATMAP_MAX_CPES,
        }

    procs = [r["process"] for r in fleet_rows[:FLEET_HEATMAP_MAX_PROCESSES]]
    
    # Build CPE set: for each displayed process, include CPEs where it has the worst slopes
    cpe_set: Set[str] = set()
    proc_cpe_data: Dict[str, List[Tuple[str, float]]] = {}
    
    for proc in procs:
        if proc not in proc_slopes:
            proc_cpe_data[proc] = []
            continue
        # For this process, sort CPEs by slope (worst first)
        pairs = proc_slopes[proc]
        sorted_pairs = sorted(pairs, key=lambda x: x[1], reverse=True)
        top_pairs = sorted_pairs[:FLEET_HEATMAP_MAX_CPES]
        proc_cpe_data[proc] = top_pairs
        for serial, _ in top_pairs:
            cpe_set.add(serial)
    
    if not cpe_set:
        return {
            "processes": [],
            "cpes": [],
            "z": [],
            "heatmap_max_processes": FLEET_HEATMAP_MAX_PROCESSES,
            "heatmap_max_cpes": FLEET_HEATMAP_MAX_CPES,
        }
    
    # Sort CPEs by pressure (worst first) for consistent column order
    cpe_pressure_map = {e["serial"]: e.get("pressure_score_0_100", 0) or 0 for e in cpe_entries}
    cpe_serials = sorted(cpe_set, key=lambda s: (-cpe_pressure_map.get(s, 0), s))
    
    cpe_idx = {s: i for i, s in enumerate(cpe_serials)}
    proc_idx = {p: i for i, p in enumerate(procs)}
    
    z = [[0.0 for _ in cpe_serials] for _ in procs]
    for proc, pairs in proc_cpe_data.items():
        i = proc_idx[proc]
        for serial, slope in pairs:
            j = cpe_idx.get(serial)
            if j is not None:
                z[i][j] = slope
    
    return {
        "processes": procs,
        "cpes": cpe_serials,
        "z": z,
        "heatmap_max_processes": FLEET_HEATMAP_MAX_PROCESSES,
        "heatmap_max_cpes": FLEET_HEATMAP_MAX_CPES,
    }


@selfheal_bp.route("/<project_id>/selfheal/cross-cpe-overview", methods=["GET"])
@jwt_required()
def cross_cpe_overview(project_id: str):
    """
    Get cross-CPE memory analytics summary.

    Query params:
        - force: If 1, force re-parse all CPEs

    Returns:
        Fleet-wide summary with CPE-level metrics, aggregated process leaks,
        and capped heatmap data (parallel parse for large projects).
    """
    user_id = get_user_id()
    project, error = _verify_project(project_id, user_id)
    if error:
        return error

    force = request.args.get("force") == "1"

    project_dir = _project_dir(user_id, project_id)
    if not project_dir.exists():
        return jsonify({"error": "Project directory not found"}), 404

    try:
        cpe_paths = [
            p
            for p in project_dir.iterdir()
            if p.is_dir()
            and not p.name.startswith(".")
            and p.name.lower() not in _CROSS_CPE_EXCLUDED_TOP_LEVEL_DIRS
        ]
        fingerprint = _cross_cpe_fingerprint(cpe_paths)
        if not force:
            cached_body = _load_fleet_cross_cpe_cache(project_dir, fingerprint)
            if cached_body is not None:
                return jsonify(cached_body), 200

        overview_stats = {
            "total_cpes": 0,
            "cpes_low_memory": 0,
            "cpes_high_rss": 0,
            "cpes_memory_pressure": 0,
            "cpes_no_swap": 0,
            "cpes_kernel_leak": 0,
        }

        results: List[Optional[Dict[str, Any]]] = []
        workers = min(CROSS_CPE_MAX_WORKERS, max(1, len(cpe_paths)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(_process_cross_cpe_one, p, force): p.name for p in cpe_paths
            }
            for fut in as_completed(futs):
                try:
                    results.append(fut.result())
                except Exception as exc:
                    logger.warning(
                        "Cross-CPE worker failed for %s: %s", futs.get(fut), exc
                    )
                    results.append(None)

        cpe_entries: List[Dict[str, Any]] = []
        trend_rows_per_cpe: List[Tuple[str, List[Dict[str, Any]]]] = []
        for r in results:
            if not r:
                continue
            entry = r["entry"]
            cpe_entries.append(entry)
            trend_rows_per_cpe.append((entry["serial"], r["trends"]))

            alerts = entry["alerts"]
            overview_stats["total_cpes"] += 1
            if "LOW_MEMORY" in alerts:
                overview_stats["cpes_low_memory"] += 1
            if entry.get("peak_memory_usage_pct", 0) > 90:
                overview_stats["cpes_high_rss"] += 1
            if "NO_SWAP" in alerts:
                overview_stats["cpes_no_swap"] += 1
            if "KERNEL_LEAK" in alerts:
                overview_stats["cpes_kernel_leak"] += 1
            if entry.get("sunreclaim_pct", 0) > 50:
                overview_stats["cpes_memory_pressure"] += 1

        status_priority = {
            "KERNEL_LEAK": 0,
            "OVERCOMMIT_RISK": 1,
            "NO_SWAP": 2,
            "LOW_MEMORY": 3,
            "WARNING": 4,
            "OK": 5,
        }
        cpe_entries.sort(
            key=lambda x: (
                status_priority.get(x["status"], 5),
                x["min_memory_available_kb"] or 999999999,
            )
        )

        fleet_process_leaks, proc_slopes = _aggregate_fleet_process_leaks(
            trend_rows_per_cpe
        )
        heatmap = _build_fleet_heatmap(proc_slopes, fleet_process_leaks, cpe_entries)

        body: Dict[str, Any] = {
            "overview": overview_stats,
            "cpes": cpe_entries,
            "fleet_process_leaks": fleet_process_leaks,
            "heatmap": heatmap,
            "fleet_meta": {
                "leak_slope_threshold_kb": FLEET_LEAK_SLOPE_THRESHOLD_KB,
                "top_process_limit": FLEET_TOP_PROCESS_ROWS,
            },
        }
        body.update(build_cross_cpe_summary(body))
        _persist_fleet_narrative_summary(project_dir, body, force)
        _save_fleet_cross_cpe_cache(project_dir, fingerprint, body)

        return jsonify(body), 200

    except Exception as e:
        logger.error(f"Failed to get cross-cpe overview: {e}")
        return jsonify({"error": str(e)}), 500
