"""
Portable configuration for logai core modules.

Provides injectable paths and settings so the library can be used
in multi-agent environments, CI, or embedded without hardcoded
project structure assumptions.

Usage:
    >>> from logai.config import LogAIConfig
    >>> config = LogAIConfig(
    ...     base_dir=Path("/my/app"),
    ...     rg_patterns_dir=Path("/my/configs/rg_patterns"),
    ... )
    >>> indexer = RagIndexer(project_dir=..., config=config)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class LogAIConfig:
    """
    Portable configuration for logai modules.

    All paths are optional. When None, modules fall back to
    defaults relative to the package location.
    """

    base_dir: Optional[Path] = None
    """Base directory for resolving relative paths. Defaults to project root."""

    rg_patterns_dir: Optional[Path] = None
    """Directory containing rg pattern YAML files per domain."""

    drain3_config_path: Optional[Path] = None
    """Path to drain3.ini. Defaults to project_root/drain3.ini."""

    telemetry_fields_config_path: Optional[Path] = None
    """Path to telemetry_report_fields.yaml."""

    parser_config_path: Optional[Path] = None
    """Path to rule_parser_config.json for LogParserConfig."""

    def resolve_base_dir(self) -> Path:
        """Resolve base directory, defaulting to project root."""
        if self.base_dir is not None:
            return Path(self.base_dir)
        return Path(__file__).resolve().parent.parent

    def resolve_rg_patterns_dir(self) -> Path:
        """Resolve rg patterns directory."""
        if self.rg_patterns_dir is not None:
            return Path(self.rg_patterns_dir)
        return self.resolve_base_dir() / "configs" / "rg_patterns"

    def resolve_drain3_config_path(self) -> Path:
        """Resolve drain3.ini path."""
        if self.drain3_config_path is not None:
            return Path(self.drain3_config_path)
        return self.resolve_base_dir() / "drain3.ini"

    def resolve_telemetry_fields_config_path(self) -> Path:
        """Resolve telemetry report fields YAML path."""
        if self.telemetry_fields_config_path is not None:
            return Path(self.telemetry_fields_config_path)
        return self.resolve_base_dir() / "configs" / "telemetry_report_fields.yaml"

    def resolve_parser_config_path(self) -> Path:
        """Resolve rule parser config JSON path."""
        if self.parser_config_path is not None:
            return Path(self.parser_config_path)
        return self.resolve_base_dir() / "user_uploads" / "rule_parser_config.json"


def default_config() -> LogAIConfig:
    """Return default configuration using project structure."""
    return LogAIConfig()
