"""
DuckDB Read-Only Query Layer for CPE Analytics

Provides a thin analytics API layer using DuckDB to query Parquet files
under issue_analysis directory. DuckDB is strictly read-only - no ingestion or ETL.

Key principles:
- Attach/read Parquet files directly from issue_analysis
- Serve ad-hoc analytics and filtered drill-downs
- SQL-backed API endpoints for Analytics UI
- No writes to Parquet - Polars owns all writes to SSOT
"""

import duckdb
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
import logging
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .data_layout import DataLayoutManager
from .fleet_summary import _find_processed_cpes

logger = logging.getLogger(__name__)


def _merge_live_project_counts(summary: Dict[str, Any], user_id: str, project_id: str) -> Dict[str, Any]:
    """Align total_devices with project CPE folders and devices_with_analytics with issue_analysis artifacts."""
    layout = DataLayoutManager(user_id, project_id)
    project_total = len(layout.list_cpes_with_rg_parquet())
    analyzed = len(_find_processed_cpes(layout))
    fs = dict(summary.get("fleet_statistics") or {})
    total_devices = (
        project_total if project_total > 0 else int(fs.get("total_devices", 0) or analyzed)
    )
    tr = int(fs.get("total_reboots", 0) or 0)
    new_fs = {
        **fs,
        "total_devices": total_devices,
        "devices_with_analytics": analyzed,
        "average_reboots_per_device": tr / max(total_devices, 1),
    }
    return {**summary, "fleet_statistics": new_fs}


class DuckDBQueryEngine:
    """Read-only DuckDB query engine for CPE analytics."""
    
    def __init__(self, user_id: str, project_id: str):
        self.user_id = str(user_id)
        self.project_id = project_id
        self.layout = DataLayoutManager(user_id, project_id)
        self.conn = None
        
    def __enter__(self):
        """Context manager entry - create connection."""
        self.conn = duckdb.connect(":memory:")
        self._setup_views()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection."""
        if self.conn:
            self.conn.close()
            
    def _setup_views(self):
        """Set up views for all available Parquet files."""
        issue_analysis_dir = self.layout.get_issue_analysis_dir()
        
        if not issue_analysis_dir.exists():
            logger.warning(f"Issue analysis directory not found: {issue_analysis_dir}")
            return
            
        # Create views for per-CPE data
        self._create_cpe_views()
        
        # Create views for fleet data
        self._create_fleet_views()
    
    def _create_cpe_views(self):
        """Create views for consolidated analytics Parquet (fallback: legacy partitions)."""
        file_types = [
            "reboot_features",
            "device_health",
            "signals",
            "error_templates",
            "sta_issues",
            "selfheal_insights",
        ]
        analytics_dir = self.layout.get_consolidated_analytics_dir()
        used_consolidated = False

        for file_type in file_types:
            consolidated = analytics_dir / f"{file_type}.parquet"
            if consolidated.is_file():
                path = str(consolidated)
                try:
                    self.conn.execute(f"""
                        CREATE VIEW {file_type}_view AS
                        SELECT * FROM read_parquet('{path}')
                    """)
                    logger.debug("Created view %s_view from consolidated file", file_type)
                    used_consolidated = True
                except Exception as e:
                    logger.warning("Failed consolidated view %s_view: %s", file_type, e)

        if used_consolidated:
            return

        cpes_dir = self.layout.get_issue_analysis_dir() / "cpes"
        if not cpes_dir.exists():
            return

        for file_type in file_types:
            parquet_paths = []
            for serial_dir in cpes_dir.glob("serial=*"):
                for date_dir in serial_dir.glob("date=*"):
                    parquet_file = date_dir / f"{file_type}.parquet"
                    if parquet_file.exists():
                        parquet_paths.append(str(parquet_file))

            if parquet_paths:
                paths_sql = ", ".join(f"'{path}'" for path in parquet_paths)
                try:
                    self.conn.execute(f"""
                        CREATE VIEW {file_type}_view AS
                        SELECT * FROM read_parquet([{paths_sql}])
                    """)
                    logger.debug(
                        "Created view %s_view with %s legacy files", file_type, len(parquet_paths)
                    )
                except Exception as e:
                    logger.warning("Failed to create view %s_view: %s", file_type, e)
    
    def _create_fleet_views(self):
        """Create views for fleet-level data (flat fleet dir, then legacy date=*)."""
        fleet_dir = self.layout.get_issue_analysis_dir() / "fleet"
        if not fleet_dir.exists():
            return

        flat = fleet_dir / "fleet_summary.parquet"
        if flat.is_file():
            try:
                self.conn.execute(f"""
                    CREATE VIEW fleet_summary_view AS
                    SELECT * FROM read_parquet('{flat}')
                """)
                logger.debug("Created fleet_summary_view from consolidated fleet parquet")
                return
            except Exception as e:
                logger.warning("Failed consolidated fleet_summary_view: %s", e)

        fleet_parquet_paths = []
        for date_dir in fleet_dir.glob("date=*"):
            parquet_file = date_dir / "fleet_summary.parquet"
            if parquet_file.exists():
                fleet_parquet_paths.append(str(parquet_file))

        if fleet_parquet_paths:
            paths_sql = ", ".join(f"'{path}'" for path in fleet_parquet_paths)
            try:
                self.conn.execute(f"""
                    CREATE VIEW fleet_summary_view AS
                    SELECT * FROM read_parquet([{paths_sql}])
                """)
                logger.debug(
                    "Created fleet_summary_view with %s legacy files", len(fleet_parquet_paths)
                )
            except Exception as e:
                logger.warning("Failed to create fleet_summary_view: %s", e)
    
    def query(self, sql: str) -> List[Dict[str, Any]]:
        """
        Execute a SQL query and return results as list of dictionaries.
        
        Args:
            sql: SQL query string
            
        Returns:
            List of dictionaries representing query results
        """
        if not self.conn:
            raise RuntimeError("DuckDB connection not initialized. Use as context manager.")
        
        try:
            result = self.conn.execute(sql).fetchall()
            columns = [desc[0] for desc in self.conn.description]
            
            return [dict(zip(columns, row)) for row in result]
            
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            raise
    
    def get_available_views(self) -> List[str]:
        """Get list of available views."""
        if not self.conn:
            raise RuntimeError("DuckDB connection not initialized. Use as context manager.")
        
        result = self.conn.execute("SHOW TABLES").fetchall()
        return [row[0] for row in result]
    
    def describe_view(self, view_name: str) -> List[Dict[str, str]]:
        """Get schema information for a view."""
        if not self.conn:
            raise RuntimeError("DuckDB connection not initialized. Use as context manager.")
        
        result = self.conn.execute(f"DESCRIBE {view_name}").fetchall()
        return [
            {"column_name": row[0], "column_type": row[1], "null": row[2]}
            for row in result
        ]


def _load_latest_fleet_summary_json(user_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    """UI expects nested shape from fleet_summary.json; prefer this over flat Parquet rows."""
    layout = DataLayoutManager(user_id, project_id)
    fleet_dir = layout.get_issue_analysis_dir() / "fleet"
    if not fleet_dir.is_dir():
        return None
    flat_json = fleet_dir / "fleet_summary.json"
    if flat_json.is_file():
        with open(flat_json, encoding="utf-8") as f:
            return json.load(f)
    date_dirs = sorted(
        [p for p in fleet_dir.glob("date=*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    for date_dir in date_dirs:
        json_file = date_dir / "fleet_summary.json"
        if json_file.exists():
            with open(json_file, encoding="utf-8") as f:
                return json.load(f)
    return None


def _fleet_summary_from_flat_parquet_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map one-row fleet_summary.parquet schema to the nested API shape the frontend uses."""
    total_devices = int(row.get("total_devices") or 0)
    total_reboots = int(row.get("total_reboots") or 0)
    return {
        "generation_date": str(row.get("generation_date") or ""),
        "fleet_statistics": {
            "total_devices": total_devices,
            "total_reboots": total_reboots,
            "average_reboots_per_device": total_reboots / max(total_devices, 1),
        },
        "reboot_analysis": {
            "reasons_distribution": {},
            "most_common_reason": row.get("most_common_reboot_reason") or None,
        },
        "firmware_analysis": {
            "version_distribution": {},
            "unique_versions": int(row.get("unique_firmware_versions") or 0),
            "device_serials_with_empty_firmware": [],
        },
        "error_analysis": {
            "top_templates_by_domain": {},
            "total_error_instances": int(row.get("total_error_instances") or 0),
        },
        "device_health": {
            "high_risk_devices": [],
            "high_risk_count": int(row.get("high_risk_device_count") or 0),
        },
        "module_graph_version": str(row.get("module_graph_version") or "unknown"),
    }


def get_fleet_summary(user_id: str, project_id: str) -> Dict[str, Any]:
    """
    Get fleet summary for the Analytics UI: nested JSON (same as fleet_summary.json).

    Prefer fleet_summary.json on disk; if missing (e.g. deleted), rebuild from analytics
    Parquet when possible; else DuckDB over fleet_summary Parquet.
    """
    nested = _load_latest_fleet_summary_json(user_id, project_id)
    if nested is None:
        from logai.analytics.fleet_summary import generate_fleet_summary

        gen = generate_fleet_summary(user_id, project_id)
        if gen.get("status") == "success" and gen.get("summary") is not None:
            nested = gen["summary"]

    if nested is not None:
        return _merge_live_project_counts(nested, user_id, project_id)

    with DuckDBQueryEngine(user_id, project_id) as db:
        views = db.get_available_views()
        if "fleet_summary_view" not in views:
            return {"error": "No fleet summary data available"}

        result = db.query("""
            SELECT * FROM fleet_summary_view
            ORDER BY generation_date DESC
            LIMIT 1
        """)
        if not result:
            return {"error": "No fleet summary data found"}
        row = result[0]
        if "fleet_statistics" in row:
            return _merge_live_project_counts(row, user_id, project_id)
        return _merge_live_project_counts(
            _fleet_summary_from_flat_parquet_row(row), user_id, project_id
        )


def get_sta_issues_analysis(
    user_id: str,
    project_id: str,
    device_serial: Optional[str] = None,
    issue_key: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """
    Per-STA WiFi protocol issues from consolidated ``sta_issues.parquet``.
    """
    with DuckDBQueryEngine(user_id, project_id) as db:
        views = db.get_available_views()

        if "sta_issues_view" not in views:
            return []

        def esc(s: str) -> str:
            return str(s).replace("'", "''")

        filters: List[str] = []
        if device_serial:
            filters.append(f"device_serial = '{esc(device_serial)}'")
        if issue_key:
            filters.append(f"issue_key = '{esc(issue_key)}'")
        where = (" WHERE " + " AND ".join(filters)) if filters else ""

        lim = max(1, min(int(limit), 10_000))
        result = db.query(f"""
            SELECT *
            FROM sta_issues_view
            {where}
            ORDER BY window_start DESC
            LIMIT {lim}
        """)
        return result


# Issue time window vs reboot instant: treat deauth / storms during radio reset as ambiguous.
_REBOOT_BEFORE = timedelta(seconds=120)
_REBOOT_AFTER = timedelta(seconds=600)
_MAX_OVERLAP_REBOOT_HINTS = 5


def _parse_issue_ts(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _issue_window_overlaps_reboot(
    window_start: Optional[str],
    window_end: Optional[str],
    reboot_times: List[datetime],
) -> Tuple[bool, List[str]]:
    w0 = _parse_issue_ts(window_start)
    w1 = _parse_issue_ts(window_end) or w0
    if w0 is None and w1 is None:
        return False, []
    if w0 is None:
        w0 = w1
    if w1 is None:
        w1 = w0
    if w1 < w0:
        w0, w1 = w1, w0
    hints: List[str] = []
    for rb in reboot_times:
        r0 = rb - _REBOOT_BEFORE
        r1 = rb + _REBOOT_AFTER
        if w0 <= r1 and w1 >= r0:
            rb_utc = rb if rb.tzinfo else rb.replace(tzinfo=timezone.utc)
            hints.append(rb_utc.astimezone(timezone.utc).isoformat())
            if len(hints) >= _MAX_OVERLAP_REBOOT_HINTS:
                break
    return (len(hints) > 0), hints


def get_sta_issues_grouped_analysis(
    user_id: str,
    project_id: str,
    device_serial: Optional[str] = None,
    issue_key: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """
    One row per ``device_serial`` + ``issue_key`` with a list of STA MACs (local OUI vendor).

    ``may_overlap_reboot`` is true when the issue time window intersects an expanded reboot
    instant (typical radio-down / deauth noise vs real client problems).
    """
    from api.routes.utilities import (
        get_oui,
        is_locally_administered,
        lookup_vendor_local,
        normalize_mac,
    )

    def _vendor_for_mac(mac: str) -> Optional[str]:
        try:
            normalized = normalize_mac(mac)
        except ValueError:
            return None
        if is_locally_administered(normalized):
            return "Locally administered"
        oui = get_oui(normalized)
        return lookup_vendor_local(oui)

    with DuckDBQueryEngine(user_id, project_id) as db:
        views = db.get_available_views()
        if "sta_issues_view" not in views:
            return []

        def esc(s: str) -> str:
            return str(s).replace("'", "''")

        filters: List[str] = []
        if device_serial:
            filters.append(f"device_serial = '{esc(device_serial)}'")
        if issue_key:
            filters.append(f"issue_key = '{esc(issue_key)}'")
        where = (" WHERE " + " AND ".join(filters)) if filters else ""

        flat_lim = 10_000
        flat = db.query(f"""
            SELECT *
            FROM sta_issues_view
            {where}
            ORDER BY window_start DESC
            LIMIT {flat_lim}
        """)
        if not flat:
            return []

        groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in flat:
            ds = str(r.get("device_serial") or "").strip()
            ik = str(r.get("issue_key") or "").strip()
            if not ds or not ik:
                continue
            key = (ds, ik)
            if key not in groups:
                groups[key] = {
                    "device_serial": ds,
                    "issue_key": ik,
                    "category": str(r.get("category") or ""),
                    "severity": str(r.get("severity") or ""),
                    "sta_macs": set(),
                    "total_occurrence_count": 0,
                    "window_starts": [],
                    "window_ends": [],
                }
            g = groups[key]
            sm = str(r.get("sta_mac") or "").strip()
            if sm:
                g["sta_macs"].add(sm)
            try:
                g["total_occurrence_count"] += int(r.get("occurrence_count") or 1)
            except (TypeError, ValueError):
                g["total_occurrence_count"] += 1
            ws = r.get("window_start")
            we = r.get("window_end")
            if ws:
                g["window_starts"].append(str(ws))
            if we:
                g["window_ends"].append(str(we))

        serials = list({k[0] for k in groups})
        reboot_by_serial: Dict[str, List[datetime]] = defaultdict(list)
        if "reboot_features_view" in views and serials:
            in_list = ",".join(f"'{esc(s)}'" for s in serials)
            rrows = db.query(f"""
                SELECT device_serial, timestamp
                FROM reboot_features_view
                WHERE device_serial IN ({in_list})
                ORDER BY device_serial, timestamp
            """)
            for rr in rrows or []:
                ds = str(rr.get("device_serial") or "").strip()
                ts_raw = rr.get("timestamp")
                if not ds or ts_raw is None:
                    continue
                if isinstance(ts_raw, datetime):
                    dt = ts_raw
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = _parse_issue_ts(str(ts_raw))
                if dt is not None:
                    reboot_by_serial[ds].append(dt)

        out: List[Dict[str, Any]] = []
        for key in sorted(groups.keys(), key=lambda x: (x[0], x[1])):
            g = groups[key]
            starts = g["window_starts"]
            ends = g["window_ends"]
            ws_min = min(starts) if starts else ""
            we_max = max(ends) if ends else ""
            rb_times = reboot_by_serial.get(g["device_serial"], [])
            near, hint_times = _issue_window_overlaps_reboot(ws_min, we_max, rb_times)
            sta_sorted = sorted(g["sta_macs"])
            sta_list = [
                {
                    "sta_mac": mac,
                    "vendor": _vendor_for_mac(mac),
                }
                for mac in sta_sorted
            ]
            out.append(
                {
                    "device_serial": g["device_serial"],
                    "issue_key": g["issue_key"],
                    "category": g["category"],
                    "severity": g["severity"],
                    "sta_count": len(sta_sorted),
                    "total_occurrence_count": g["total_occurrence_count"],
                    "window_start": ws_min,
                    "window_end": we_max,
                    "may_overlap_reboot": near,
                    "overlapping_reboot_times": hint_times,
                    "sta_list": sta_list,
                }
            )

        group_cap = max(1, min(int(limit), 2000))
        return out[:group_cap]


def get_selfheal_insights_analysis(
    user_id: str,
    project_id: str,
    device_serial: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """
    SelfHeal-derived per-CPE signals (CPU, process restarts, RSS trend, slab/overcommit).

    Rows come from consolidated ``selfheal_insights.parquet`` (Polars ETL). JSON columns
    are expanded to ``tags`` and ``detail_lines`` lists for the UI.
    """
    with DuckDBQueryEngine(user_id, project_id) as db:
        views = db.get_available_views()
        if "selfheal_insights_view" not in views:
            return []

        def esc(s: str) -> str:
            return str(s).replace("'", "''")

        filters: List[str] = []
        if device_serial:
            filters.append(f"device_serial = '{esc(device_serial)}'")
        where = (" WHERE " + " AND ".join(filters)) if filters else ""

        lim = max(1, min(int(limit), 2000))
        rows = db.query(f"""
            SELECT *
            FROM selfheal_insights_view
            {where}
            ORDER BY device_serial
            LIMIT {lim}
        """)

        out: List[Dict[str, Any]] = []
        for r in rows or []:
            rec = dict(r)
            try:
                rec["tags"] = json.loads(rec.get("tags_json") or "[]")
            except json.JSONDecodeError:
                rec["tags"] = []
            if not isinstance(rec["tags"], list):
                rec["tags"] = []
            try:
                rec["detail_lines"] = json.loads(rec.get("detail_lines_json") or "[]")
            except json.JSONDecodeError:
                rec["detail_lines"] = []
            if not isinstance(rec["detail_lines"], list):
                rec["detail_lines"] = []
            out.append(rec)
        return out


def execute_custom_query(user_id: str, project_id: str, 
                        sql_query: str) -> Dict[str, Any]:
    """
    Execute a custom SQL query with safety restrictions.
    
    Args:
        user_id: User ID
        project_id: Project ID
        sql_query: SQL query to execute
        
    Returns:
        Query results or error message
    """
    # Basic safety checks - only allow SELECT statements
    sql_lower = sql_query.strip().lower()
    if not sql_lower.startswith("select"):
        return {"error": "Only SELECT queries are allowed"}
    
    # Prevent potentially dangerous operations
    forbidden_keywords = ["drop", "create", "insert", "update", "delete", "alter"]
    if any(keyword in sql_lower for keyword in forbidden_keywords):
        return {"error": "Query contains forbidden keywords"}
    
    try:
        with DuckDBQueryEngine(user_id, project_id) as db:
            result = db.query(sql_query)
            return {"success": True, "data": result}
            
    except Exception as e:
        return {"error": f"Query execution failed: {str(e)}"}


def get_analytics_schema(user_id: str, project_id: str) -> Dict[str, Any]:
    """
    Get schema information for all available analytics views.
    
    Args:
        user_id: User ID
        project_id: Project ID
        
    Returns:
        Schema information for all views
    """
    with DuckDBQueryEngine(user_id, project_id) as db:
        views = db.get_available_views()
        schema_info = {}
        
        for view in views:
            try:
                schema_info[view] = db.describe_view(view)
            except Exception as e:
                logger.warning(f"Failed to describe view {view}: {e}")
        
        return schema_info