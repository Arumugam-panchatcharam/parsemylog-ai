"""
Ripgrep Scanner Module
======================

Pre-filters RDK log files using ripgrep (rg) to extract only error-class and
state-change lines before feeding them to Drain3 for template extraction.

This two-stage approach provides 6-10x speedup over full-file Drain3 parsing:
1. Stage 1 (rg): Scans logs at native speed (~0.3s for 500K lines)
2. Stage 2 (Drain3): Templates only the filtered subset (~5-15% of lines)

Requirements:
    - ripgrep (rg) binary must be installed and accessible
    - Pattern packs defined in YAML config files per domain

Architecture:
    Pattern Packs (YAML) + Log Files
        -> RgScanner.scan_domain()
            -> subprocess rg --json -C<N>
                -> Parse JSON output
                    -> List[RgMatch] (structured matches with context)

Example:
    >>> from logai.rg_scanner import RgScanner
    >>> from pathlib import Path
    >>>
    >>> scanner = RgScanner(pattern_config_dir=Path("configs/rg_patterns"))
    >>> matches = scanner.scan_domain(Path("/logs/merged_logs"), domain="wireless")
    >>> print(f"Found {len(matches)} error-class lines")
    >>> for m in matches[:3]:
    ...     print(f"  {m.file}:{m.line_number} {m.match_text[:80]}")
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class RgMatch:
    """
    A single match from ripgrep with surrounding context.

    Attributes:
        file: Source log file path.
        line_number: Line number in source file (1-based).
        match_text: The matched line content.
        context_before: Lines immediately before the match.
        context_after: Lines immediately after the match.
        pattern_type: Whether the match came from 'literal' or 'regex' pattern.
    """
    file: str
    line_number: int
    match_text: str
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)
    pattern_type: str = "regex"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "file": self.file,
            "line_number": self.line_number,
            "match_text": self.match_text,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "pattern_type": self.pattern_type,
        }


@dataclass
class DomainPatternConfig:
    """
    Pattern configuration for a single domain loaded from YAML.

    Attributes:
        domain: Domain name (wireless, platform, cellular, mesh, core_router, telemetry, common, voice).
        files: Glob patterns for log files to scan.
        context_lines: Number of context lines around matches.
        case_insensitive: Whether to use case-insensitive matching.
        literals: Literal string patterns (fast path, rg -F).
        regex: Regex patterns (rg -e).
    """
    domain: str
    files: List[str]
    context_lines: int = 3
    case_insensitive: bool = True
    literals: List[str] = field(default_factory=list)
    regex: List[str] = field(default_factory=list)


# ============================================================================
# RIPGREP SCANNER
# ============================================================================

class RgScanner:
    """
    Scans RDK log files using ripgrep for error-class and state-change lines.

    The scanner:
    1. Loads domain-specific pattern packs from YAML configuration.
    2. Builds optimized rg commands (literals via -F, regex via -e).
    3. Parses --json output into structured RgMatch objects.
    4. Captures context lines around each match (-C N).

    Performance:
        - Scanning 500K lines: ~0.2-0.5s (ripgrep native speed)
        - Typical filter rate: 5-15% of lines match (error/failure class)
        - One rg invocation per domain (all patterns batched)

    Attributes:
        pattern_config_dir: Directory containing domain YAML pattern files.
        rg_binary: Path to ripgrep binary.
        domain_configs: Loaded domain pattern configurations.

    Example:
        >>> scanner = RgScanner(Path("configs/rg_patterns"))
        >>> matches = scanner.scan_domain(Path("/logs"), "wireless")
        >>> print(f"Found {len(matches)} matches")
    """

    def __init__(
        self,
        pattern_config_dir: Path,
        rg_binary: str = "rg",
    ):
        """
        Initialize ripgrep scanner.

        Args:
            pattern_config_dir: Directory containing per-domain YAML pattern files.
            rg_binary: Path or name of ripgrep binary (default: "rg").

        Raises:
            FileNotFoundError: If pattern_config_dir doesn't exist.
            RuntimeError: If ripgrep binary is not found.
        """
        self.pattern_config_dir = pattern_config_dir
        self.rg_binary = rg_binary
        self.domain_configs: Dict[str, DomainPatternConfig] = {}

        # Validate rg binary is available
        self._validate_rg_binary()

        # Load all domain pattern configs
        self._load_pattern_configs()

        logger.info(
            f"RgScanner initialized: {len(self.domain_configs)} domain configs, "
            f"rg binary: {self.rg_binary}"
        )

    def _validate_rg_binary(self):
        """
        Validate that ripgrep binary is available.

        Raises:
            RuntimeError: If rg binary is not found on PATH or at specified path.
        """
        rg_path = shutil.which(self.rg_binary)
        if rg_path is None:
            raise RuntimeError(
                f"ripgrep binary not found: '{self.rg_binary}'. "
                f"Install it via: apt-get install ripgrep (Debian/Ubuntu), "
                f"brew install ripgrep (macOS), or download from "
                f"https://github.com/BurntSushi/ripgrep/releases"
            )
        self.rg_binary = rg_path
        logger.debug(f"ripgrep binary found: {self.rg_binary}")

    def _load_pattern_configs(self):
        """
        Load domain pattern configurations from YAML files.

        Scans pattern_config_dir for .yaml/.yml files and loads each
        as a DomainPatternConfig.
        """
        if not self.pattern_config_dir.exists():
            logger.warning(f"Pattern config directory not found: {self.pattern_config_dir}")
            return

        yaml_files = list(self.pattern_config_dir.glob("*.yaml")) + \
                     list(self.pattern_config_dir.glob("*.yml"))

        if not yaml_files:
            logger.warning(f"No YAML files found in {self.pattern_config_dir}")
            return

        for yaml_file in yaml_files:
            try:
                with open(yaml_file, "r") as f:
                    raw = yaml.safe_load(f)

                if not raw or "domain" not in raw:
                    logger.warning(f"Skipping {yaml_file}: missing 'domain' key")
                    continue

                config = DomainPatternConfig(
                    domain=raw["domain"],
                    files=raw.get("files", []),
                    context_lines=raw.get("context_lines", 3),
                    case_insensitive=raw.get("case_insensitive", True),
                    literals=raw.get("literals", []),
                    regex=raw.get("regex", []),
                )

                self.domain_configs[config.domain] = config
                logger.info(
                    f"Loaded pattern config: {config.domain} "
                    f"({len(config.literals)} literals, {len(config.regex)} regex, "
                    f"{len(config.files)} file globs)"
                )

            except Exception as e:
                logger.error(f"Failed to load pattern config {yaml_file}: {e}")

    def scan_domain(
        self,
        log_dir: Path,
        domain: str,
        extra_files: Optional[List[Path]] = None,
    ) -> List[RgMatch]:
        """
        Scan log files for a specific domain using ripgrep.

        Builds and runs an optimized rg command that batches all patterns
        for the domain into a single invocation.

        Args:
            log_dir: Directory containing log files.
            domain: Domain name (must match a loaded pattern config).
            extra_files: Optional list of specific file paths to scan
                        (overrides file glob patterns from config).

        Returns:
            List of RgMatch objects with matches and context.

        Example:
            >>> matches = scanner.scan_domain(Path("/logs/merged"), "wireless")
            >>> for m in matches:
            ...     print(f"{m.file}:{m.line_number} {m.match_text[:60]}")
        """
        config = self.domain_configs.get(domain)
        if config is None:
            logger.warning(f"No pattern config for domain: {domain}")
            return []

        if not log_dir.exists():
            logger.warning(f"Log directory not found: {log_dir}")
            return []

        start_time = time.perf_counter()

        # Build rg command
        cmd = self._build_rg_command(config, log_dir, extra_files)
        if not cmd:
            logger.warning(f"No patterns to scan for domain: {domain}")
            return []

        # Execute rg
        matches = self._execute_rg(cmd, config)

        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[RgScanner] Domain '{domain}': {len(matches)} matches "
            f"in {elapsed:.3f}s"
        )

        return matches

    def scan_all_domains(
        self,
        log_dir: Path,
        domains: Optional[List[str]] = None,
    ) -> Dict[str, List[RgMatch]]:
        """
        Scan log files for multiple domains.

        Args:
            log_dir: Directory containing log files.
            domains: List of domain names to scan. If None, scans all
                    configured domains.

        Returns:
            Dictionary mapping domain name to list of RgMatch objects.
        """
        target_domains = domains or list(self.domain_configs.keys())
        results: Dict[str, List[RgMatch]] = {}

        for domain in target_domains:
            results[domain] = self.scan_domain(log_dir, domain)

        return results

    def scan_files(
        self,
        file_paths: List[Path],
        domain: str,
    ) -> List[RgMatch]:
        """
        Scan specific log files (not a directory) for a domain.

        This is useful when log files are already known/collected
        rather than discovered via globs.

        Args:
            file_paths: List of specific file paths to scan.
            domain: Domain name (for pattern selection).

        Returns:
            List of RgMatch objects.
        """
        config = self.domain_configs.get(domain)
        if config is None:
            logger.warning(f"No pattern config for domain: {domain}")
            return []

        existing_files = [p for p in file_paths if p.exists()]
        if not existing_files:
            logger.warning(f"No existing files to scan for domain: {domain}")
            return []

        start_time = time.perf_counter()

        cmd = self._build_rg_command_for_files(config, existing_files)
        if not cmd:
            return []

        matches = self._execute_rg(cmd, config)

        elapsed = time.perf_counter() - start_time
        logger.info(
            f"[RgScanner] Domain '{domain}' ({len(existing_files)} files): "
            f"{len(matches)} matches in {elapsed:.3f}s"
        )

        return matches

    def _build_rg_command(
        self,
        config: DomainPatternConfig,
        log_dir: Path,
        extra_files: Optional[List[Path]] = None,
    ) -> List[str]:
        """
        Build ripgrep command for a domain configuration.

        Strategy:
        - Combine all patterns (literals + regex) into a single rg invocation.
        - Use --json for structured output parsing.
        - Use -C N for context lines.
        - Use --glob to scope to domain-specific files.

        Args:
            config: Domain pattern configuration.
            log_dir: Directory to scan.
            extra_files: Optional specific files to scan.

        Returns:
            Command arguments list, or empty list if no patterns.
        """
        # Collect all regex patterns
        all_patterns = list(config.regex)

        # Convert literals to regex (escaped) for single invocation
        for literal in config.literals:
            escaped = _escape_regex(literal)
            all_patterns.append(escaped)

        if not all_patterns:
            return []

        # Combine all patterns with | (OR) for single rg invocation
        combined_pattern = "|".join(f"(?:{p})" for p in all_patterns)

        # Build command
        cmd = [
            self.rg_binary,
            "--json",                          # Structured JSON output
            f"-C{config.context_lines}",       # Context lines
            "--no-heading",                     # No file headers
            "--line-number",                    # Include line numbers
            "--max-count", "10000",             # Safety limit per file
            "--max-filesize", "500M",           # Skip huge files
        ]

        if config.case_insensitive:
            cmd.append("-i")

        # Add the combined pattern
        cmd.extend(["-e", combined_pattern])

        # Add file scope
        if extra_files:
            # Scan specific files
            cmd.extend(str(f) for f in extra_files)
        else:
            # Use glob patterns from config
            for file_glob in config.files:
                cmd.extend(["--glob", file_glob])
            cmd.append(str(log_dir))

        return cmd

    def _build_rg_command_for_files(
        self,
        config: DomainPatternConfig,
        file_paths: List[Path],
    ) -> List[str]:
        """
        Build ripgrep command for specific file paths.

        Args:
            config: Domain pattern configuration.
            file_paths: Specific files to scan.

        Returns:
            Command arguments list, or empty list if no patterns.
        """
        return self._build_rg_command(config, Path("."), extra_files=file_paths)

    def _execute_rg(
        self,
        cmd: List[str],
        config: DomainPatternConfig,
    ) -> List[RgMatch]:
        """
        Execute ripgrep command and parse JSON output.

        Ripgrep --json outputs one JSON object per line with types:
        - "begin": Start of file match group
        - "match": A matching line
        - "context": A context line (before/after match)
        - "end": End of file match group
        - "summary": Final summary

        Args:
            cmd: Ripgrep command arguments.
            config: Domain pattern config (for metadata).

        Returns:
            List of parsed RgMatch objects.
        """
        try:
            logger.debug(f"[RgScanner] Running: {' '.join(cmd[:10])}...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # rg exit codes: 0 = matches found, 1 = no matches, 2 = error
            if result.returncode == 2:
                logger.error(f"[RgScanner] ripgrep error: {result.stderr}")
                return []

            if result.returncode == 1:
                # No matches found
                logger.debug(f"[RgScanner] No matches found for domain: {config.domain}")
                return []

            return self._parse_rg_json(result.stdout)

        except subprocess.TimeoutExpired:
            logger.error("[RgScanner] ripgrep timed out after 60s")
            return []
        except Exception as e:
            logger.error(f"[RgScanner] Failed to run ripgrep: {e}")
            return []

    def _parse_rg_json(self, json_output: str) -> List[RgMatch]:
        """
        Parse ripgrep --json output into RgMatch objects.

        The JSON output is newline-delimited (one JSON object per line).
        We reconstruct matches with their surrounding context.

        Args:
            json_output: Raw JSON output from rg --json.

        Returns:
            List of RgMatch objects.
        """
        matches: List[RgMatch] = []
        # Buffer to collect context lines for each match
        current_context_before: List[str] = []
        pending_matches: List[RgMatch] = []

        for line in json_output.splitlines():
            if not line.strip():
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type")

            if msg_type == "context":
                # Context line (before or after a match)
                data = obj.get("data", {})
                text = data.get("lines", {}).get("text", "").rstrip("\n")

                if pending_matches:
                    # This is context AFTER the last match
                    pending_matches[-1].context_after.append(text)
                else:
                    # This is context BEFORE the next match
                    current_context_before.append(text)

            elif msg_type == "match":
                # A matching line
                data = obj.get("data", {})
                text = data.get("lines", {}).get("text", "").rstrip("\n")
                line_number = data.get("line_number", 0)
                file_path = data.get("path", {}).get("text", "")

                match = RgMatch(
                    file=file_path,
                    line_number=line_number,
                    match_text=text,
                    context_before=list(current_context_before),
                    context_after=[],
                    pattern_type="combined",
                )

                pending_matches.append(match)
                current_context_before.clear()

            elif msg_type == "begin":
                # New file group - reset context buffer
                current_context_before.clear()

            elif msg_type == "end":
                # End of file group - finalize all pending matches
                matches.extend(pending_matches)
                pending_matches.clear()
                current_context_before.clear()

        # Finalize any remaining matches
        matches.extend(pending_matches)

        return matches

    def get_available_domains(self) -> List[str]:
        """
        Get list of domains with loaded pattern configurations.

        Returns:
            List of domain names.
        """
        return list(self.domain_configs.keys())

    def get_domain_config(self, domain: str) -> Optional[DomainPatternConfig]:
        """
        Get pattern configuration for a specific domain.

        Args:
            domain: Domain name.

        Returns:
            DomainPatternConfig or None.
        """
        return self.domain_configs.get(domain)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get scanner configuration statistics.

        Returns:
            Dictionary with configuration info.
        """
        stats = {
            "rg_binary": self.rg_binary,
            "pattern_config_dir": str(self.pattern_config_dir),
            "domains": {},
        }
        for domain, config in self.domain_configs.items():
            stats["domains"][domain] = {
                "literals": len(config.literals),
                "regex": len(config.regex),
                "file_globs": len(config.files),
                "context_lines": config.context_lines,
                "case_insensitive": config.case_insensitive,
            }
        return stats


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _escape_regex(literal: str) -> str:
    """
    Escape special regex characters in a literal string.

    Args:
        literal: Literal string to escape.

    Returns:
        Regex-safe escaped string.
    """
    special_chars = r"\.^$*+?{}[]|()"
    escaped = []
    for char in literal:
        if char in special_chars:
            escaped.append(f"\\{char}")
        else:
            escaped.append(char)
    return "".join(escaped)


def check_rg_available(rg_binary: str = "rg") -> bool:
    """
    Check if ripgrep binary is available.

    Args:
        rg_binary: Path or name of rg binary.

    Returns:
        True if rg is available, False otherwise.
    """
    return shutil.which(rg_binary) is not None
