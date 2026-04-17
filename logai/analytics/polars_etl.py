"""
Polars ETL for per-CPE analytics processing.

Implements polars_etl_per_cpe function according to the plan:
- Load: *_rg.parquet, raw_selfheal_cache.parquet (JSON migrated), raw_telemetry_cache.json, device/version/reboot JSON
- Transform: join_asof temporal alignment, module graph enrichment, compute signals
- Generate: reboot_features.parquet, device_health.parquet, signals.parquet, error_templates.parquet
"""

import polars as pl
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
import logging

from .consolidated_io import ensure_migrated_from_legacy, upsert_replace_device_serial
from .data_layout import DataLayoutManager
from .module_graph import get_module_graph
from .wifi_protocol import run_wifi_sta_issues
from logai.analytics.selfheal.cache_io import load_raw_selfheal_dict, migrate_json_cache_if_present
from logai.analytics.selfheal.insights import build_selfheal_insights_dataframe

logger = logging.getLogger(__name__)


def _cpe_identity_serial(device_info: Dict[str, Any], folder_serial: str) -> str:
    """
    Prefer device_info['serial'] when non-empty; otherwise the project folder name.

    device_info often contains "serial": "" — dict.get("serial", folder_serial) would
    incorrectly return "" and break consolidated analytics keys.
    """
    raw = device_info.get("serial")
    if raw is None:
        return folder_serial
    s = str(raw).strip()
    return s if s else folder_serial


def polars_etl_per_cpe(user_id: str, project_id: str, serial: str, 
                      processing_date: str = None) -> Dict[str, Any]:
    """
    Main Polars ETL function for per-CPE analytics processing.
    
    Args:
        user_id: User ID
        project_id: Project ID
        serial: CPE serial number
        processing_date: Date string (YYYY-MM-DD), defaults to today
    
    Returns:
        Dictionary with processing results and output paths
    """
    if processing_date is None:
        processing_date = datetime.now().strftime("%Y-%m-%d")
    
    logger.info(f"Starting Polars ETL for CPE {serial} (date={processing_date})")
    
    # Initialize data layout manager
    layout = DataLayoutManager(user_id, project_id)
    ensure_migrated_from_legacy(layout)

    # Load module graph
    module_graph = get_module_graph()

    try:
        # 1. LOAD phase
        logger.info(f"Loading data for CPE {serial}")
        
        # Load parquet files
        parquet_data = _load_parquet_files(layout, serial, module_graph)
        
        # Load cache JSON files
        device_info = _load_device_info(layout, serial)
        version_info = _load_version_info(layout, serial) 
        reboots = _load_reboots(layout, serial)
        selfheal_data = _load_selfheal_data(layout, serial)
        telemetry_data = _load_telemetry_data(layout, serial)
        
        # 2. TRANSFORM phase
        logger.info(f"Transforming data for CPE {serial}")
        
        # Create time-aligned datasets
        aligned_data = _perform_temporal_alignment(
            parquet_data, selfheal_data, telemetry_data, reboots
        )
        
        # Compute derived signals
        signals = _compute_signals(aligned_data, selfheal_data, telemetry_data)
        
        # 3. GENERATE & SAVE phase
        logger.info(f"Generating consolidated analytics for CPE {serial}")

        cpe_serial = _cpe_identity_serial(device_info, serial)
        layout.ensure_directories(layout.get_consolidated_analytics_dir())

        results = {}

        reboot_features = _generate_reboot_features(
            reboots, aligned_data, device_info, cpe_serial
        )
        rb_path = layout.consolidated_parquet_path("reboot_features")
        upsert_replace_device_serial(rb_path, reboot_features, cpe_serial)
        results["reboot_features"] = {"path": str(rb_path), "rows": len(reboot_features)}

        device_health = _generate_device_health(
            device_info, version_info, selfheal_data, processing_date, cpe_serial
        )
        dh_path = layout.consolidated_parquet_path("device_health")
        upsert_replace_device_serial(dh_path, device_health, cpe_serial)
        results["device_health"] = {"path": str(dh_path), "rows": len(device_health)}

        signals_df = _generate_signals_parquet(signals, processing_date, cpe_serial)
        sig_path = layout.consolidated_parquet_path("signals")
        upsert_replace_device_serial(sig_path, signals_df, cpe_serial)
        results["signals"] = {"path": str(sig_path), "rows": len(signals_df)}

        error_templates = _generate_error_templates(
            parquet_data, module_graph, processing_date, cpe_serial
        )
        et_path = layout.consolidated_parquet_path("error_templates")
        upsert_replace_device_serial(et_path, error_templates, cpe_serial)
        results["error_templates"] = {"path": str(et_path), "rows": len(error_templates)}

        sta_issues, wifi_issue_stats = run_wifi_sta_issues(
            layout,
            serial,
            device_info,
            processing_date,
            cpe_serial,
            write_labeled_debug=False,
        )
        si_path = layout.consolidated_parquet_path("sta_issues")
        upsert_replace_device_serial(si_path, sta_issues, cpe_serial)
        results["sta_issues"] = {
            "path": str(si_path),
            "rows": sta_issues.height,
            "wifi_stats": wifi_issue_stats,
        }

        sh_insights = build_selfheal_insights_dataframe(
            selfheal_data,
            processing_date,
            cpe_serial,
            reboot_events=reboots,
        )
        sh_path = layout.consolidated_parquet_path("selfheal_insights")
        upsert_replace_device_serial(sh_path, sh_insights, cpe_serial)
        results["selfheal_insights"] = {
            "path": str(sh_path),
            "rows": sh_insights.height,
        }

        logger.info(f"Successfully completed Polars ETL for CPE {serial}")
        
        return {
            "status": "success",
            "serial": serial,
            "processing_date": processing_date,
            "outputs": results
        }
        
    except Exception as e:
        logger.error(f"Error in Polars ETL for CPE {serial}: {e}", exc_info=True)
        return {
            "status": "error", 
            "serial": serial,
            "error": str(e)
        }


def _load_parquet_files(layout: DataLayoutManager, serial: str, module_graph) -> Dict[str, pl.DataFrame]:
    """Load all *_rg.parquet files for a CPE."""
    parquet_files = layout.get_cpe_parquet_files(serial)
    parquet_data = {}
    
    for domain, file_path in parquet_files.items():
        try:
            df = pl.read_parquet(file_path)
            if len(df) > 0:
                # Add domain column and module graph enrichment
                df = df.with_columns(
                    pl.lit(domain).alias("domain")
                )
                parquet_data[domain] = df
                logger.debug(f"Loaded {len(df)} rows from {domain}_rg.parquet")
            else:
                logger.debug(f"Empty parquet file: {domain}_rg.parquet")
        except Exception as e:
            logger.warning(f"Failed to load {domain}_rg.parquet: {e}")
    
    return parquet_data


def _load_device_info(layout: DataLayoutManager, serial: str) -> Dict[str, Any]:
    """Load device info cache."""
    cache_files = layout.get_cpe_cache_files(serial)
    if "device_info" in cache_files:
        with open(cache_files["device_info"]) as f:
            return json.load(f)
    return {}


def _load_version_info(layout: DataLayoutManager, serial: str) -> Dict[str, Any]:
    """Load version info cache."""
    cache_files = layout.get_cpe_cache_files(serial)
    if "version" in cache_files:
        with open(cache_files["version"]) as f:
            return json.load(f)
    return {}


def _load_reboots(layout: DataLayoutManager, serial: str) -> List[Dict[str, Any]]:
    """Load reboots cache."""
    cache_files = layout.get_cpe_cache_files(serial)
    if "reboots" in cache_files:
        with open(cache_files["reboots"]) as f:
            data = json.load(f)
            return data.get("reboots", [])
    return []


def _load_selfheal_data(layout: DataLayoutManager, serial: str) -> Dict[str, Any]:
    """Load raw selfheal cache (Parquet payload; migrate legacy JSON on disk)."""
    cpe_dir = layout.get_cpe_source_dir(serial)
    migrate_json_cache_if_present(cpe_dir)
    data = load_raw_selfheal_dict(cpe_dir)
    return data if data else {}


def _load_telemetry_data(layout: DataLayoutManager, serial: str) -> Dict[str, Any]:
    """Load raw telemetry cache."""
    cache_files = layout.get_cpe_cache_files(serial)
    if "raw_telemetry" in cache_files:
        with open(cache_files["raw_telemetry"]) as f:
            return json.load(f)
    return {}


def _perform_temporal_alignment(parquet_data: Dict[str, pl.DataFrame],
                               selfheal_data: Dict[str, Any],
                               telemetry_data: Dict[str, Any], 
                               reboots: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Perform temporal alignment using join_asof."""
    
    # Create unified error timeline from parquet data
    error_timeline = []
    for domain, df in parquet_data.items():
        if len(df) > 0:
            error_timeline.append(
                df.select([
                    "timestamp",
                    "template", 
                    "domain",
                    pl.lit("error").alias("event_type")
                ])
            )
    
    if error_timeline:
        error_df = pl.concat(error_timeline).sort("timestamp")
    else:
        error_df = pl.DataFrame({
            "timestamp": [], 
            "template": [],
            "domain": [],
            "event_type": []
        })
    
    # Create selfheal timeline
    selfheal_snapshots = selfheal_data.get("snapshots", [])
    if selfheal_snapshots:
        selfheal_df = pl.DataFrame([
            {
                "timestamp": snapshot["timestamp"],
                "mem_available": snapshot.get("mem_available", 0),
                "mem_total": snapshot.get("mem_total", 0),
                "event_type": "selfheal"
            }
            for snapshot in selfheal_snapshots
        ])
        selfheal_df = selfheal_df.with_columns(
            pl.col("timestamp").str.to_datetime()
        )
    else:
        selfheal_df = pl.DataFrame({
            "timestamp": [],
            "mem_available": [],
            "mem_total": [],
            "event_type": []
        })
    
    # Create telemetry timeline
    telemetry_reports = telemetry_data.get("reports", [])
    if telemetry_reports:
        telemetry_df = pl.DataFrame([
            {
                "timestamp": report.get("time", report.get("log_timestamp", "")),
                "uptime": report.get("uptime", 0),
                "event_type": "telemetry"
            }
            for report in telemetry_reports
            if report.get("parse_ok", True)
        ])
        if len(telemetry_df) > 0:
            telemetry_df = telemetry_df.with_columns(
                pl.col("timestamp").str.to_datetime()
            )
    else:
        telemetry_df = pl.DataFrame({
            "timestamp": [],
            "uptime": [],
            "event_type": []
        })
    
    # Create reboot timeline
    if reboots:
        reboot_df = pl.DataFrame([
            {
                "timestamp": reboot["timestamp"],
                "reason": reboot.get("reason", ""),
                "reboot_type": reboot.get("reboot_type", ""),
                "event_type": "reboot"
            }
            for reboot in reboots
        ])
        reboot_df = reboot_df.with_columns(
            pl.col("timestamp").str.to_datetime()
        )
    else:
        reboot_df = pl.DataFrame({
            "timestamp": [],
            "reason": [],
            "reboot_type": [],
            "event_type": []
        })
    
    return {
        "errors": error_df,
        "selfheal": selfheal_df,
        "telemetry": telemetry_df,
        "reboots": reboot_df
    }


def _compute_signals(aligned_data: Dict[str, Any], 
                    selfheal_data: Dict[str, Any],
                    telemetry_data: Dict[str, Any]) -> Dict[str, Any]:
    """Compute derived signals like memory pressure, CPU spikes, Wi-Fi instability."""
    
    signals = {}
    
    # Memory pressure from selfheal data
    if selfheal_data.get("snapshots"):
        mem_pressures = []
        snapshots = selfheal_data["snapshots"]
        
        for snapshot in snapshots:
            mem_total = snapshot.get("mem_total", 1)
            mem_available = snapshot.get("mem_available", 0)
            
            if mem_total > 0:
                mem_usage_pct = (mem_total - mem_available) / mem_total * 100
                mem_pressures.append({
                    "timestamp": snapshot["timestamp"],
                    "memory_pressure_pct": mem_usage_pct,
                    "memory_available_kb": mem_available
                })
        
        signals["memory_pressure"] = mem_pressures
    
    # CPU usage from selfheal data
    cpu_samples = selfheal_data.get("cpu_samples", [])
    if cpu_samples:
        signals["cpu_usage"] = [
            {
                "timestamp": sample.get("timestamp", ""),
                "cpu_usage_pct": sample.get("cpu_usage", 0)
            }
            for sample in cpu_samples
        ]
    
    # Wi-Fi instability from telemetry (simplified)
    wifi_signals = []
    if telemetry_data.get("reports"):
        for report in telemetry_data["reports"]:
            if not report.get("parse_ok", True):
                continue
            
            fields = report.get("fields", {})
            
            # Look for Wi-Fi related metrics
            wifi_errors = 0
            for field_name, field_value in fields.items():
                if "wifi" in field_name.lower() and "error" in field_name.lower():
                    try:
                        wifi_errors += int(field_value)
                    except:
                        pass
            
            if wifi_errors > 0:
                wifi_signals.append({
                    "timestamp": report.get("time", report.get("log_timestamp", "")),
                    "wifi_errors": wifi_errors
                })
    
    signals["wifi_instability"] = wifi_signals
    
    return signals


def _generate_reboot_features(
    reboots: List[Dict[str, Any]],
    aligned_data: Dict[str, Any],
    device_info: Dict[str, Any],
    device_serial: str,
) -> pl.DataFrame:
    """Generate reboot features parquet."""

    if not reboots:
        return pl.DataFrame({
            "timestamp": [],
            "reason": [],
            "reboot_type": [],
            "is_short_reboot": [],
            "errors_before_reboot": [],
            "device_serial": [],
        })

    reboot_features = []
    serial = device_serial
    
    for reboot in reboots:
        # Count errors in the 15 minutes before reboot
        reboot_time = datetime.fromisoformat(reboot["timestamp"].replace("Z", ""))
        errors_before = 0
        
        if len(aligned_data.get("errors", pl.DataFrame())) > 0:
            errors_df = aligned_data["errors"]
            # Filter errors within 15 minutes before reboot
            errors_before_df = errors_df.filter(
                pl.col("timestamp") <= reboot_time
            ).filter(
                pl.col("timestamp") >= reboot_time.replace(minute=max(0, reboot_time.minute - 15))
            )
            errors_before = len(errors_before_df)
        
        reboot_features.append({
            "timestamp": reboot["timestamp"],
            "reason": reboot.get("reason", ""),
            "reboot_type": reboot.get("reboot_type", ""),
            "is_short_reboot": reboot.get("is_short_reboot", False),
            "errors_before_reboot": errors_before,
            "device_serial": serial
        })
    
    return pl.DataFrame(reboot_features)


def _generate_device_health(
    device_info: Dict[str, Any],
    version_info: Dict[str, Any],
    selfheal_data: Dict[str, Any],
    processing_date: str,
    device_serial: str,
) -> pl.DataFrame:
    """Generate device health parquet."""

    summary = selfheal_data.get("summary", {})

    health_data = [{
        "device_serial": device_serial,
        "model": device_info.get("model", ""),
        "manufacturer": device_info.get("manufacturer", ""),
        "firmware_version": device_info.get("version", ""),
        "sdk_version": device_info.get("sdk_version", ""),
        "wan_type": device_info.get("wan_type", ""),
        "last_reboot_reason": device_info.get("last_reboot_reason", ""),
        "peak_memory_usage_pct": summary.get("peak_memory_usage_pct", 0),
        "avg_memory_usage_pct": 100 - summary.get("mem_available_avg_pct", 0),
        "peak_cpu_usage_pct": summary.get("peak_cpu_usage_pct", 0),
        "avg_cpu_usage_pct": summary.get("avg_cpu_usage_pct", 0),
        "processing_date": processing_date
    }]
    
    return pl.DataFrame(health_data)


def _generate_signals_parquet(
    signals: Dict[str, Any], processing_date: str, device_serial: str
) -> pl.DataFrame:
    """Generate signals parquet (includes device_serial for consolidated store)."""

    all_signals = []

    for signal in signals.get("memory_pressure", []):
        all_signals.append({
            "timestamp": signal["timestamp"],
            "signal_type": "memory_pressure",
            "signal_value": signal["memory_pressure_pct"],
            "processing_date": processing_date,
            "device_serial": device_serial,
        })

    for signal in signals.get("cpu_usage", []):
        all_signals.append({
            "timestamp": signal["timestamp"],
            "signal_type": "cpu_usage",
            "signal_value": signal["cpu_usage_pct"],
            "processing_date": processing_date,
            "device_serial": device_serial,
        })

    for signal in signals.get("wifi_instability", []):
        all_signals.append({
            "timestamp": signal["timestamp"],
            "signal_type": "wifi_instability",
            "signal_value": signal["wifi_errors"],
            "processing_date": processing_date,
            "device_serial": device_serial,
        })

    if not all_signals:
        return pl.DataFrame({
            "timestamp": [],
            "signal_type": [],
            "signal_value": [],
            "processing_date": [],
            "device_serial": [],
        })

    return pl.DataFrame(all_signals)


def _generate_error_templates(
    parquet_data: Dict[str, pl.DataFrame],
    module_graph,
    processing_date: str,
    device_serial: str,
) -> pl.DataFrame:
    """Generate error templates parquet with module graph enrichment."""

    if not parquet_data:
        return pl.DataFrame({
            "timestamp": [],
            "domain": [],
            "template": [],
            "loglines": [],
            "module_enrichment": [],
            "processing_date": [],
            "device_serial": [],
        })
    
    # Combine all domains
    enriched_templates = []
    
    for domain, df in parquet_data.items():
        if len(df) > 0:
            # Get module enrichment for this domain
            modules = module_graph.get_modules_for_domain(domain)
            module_names = [m.display_name for m in modules]
            
            # Add to enriched templates
            df_with_enrichment = df.with_columns([
                pl.lit(", ".join(module_names)).alias("module_enrichment"),
                pl.lit(processing_date).alias("processing_date"),
                pl.lit(device_serial).alias("device_serial"),
            ])
            
            enriched_templates.append(df_with_enrichment)
    
    if enriched_templates:
        return pl.concat(enriched_templates)
    else:
        return pl.DataFrame({
            "timestamp": [],
            "domain": [],
            "template": [],
            "loglines": [],
            "module_enrichment": [],
            "processing_date": [],
            "device_serial": [],
        })