"""
File Manager Module
====================

Handles file upload, extraction, merging, and archive creation for
uploaded RDK log tarballs.

Pipeline:
    Upload (base64 tgz) -> save to disk -> LogMerger (extract + merge)
    -> Telemetry parse (if present) -> ZIP archive creation

The FileManager is the main entry point called from the log viewer
upload callback.

Example:
    >>> fm = FileManager()
    >>> fm.process_uploaded_files(Path("uploads/user1/proj1"), "my_project")
"""

import os
import base64
import shutil
import tarfile
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from dash import html
from urllib.parse import quote as urlquote

from logai.utils.constants import (
    BASE_DIR,
    MERGED_LOGS_DIR_NAME,
    MERGED_LOGS_ARCHIVE_NAME,
    TELEMETRY_PROFILES_DIR_NAME,
)
from api.log_merger import LogMerger
from typing import List

from logai.telemetry_parser import parse_telemetry_file


@dataclass
class ConfigEntry:
    """A single parser configuration entry mapping files to config."""
    name: str
    supported_config: str
    supported_files: List[str]


@dataclass
class ConfigIndex:
    """
    Index of parser configurations loaded from config_list.json.

    Maps log filenames to their corresponding parser config files.
    """
    supported_files: List[ConfigEntry]

    @staticmethod
    def load_from_file(index_path: str) -> 'ConfigIndex':
        """Load config index from a JSON file."""
        with open(index_path, 'r') as f:
            raw_data = json.load(f)
        entries = [ConfigEntry(**entry) for entry in raw_data.get("supported_files", [])]
        return ConfigIndex(supported_files=entries)

    def find_config_for_file(self, filename: str) -> str:
        """
        Find the parser config for a given filename.

        Args:
            filename: Name of the log file.

        Returns:
            Name of the parser config file.

        Raises:
            ValueError: If no config matches the filename.
        """
        filename_base = os.path.basename(filename)

        for entry in self.supported_files:
            for supported_name in entry.supported_files:
                if supported_name.lower() in filename_base.lower():
                    return entry.supported_config
        raise ValueError(f"No config found for file: {filename}")


class FileManager:
    """
    Processor for handling uploaded files in the application.

    Manages the lifecycle of uploaded log tarballs:
    1. Save uploaded base64 content to disk.
    2. Extract and merge logs using LogMerger.
    3. Parse telemetry reports if present.
    4. Create downloadable ZIP archive.

    Attributes:
        directory: Current project upload directory.
        merged_logs_path: Path to merged logs subdirectory.
    """

    def __init__(self):
        """Initialize FileManager with no active directory."""
        self.directory = None
        self.merged_logs_path = None

    def save_file(self, name, content):
        """
        Save a base64-encoded uploaded file to the project directory.

        Args:
            name: Filename to save as.
            content: Base64-encoded file content from Dash upload.
        """
        content_type, content_string = content.split(',')
        decoded = base64.b64decode(content_string)
        file_path = os.path.join(self.directory, name)
        with open(file_path, "wb") as f:
            f.write(decoded)

    def uploaded_files(self):
        """
        List all files in the current upload directory.

        Returns:
            List of filenames.
        """
        files = []
        for filename in os.listdir(self.directory):
            path = os.path.join(self.directory, filename)
            if os.path.isfile(path):
                files.append(filename)
        return files

    def create_merged_logs_archive(self, project_name, project_path, merged_logs_path, telemetry_path):
        """
        Create a ZIP archive of the merged logs directory.

        Includes telemetry report Excel file if available.

        Args:
            project_name: Project name for the archive filename.
            project_path: Base project directory.
            merged_logs_path: Path to the merged logs directory.
            telemetry_path: Path to the telemetry profiles directory.
        """
        if not os.listdir(merged_logs_path):
            return
        if os.path.exists(telemetry_path) and len(os.listdir(telemetry_path)) > 0:
            telemetry_report_path = os.path.join(telemetry_path, "Telemetry2_report.xlsx")
            copyto_path = os.path.join(merged_logs_path, "Telemetry2_report.xlsx")
            if os.path.exists(telemetry_report_path):
                shutil.copyfile(telemetry_report_path, copyto_path)

        archive = MERGED_LOGS_ARCHIVE_NAME + "-" + str(project_name)
        shutil.make_archive(os.path.join(project_path, archive), 'zip', os.path.join(merged_logs_path))

    def file_download_link(self, filename):
        """
        Generate an HTML download link for a file.

        Args:
            filename: Name of the file to link to.

        Returns:
            Dash html.A component with download URL.
        """
        location = "/download/{}".format(urlquote(filename))
        return html.A(filename, href=location)
    
    def process_uploaded_files(self, project_path, project_name):
        """
        Process uploaded files by extracting and merging logs.

        Steps:
        1. Extract tarballs and merge logs chronologically.
        2. Parse telemetry2_0.txt (if present) using the new YAML-driven parser.
        3. Create a zip archive of merged logs.

        Args:
            project_path: Path to the project directory.
            project_name: Human-readable project name for archive naming.

        Raises:
            FileNotFoundError: If project directory doesn't exist.
        """
        self.directory = project_path
        if not os.path.exists(self.directory):
            raise FileNotFoundError(f"Upload directory '{self.directory}' does not exist.")

        self.merged_logs_path = os.path.join(self.directory, MERGED_LOGS_DIR_NAME)
        self.telemetry_path = os.path.join(self.directory, TELEMETRY_PROFILES_DIR_NAME)
        os.makedirs(self.merged_logs_path, exist_ok=True)

        print(f"Processing uploaded files in {self.directory} ...")

        # Step 1: Merge log files (extract tarballs, merge chronologically)
        merger = LogMerger(self.directory, self.merged_logs_path)
        merger.merge_logs()

        # Step 2: Parse telemetry if present (new YAML-driven parser)
        # The telemetry is now parsed on-demand in the Telemetry tab callback,
        # but we still look for the file to include in the archive.
        telemetry_file = None
        merged_dir = Path(self.merged_logs_path)
        for f in merged_dir.iterdir():
            if f.is_file() and f.name.startswith("telemetry2_0"):
                telemetry_file = f
                break

        if telemetry_file:
            try:
                os.makedirs(self.telemetry_path, exist_ok=True)
                reports, merged, summary = parse_telemetry_file(telemetry_file)
                print(f"Telemetry: {summary.get('parsed', 0)}/{summary.get('total', 0)} reports parsed")
            except Exception as e:
                print(f"Telemetry parsing error (non-fatal): {e}")

        # Step 3: Create archive of merged logs
        self.create_merged_logs_archive(
            project_name=project_name,
            project_path=self.directory,
            merged_logs_path=self.merged_logs_path,
            telemetry_path=self.telemetry_path,
        )

        print("Process uploaded files done")

    # ---------- Multi-CPE Upload ----------

    # Regex: SERIAL_YYYY-MM-DD_YYYY-MM-DD.zip
    CPE_ZIP_RE = re.compile(r'^([A-Za-z0-9]+)_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.zip$')

    # MAC inside tgz filename: ..._AABBCCDDEEFF_..._CPELogs_...
    TGZ_MAC_RE = re.compile(r'_([0-9A-Fa-f]{12})_.*_CPELogs_')

    # Fallback: extract MAC (12 hex chars) and date from tgz filenames
    # e.g. provider_AABBCCDDEEFF_YYYY-MM-DD-HH-MM-SS_CPELogs_MODEL.tgz
    TGZ_CPE_RE = re.compile(r'_([0-9A-Fa-f]{12})_(\d{4}-\d{2}-\d{2})')

    # Extensions recognised as tar archives (standalone uploads)
    TAR_EXTENSIONS = (".tar", ".tgz", ".tar.gz", ".tar.bz2")

    @classmethod
    def detect_cpe_zips(cls, project_dir: Path):
        """
        Detect CPE archive files in the project directory.

        Three patterns are supported:

        1. **Primary zip** -- ``SERIAL_YYYY-MM-DD_YYYY-MM-DD.zip``
           Serial and date range come from the zip filename.

        2. **Fallback zip** -- any other ``.zip`` containing ``.tgz`` files
           whose names embed a 12-hex-digit MAC and a date, e.g.
           ``partner-id_mac_2025-12-13-23-01-27_CPELogs_*.tgz``
           The MAC is used as the CPE serial; dates are extracted from
           the tgz filenames.

        3. **Standalone tar** -- any ``.tar``/``.tgz``/``.tar.gz`` whose
           filename embeds a 12-hex-digit MAC and a date (same regex as
           fallback).  These are treated as single-CPE uploads without
           a zip wrapper.

        Returns:
            List of dicts: {path, serial, date_from, date_to,
                            is_fallback, is_standalone_tar}
        """
        import zipfile

        results = []
        unmatched_zips = []

        for f in project_dir.iterdir():
            if not f.is_file():
                continue

            # --- ZIP archives ---
            if f.name.endswith('.zip'):
                m = cls.CPE_ZIP_RE.match(f.name)
                if m:
                    results.append({
                        "path": f,
                        "serial": m.group(1),
                        "date_from": m.group(2),
                        "date_to": m.group(3),
                        "is_fallback": False,
                        "is_standalone_tar": False,
                    })
                else:
                    unmatched_zips.append(f)
                continue

            # --- Standalone tar/tgz/tar.gz archives ---
            if any(f.name.endswith(ext) for ext in cls.TAR_EXTENSIONS):
                m = cls.TGZ_CPE_RE.search(f.name)
                if m:
                    mac = m.group(1)
                    date_str = m.group(2)
                    results.append({
                        "path": f,
                        "serial": mac,
                        "date_from": date_str,
                        "date_to": date_str,
                        "is_fallback": True,
                        "is_standalone_tar": True,
                    })
                    print(f"[DetectCPE] Standalone tar: {f.name} -> MAC {mac} ({date_str})")

        # Fallback: peek inside unmatched zips for tgz files with MAC addresses
        for zip_path in unmatched_zips:
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    tgz_names = [
                        n for n in zf.namelist()
                        if n.endswith('.tgz') or n.endswith('.tar.gz') or n.endswith('.tar')
                    ]
                    # Group by MAC
                    mac_dates: dict = {}  # MAC -> list of date strings
                    for tgz_name in tgz_names:
                        m = cls.TGZ_CPE_RE.search(tgz_name)
                        if m:
                            mac_dates.setdefault(m.group(1), []).append(m.group(2))

                    for mac, dates in mac_dates.items():
                        results.append({
                            "path": zip_path,
                            "serial": mac,
                            "date_from": min(dates),
                            "date_to": max(dates),
                            "is_fallback": True,
                            "is_standalone_tar": False,
                        })
                        print(f"[DetectCPE] Fallback: {zip_path.name} -> MAC {mac} ({min(dates)} to {max(dates)})")
            except Exception as e:
                print(f"[DetectCPE] Error peeking into {zip_path.name}: {e}")

        return results

    def process_multi_cpe_upload(self, project_dir: Path, project_name: str):
        """
        Process multi-CPE zip uploads.

        Supports two zip naming conventions:

        1. **Primary** -- ``SERIAL_YYYY-MM-DD_YYYY-MM-DD.zip``
           All tgz files inside belong to that serial.
        2. **Fallback** -- any other ``.zip`` whose tgz filenames embed a
           12-hex-digit MAC (e.g. ``partner-id_mac_2025-12-13-...``).
           Only tgz files matching the target MAC are collected.

        Handles the corner case where the same serial/MAC appears in multiple
        zips with different date ranges.  All tgz files from every zip for a
        given serial are extracted first, then merged once so the final logs
        cover the full date span.

        Pipeline per serial:
          1. Group all zips by serial
          2. Extract ALL zips for that serial into one staging dir
          3. Collect tgz files (filter by MAC for fallback zips)
          4. Run LogMerger ONCE on the combined set
          5. Move merged output to {project_dir}/{serial}/
          6. Parse MAC from tgz filenames (or use serial if fallback)
          7. Use min(date_from), max(date_to) across all zips

        Returns:
            List of dicts: {serial, mac, date_from, date_to}
        """
        import zipfile

        cpe_zips = self.detect_cpe_zips(project_dir)
        if not cpe_zips:
            return []

        # ---- Group zips by serial ----
        serial_groups: dict = {}  # serial -> list of cpe_info dicts
        for cpe_info in cpe_zips:
            serial = cpe_info["serial"]
            serial_groups.setdefault(serial, []).append(cpe_info)

        cpe_results = []

        for serial, zip_list in serial_groups.items():
            zip_names = [z["path"].name for z in zip_list]
            is_fallback = any(z.get("is_fallback", False) for z in zip_list)
            label = f" (fallback/MAC)" if is_fallback else ""
            print(f"[MultiCPE] Processing CPE {serial}{label} — {len(zip_list)} zip(s): {zip_names}")

            # Compute overall date range
            date_from = min(z["date_from"] for z in zip_list)
            date_to = max(z["date_to"] for z in zip_list)

            # Staging directory: all tgz files from all zips end up here
            staging_dir = project_dir / f"_cpe_staging_{serial}"
            os.makedirs(staging_dir, exist_ok=True)

            # For fallback zips the serial IS the MAC
            mac = serial if is_fallback else None

            try:
                # ---- Phase 1: Extract every zip / collect standalone tars ----
                for cpe_info in zip_list:
                    archive_path = cpe_info["path"]

                    # --- Standalone tarball (no zip wrapper) ---
                    if cpe_info.get("is_standalone_tar"):
                        dest_name = f"{cpe_info['date_from']}_{archive_path.name}"
                        shutil.copy2(str(archive_path), str(staging_dir / dest_name))
                        # Try to extract MAC from filename
                        if mac is None:
                            m = self.TGZ_MAC_RE.search(archive_path.name)
                            if m:
                                mac = m.group(1)
                        print(f"[MultiCPE] Standalone tar -> staging: {dest_name}")
                        continue

                    # --- ZIP archive ---
                    # Each zip gets its own temp extraction dir to avoid collisions
                    temp_dir = project_dir / f"_cpe_tmp_{serial}_{cpe_info['date_from']}"
                    os.makedirs(temp_dir, exist_ok=True)

                    try:
                        with zipfile.ZipFile(archive_path, 'r') as zf:
                            zf.extractall(temp_dir)

                        # Find inner folder with tarball files
                        # Could be directly in temp_dir or in a subfolder
                        tgz_source = temp_dir
                        subdirs = [d for d in temp_dir.iterdir() if d.is_dir()]
                        if subdirs:
                            for sd in subdirs:
                                tgz_files = (
                                    list(sd.glob("*.tgz"))
                                    + list(sd.glob("*.tar.gz"))
                                    + list(sd.glob("*.tar"))
                                )
                                if tgz_files:
                                    tgz_source = sd
                                    break

                        # Move tar/tgz files into staging dir (rename to avoid collisions)
                        for f in tgz_source.iterdir():
                            if f.is_file() and any(f.name.endswith(ext) for ext in self.TAR_EXTENSIONS):
                                # For fallback zips, only take tgz files containing this MAC
                                if is_fallback and serial not in f.name:
                                    continue
                                # Try to extract MAC while we're scanning
                                if mac is None:
                                    m = self.TGZ_MAC_RE.search(f.name)
                                    if m:
                                        mac = m.group(1)
                                # Use date prefix to avoid name collisions across zips
                                dest_name = f"{cpe_info['date_from']}_{f.name}"
                                shutil.move(str(f), str(staging_dir / dest_name))

                    except Exception as e:
                        print(f"[MultiCPE] Error extracting {archive_path.name}: {e}")
                    finally:
                        if temp_dir.exists():
                            shutil.rmtree(temp_dir, ignore_errors=True)

                # ---- Phase 2: Merge all collected tgz files at once ----
                cpe_output_dir = project_dir / serial
                os.makedirs(cpe_output_dir, exist_ok=True)

                merged_dir = cpe_output_dir / MERGED_LOGS_DIR_NAME
                os.makedirs(merged_dir, exist_ok=True)

                merger = LogMerger(str(staging_dir), str(merged_dir))
                merger.merge_logs()

                # Move merged files from merged_logs/ up to cpe_output_dir
                if merged_dir.exists():
                    for fname in os.listdir(merged_dir):
                        src = merged_dir / fname
                        dst = cpe_output_dir / fname
                        if src.is_file():
                            shutil.move(str(src), str(dst))
                    shutil.rmtree(merged_dir, ignore_errors=True)

                cpe_results.append({
                    "serial": serial,
                    "mac": mac,
                    "date_from": date_from,
                    "date_to": date_to,
                })
                print(f"[MultiCPE] CPE {serial} processed ({len(zip_list)} zips merged) -> {cpe_output_dir}")

            except Exception as e:
                print(f"[MultiCPE] Error processing CPE {serial}: {e}")
            finally:
                # Clean up staging dir
                if staging_dir.exists():
                    shutil.rmtree(staging_dir, ignore_errors=True)

        return cpe_results

    def list_uploaded_files(self):
        """List all files saved in the uploads folder."""
        try:
            return sorted(os.listdir(self.directory))
        except FileNotFoundError:
            return []
        
    def load_config(self, filename):
        """
        Load a parser configuration for the given filename.

        Looks up the filename in configs/config_list.json to find the
        matching parser config, then loads and returns its JSON content.

        Args:
            filename: Name of the log file to find config for.

        Returns:
            Parsed JSON config dict, or None if not found.
        """
        root_dir = os.path.dirname(os.path.abspath(__file__))
        config_list_path = os.path.join(root_dir, "../configs", "config_list.json")

        if os.path.exists(config_list_path):
            #print(f"Loading config from {config_list_path}")
            self.config_index = ConfigIndex.load_from_file(config_list_path)
            if self.config_index:
                file_config = self.config_index.find_config_for_file(filename)
                self.config_path = os.path.join(root_dir, "../configs", file_config)
                #print("config {}, path {}".format(file_config, self.config_path))
                if os.path.exists(self.config_path):
                    try:
                         with open(self.config_path, 'r') as f:
                            raw_data = json.load(f)
                            return raw_data
                    except json.JSONDecodeError as e:
                        print(f"Error decoding invalid JSON: {e}\n")
                    except Exception as e:
                        print(f"An unexpected error occurred: {e}\n")