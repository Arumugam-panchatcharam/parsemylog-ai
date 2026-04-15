"""
Data Layout Management for CPE Analytics

Layout (consolidated):
user_uploads/<user>/<project>/
  ├── raw/
  ├── processed/
  └── issue_analysis/
        ├── analytics/
        │     ├── device_health.parquet      # all CPEs + device_serial
        │     ├── error_templates.parquet
        │     ├── reboot_features.parquet
        │     └── signals.parquet
        └── fleet/
              ├── fleet_summary.parquet
              └── fleet_summary.json

Legacy partitioned paths (cpes/serial=*/date=*) are migrated on first read/write.
"""

from pathlib import Path
from typing import Union


class DataLayoutManager:
    """Manages directory layout for CPE analytics."""

    def __init__(self, user_id: Union[str, int], project_id: str, base_path: str = None):
        self.user_id = str(user_id)
        self.project_id = project_id

        if base_path is None:
            from logai.utils.constants import UPLOAD_DIRECTORY

            base_path = UPLOAD_DIRECTORY

        self.project_root = Path(base_path) / self.user_id / self.project_id

    def get_project_root(self) -> Path:
        """Get the project root directory."""
        return self.project_root

    def get_raw_dir(self) -> Path:
        """Get the raw data directory."""
        return self.project_root / "raw"

    def get_processed_dir(self) -> Path:
        """Get the processed data directory."""
        return self.project_root / "processed"

    def get_issue_analysis_dir(self) -> Path:
        """Get the issue_analysis root directory."""
        return self.project_root / "issue_analysis"

    def get_consolidated_analytics_dir(self) -> Path:
        """Per-project consolidated analytics Parquet directory."""
        return self.get_issue_analysis_dir() / "analytics"

    def consolidated_parquet_path(self, name: str) -> Path:
        """
        Path to a consolidated dataset (name without .parquet).

        name: reboot_features | device_health | signals | error_templates | sta_issues | wifi_labeled_events
        """
        return self.get_consolidated_analytics_dir() / f"{name}.parquet"

    def get_fleet_dir(self) -> Path:
        """Fleet summary outputs (no date partition)."""
        return self.get_issue_analysis_dir() / "fleet"

    def fleet_summary_parquet_path(self) -> Path:
        return self.get_fleet_dir() / "fleet_summary.parquet"

    def fleet_summary_json_path(self) -> Path:
        return self.get_fleet_dir() / "fleet_summary.json"

    def get_cpe_source_dir(self, serial: str) -> Path:
        """
        Get the existing CPE source directory (current structure).

        Returns:
            Path to user_uploads/<user>/<project>/<serial>/
        """
        return self.project_root / serial

    def ensure_directories(self, *paths: Path) -> None:
        """Ensure directories exist, creating them if necessary."""
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)

    def get_cpe_parquet_files(self, serial: str) -> dict:
        """
        Get paths to all *_rg.parquet files for a CPE.

        Returns:
            Dictionary mapping domain names to parquet file paths
        """
        cpe_dir = self.get_cpe_source_dir(serial)
        domains = [
            "cellular",
            "common",
            "core_router",
            "mesh",
            "platform",
            "telemetry",
            "voice",
            "wireless",
        ]

        parquet_files = {}
        for domain in domains:
            parquet_path = cpe_dir / f"{domain}_rg.parquet"
            if parquet_path.exists():
                parquet_files[domain] = parquet_path

        return parquet_files

    def get_cpe_cache_files(self, serial: str) -> dict:
        """Get paths to cache JSON files for a CPE."""
        cpe_dir = self.get_cpe_source_dir(serial)

        cache_files = {}
        cache_types = [
            ("device_info", ".device_info_cache.json"),
            ("version", ".version_cache.json"),
            ("reboots", ".reboots_cache.json"),
            ("raw_selfheal", "raw_selfheal_cache.json"),
            ("raw_telemetry", "raw_telemetry_cache.json"),
        ]

        for cache_type, filename in cache_types:
            cache_path = cpe_dir / filename
            if cache_path.exists():
                cache_files[cache_type] = cache_path

        return cache_files

    def list_cpe_serials(self) -> list:
        """
        List all CPE serials in the project (top-level directories).
        """
        if not self.project_root.exists():
            return []

        serials = []
        for item in self.project_root.iterdir():
            if (
                item.is_dir()
                and item.name not in ["raw", "processed", "issue_analysis"]
                and not item.name.startswith(".")
            ):
                serials.append(item.name)

        return sorted(serials)

    def list_cpes_with_rg_parquet(self) -> list:
        """
        Serials for CPE directories that have at least one *_rg.parquet file.
        """
        return sorted(
            serial
            for serial in self.list_cpe_serials()
            if self.get_cpe_parquet_files(serial)
        )
