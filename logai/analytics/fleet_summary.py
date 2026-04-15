"""
Fleet Summary Generation

Implements finalize_project_analytics function according to the plan:
- Single Polars pass over all per-CPE outputs in issue_analysis
- Generates fleet_summary.parquet and fleet_summary.json
- Aggregates reboot counts, root causes, firmware distribution, etc.
"""

import polars as pl
import json
from datetime import datetime
from typing import Dict, Any, List
import logging

from .consolidated_io import ensure_migrated_from_legacy, load_legacy_partitioned_parquets
from .data_layout import DataLayoutManager
from .module_graph import get_module_graph

logger = logging.getLogger(__name__)


def generate_fleet_summary(user_id: str, project_id: str, 
                         processing_date: str = None) -> Dict[str, Any]:
    """
    Generate fleet-level summary from all per-CPE analytics data.
    
    Args:
        user_id: User ID
        project_id: Project ID
        processing_date: Date string (YYYY-MM-DD), defaults to today
    
    Returns:
        Dictionary with fleet summary results and output paths
    """
    if processing_date is None:
        processing_date = datetime.now().strftime("%Y-%m-%d")
    
    logger.info(
        f"Starting fleet summary generation for project {project_id} (date={processing_date})"
    )

    layout = DataLayoutManager(user_id, project_id)
    ensure_migrated_from_legacy(layout)
    module_graph = get_module_graph()

    try:
        fleet_data = _load_and_aggregate_fleet_data(layout, module_graph)
        cpe_serials = _find_processed_cpes(layout)
        rg_serials = layout.list_cpes_with_rg_parquet()
        logger.info(
            "Fleet inputs: %s CPEs with analytics rows, %s with RG parquet",
            len(cpe_serials),
            len(rg_serials),
        )

        if not cpe_serials and not rg_serials:
            logger.warning("No analytics Parquet and no CPE directories with *_rg.parquet")
            return {"status": "no_data", "cpe_count": 0}

        fleet_dir = layout.get_fleet_dir()
        layout.ensure_directories(fleet_dir)

        fleet_parquet_path = layout.fleet_summary_parquet_path()
        fleet_data["summary_df"].write_parquet(fleet_parquet_path)

        fleet_json_path = layout.fleet_summary_json_path()
        with open(fleet_json_path, "w", encoding="utf-8") as f:
            json.dump(fleet_data["summary_json"], f, indent=2)

        logger.info("Fleet summary saved to %s", fleet_dir)

        cpe_count = len(cpe_serials) if cpe_serials else len(rg_serials)
        return {
            "status": "success",
            "processing_date": processing_date,
            "cpe_count": cpe_count,
            "fleet_summary_parquet": str(fleet_parquet_path),
            "fleet_summary_json": str(fleet_json_path),
            "summary": fleet_data["summary_json"],
        }
        
    except Exception as e:
        logger.error(f"Error generating fleet summary: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


def _find_processed_cpes(layout: DataLayoutManager) -> List[str]:
    """Serials present in consolidated device_health, or legacy partitioned layout."""
    dh_cons = layout.consolidated_parquet_path("device_health")
    if dh_cons.is_file():
        df = pl.read_parquet(dh_cons)
        if "device_serial" in df.columns and len(df) > 0:
            return sorted(df["device_serial"].unique().to_list())
        return []

    cpes_dir = layout.get_issue_analysis_dir() / "cpes"
    if not cpes_dir.is_dir():
        return []

    serials = []
    for serial_dir in cpes_dir.iterdir():
        if serial_dir.is_dir() and serial_dir.name.startswith("serial="):
            serial = serial_dir.name.replace("serial=", "")
            for date_dir in serial_dir.iterdir():
                if date_dir.is_dir() and date_dir.name.startswith("date="):
                    expected_files = [
                        "reboot_features.parquet",
                        "device_health.parquet",
                        "signals.parquet",
                        "error_templates.parquet",
                    ]
                    if any((date_dir / f).exists() for f in expected_files):
                        serials.append(serial)
                        break

    return sorted(serials)


def _load_and_aggregate_fleet_data(
    layout: DataLayoutManager,
    module_graph,
) -> Dict[str, Any]:
    """Load consolidated analytics Parquet files (or legacy partitions)."""

    dh_path = layout.consolidated_parquet_path("device_health")
    if dh_path.is_file():
        combined_device_health = pl.read_parquet(dh_path)
        rb_path = layout.consolidated_parquet_path("reboot_features")
        combined_reboot_features = (
            pl.read_parquet(rb_path) if rb_path.is_file() else pl.DataFrame()
        )
        sg_path = layout.consolidated_parquet_path("signals")
        combined_signals = (
            pl.read_parquet(sg_path) if sg_path.is_file() else pl.DataFrame()
        )
        et_path = layout.consolidated_parquet_path("error_templates")
        combined_error_templates = (
            pl.read_parquet(et_path) if et_path.is_file() else pl.DataFrame()
        )
    else:
        (
            combined_reboot_features,
            combined_device_health,
            combined_signals,
            combined_error_templates,
        ) = load_legacy_partitioned_parquets(layout)

    fleet_summary = _generate_fleet_aggregations(
        combined_reboot_features,
        combined_device_health,
        combined_signals,
        combined_error_templates,
        module_graph,
        layout,
    )

    return fleet_summary


def _generate_fleet_aggregations(reboot_features_df: pl.DataFrame,
                                device_health_df: pl.DataFrame,
                                signals_df: pl.DataFrame,
                                error_templates_df: pl.DataFrame,
                                module_graph,
                                layout: DataLayoutManager) -> Dict[str, Any]:
    """Generate fleet-level aggregations."""
    
    # Count all CPE directories in the project; analytics rows may be fewer until ETL runs for each CPE
    analyzed_devices = len(device_health_df) if len(device_health_df) > 0 else 0
    project_cpe_count = len(layout.list_cpes_with_rg_parquet())
    total_devices = project_cpe_count if project_cpe_count > 0 else analyzed_devices
    total_reboots = len(reboot_features_df) if len(reboot_features_df) > 0 else 0
    
    # Reboot reason distribution
    reboot_reasons = {}
    if len(reboot_features_df) > 0:
        reboot_summary = reboot_features_df.group_by("reason").agg(
            pl.count().alias("count")
        ).sort("count", descending=True)
        reboot_reasons = {
            row["reason"]: row["count"] 
            for row in reboot_summary.to_dicts()
        }
    
    # Firmware distribution
    firmware_distribution = {}
    if len(device_health_df) > 0:
        firmware_summary = device_health_df.group_by("firmware_version").agg(
            pl.count().alias("count")
        ).sort("count", descending=True)
        firmware_distribution = {
            row["firmware_version"]: row["count"]
            for row in firmware_summary.to_dicts()
        }
    
    # Top error templates by domain
    top_templates = {}
    if len(error_templates_df) > 0:
        template_summary = error_templates_df.group_by(["domain", "template"]).agg(
            pl.count().alias("count")
        ).sort("count", descending=True)
        
        for domain in template_summary["domain"].unique():
            domain_templates = template_summary.filter(pl.col("domain") == domain).head(5)
            top_templates[domain] = [
                {"template": row["template"], "count": row["count"]}
                for row in domain_templates.to_dicts()
            ]
    
    # Device risk assessment (simplified)
    high_risk_devices = []
    if len(device_health_df) > 0:
        # Devices with high memory or CPU usage
        high_risk = device_health_df.filter(
            (pl.col("peak_memory_usage_pct") > 90) | 
            (pl.col("peak_cpu_usage_pct") > 90)
        )
        high_risk_devices = [
            {
                "serial": row["device_serial"],
                "model": row["model"],
                "firmware_version": row["firmware_version"],
                "peak_memory_pct": row["peak_memory_usage_pct"],
                "peak_cpu_pct": row["peak_cpu_usage_pct"]
            }
            for row in high_risk.to_dicts()
        ]
    
    # Create summary JSON
    summary_json = {
        "generation_date": datetime.now().isoformat(),
        "fleet_statistics": {
            "total_devices": total_devices,
            "devices_with_analytics": analyzed_devices,
            "total_reboots": total_reboots,
            "average_reboots_per_device": total_reboots / max(total_devices, 1)
        },
        "reboot_analysis": {
            "reasons_distribution": reboot_reasons,
            "most_common_reason": max(reboot_reasons.items(), key=lambda x: x[1])[0] if reboot_reasons else None
        },
        "firmware_analysis": {
            "version_distribution": firmware_distribution,
            "unique_versions": len(firmware_distribution)
        },
        "error_analysis": {
            "top_templates_by_domain": top_templates,
            "total_error_instances": len(error_templates_df) if len(error_templates_df) > 0 else 0
        },
        "device_health": {
            "high_risk_devices": high_risk_devices,
            "high_risk_count": len(high_risk_devices)
        },
        "module_graph_version": module_graph.version
    }
    
    # Create summary dataframe for parquet storage
    summary_df = pl.DataFrame([{
        "generation_date": datetime.now().isoformat(),
        "total_devices": total_devices,
        "total_reboots": total_reboots,
        "unique_firmware_versions": len(firmware_distribution),
        "high_risk_device_count": len(high_risk_devices),
        "most_common_reboot_reason": max(reboot_reasons.items(), key=lambda x: x[1])[0] if reboot_reasons else "",
        "total_error_instances": len(error_templates_df) if len(error_templates_df) > 0 else 0
    }])
    
    return {
        "summary_df": summary_df,
        "summary_json": summary_json
    }