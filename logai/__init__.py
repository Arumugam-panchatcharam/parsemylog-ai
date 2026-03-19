"""
logai - Log Analysis & Intelligence Library
=============================================

Portable core modules for log parsing, pattern extraction, device info,
and telemetry. Designed for use in multi-agent environments (auto log
download, parse, report generation).

Quick start (multi-agent / portable):
    >>> from pathlib import Path
    >>> from logai import (
    ...     LogAIConfig,
    ...     Pattern,
    ...     extract_device_info_from_paths,
    ...     parse_telemetry_reports,
    ... )
    >>>
    >>> # Explicit paths - no project structure assumed
    >>> paths = {
    ...     "PARODUSlog": Path("/tmp/logs/PARODUSlog.txt"),
    ...     "version": Path("/tmp/logs/version.txt"),
    ... }
    >>> device_info = extract_device_info_from_paths(paths)
    >>>
    >>> # Parse telemetry from content
    >>> content = Path("/tmp/telemetry2_0.txt").read_text()
    >>> reports = parse_telemetry_reports(content)
    >>>
    >>> # Drain3 template extraction
    >>> parser = Pattern(project_dir=Path("/tmp/state"))
    >>> df, parquet_path = parser.parse_lines(lines, "wireless_rg")

Exports:
    - LogAIConfig, default_config: Portable configuration
    - Pattern, extract_parameters: Drain3 template extraction
    - RagIndexer: RAG indexing (rg + Drain3 + Qdrant)
    - extract_device_info_from_paths: Portable device info extraction
    - parse_telemetry_reports, extract_telemetry_summary: Telemetry parsing
    - LogParserConfig: Config-based regex log parser
"""

from logai.config import LogAIConfig, default_config
from logai.info_extractor import (
    extract_device_info_from_paths,
    find_and_extract_reboots,
    parse_boottime_log,
    parse_parodus_log,
    parse_version_txt,
)
from logai.pattern import Pattern, extract_parameters
from logai.telemetry_parser import (
    extract_telemetry_summary,
    load_report_field_config,
    merge_telemetry_reports,
    parse_telemetry_reports,
)

__all__ = [
    "LogAIConfig",
    "default_config",
    "Pattern",
    "extract_parameters",
    "extract_device_info_from_paths",
    "find_and_extract_reboots",
    "parse_boottime_log",
    "parse_parodus_log",
    "parse_version_txt",
    "parse_telemetry_reports",
    "merge_telemetry_reports",
    "extract_telemetry_summary",
    "load_report_field_config",
]
