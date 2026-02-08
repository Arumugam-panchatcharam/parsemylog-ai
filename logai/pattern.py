"""
Pattern Module -- Drain3 Log Template Extraction
==================================================

Wraps the Drain3 online log parser to extract templates from RDK log files.

Supports two entry points:
1. parse_logs(file_path) -- reads a full log file, extracts timestamps, and
   runs Drain3 on every line.  Used for individual file parsing.
2. parse_lines(lines, source_name) -- accepts pre-filtered lines (e.g. from
   ripgrep) and runs Drain3 only on those lines.  Used in the rg+Drain3
   two-stage pipeline for 6-10x speedup.

Drain3 returns a dictionary like this when you call add_log_message(line):
    {
      "change_type": "cluster_created",
      "cluster_id": 1,
      "template_mined": "User <NUM> logged in at <DATETIME>",
      "parameter_list": ["123", "2025-10-01 12:34:56,789"]
    }

Example:
    >>> from logai.pattern import Pattern
    >>> parser = Pattern(project_dir=Path("my_project"))
    >>> df, path = parser.parse_logs("/logs/WiFilog.txt")
    >>> print(df["template"].value_counts().head())
"""

import re
import os
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from dateutil import parser as dateparser

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.file_persistence import FilePersistence
import time

logger = logging.getLogger(__name__)


class Pattern:
    """
    Drain3-based log template extractor.

    Provides two parsing entry points:
    - parse_logs(fpath): Parse a full log file from disk.
    - parse_lines(lines, source_name): Parse pre-filtered lines from ripgrep.

    Attributes:
        project_dir: Project directory for Drain3 state and parquet caches.
        template_miner: Drain3 TemplateMiner with optional file persistence.
        preprocess_regex: Regex for extracting timestamps from log lines.
    """

    def __init__(self, project_dir=None, state_name=None, sim_th=None, depth=None):
        """
        Initialize the pattern parser with Drain3 configuration.

        Args:
            project_dir: Directory for Drain3 state files and parquet caches.
                        If provided, enables persistent Drain3 state.
            state_name: Optional name for the Drain3 state file. Each domain
                       should use a unique name (e.g. "wireless", "platform")
                       so that a corrupted state for one domain doesn't affect
                       others. Defaults to "drain3_state" (shared state).
            sim_th: Unused (kept for backward compatibility).
            depth: Unused (kept for backward compatibility).
        """
        self.project_dir = project_dir
        config = TemplateMinerConfig()
        config.load("drain3.ini")  # load from external ini file
        self.preprocess_regex = re.compile(
                r"^(?P<timestamp>("
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"          # 2023-10-02T12:34:56
                r"|\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}"         # 2023-10-02-12-34-56
                r"|\d{6}-\d{2}:\d{2}:\d{2}\.\d+"                # 230102-12:34:56.123
                r"|[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}" # Sep  3 00:28:37
                r"|\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}"        # 2023-10-02 12:34:56
                r"|\d+\.\d+"                                    # 175383.097855
                r"))[:\s]+(?P<loglines>.*)$"
            )
        self.headers = ["timestamp", "loglines"]
        # Build per-domain state file path
        fname = f"drain3_{state_name}.json" if state_name else "drain3_state.json"
        persistence = None
        if project_dir and os.path.exists(project_dir):
            state_path = f"{project_dir}/{fname}"
            persistence = FilePersistence(state_path)
            # Validate the state file is readable; remove if corrupted
            if os.path.exists(state_path):
                try:
                    TemplateMiner(persistence, config=config)
                except Exception as e:
                    logger.warning(
                        f"[Pattern] Corrupted drain3 state at {state_path}, "
                        f"removing and starting fresh: {e}"
                    )
                    try:
                        os.remove(state_path)
                    except OSError:
                        pass
                    persistence = FilePersistence(state_path)
        self.template_miner = TemplateMiner(persistence, config=config)
        self.log_df = pd.DataFrame()
        self.results = pd.DataFrame()

    def parse_logs(self, fpath):
        """
        Parse a full log file: extract timestamps, run Drain3 on every line.

        If a .parquet cache already exists, returns cached results.

        Args:
            fpath: Path to the log file to parse.

        Returns:
            Tuple of (DataFrame with columns [timestamp, loglines, template,
            parameter_list], Path to parquet cache or None).
        """
        result_file_path = Path(str(fpath) + ".parquet")
        tmp_result_file_path = Path(str(fpath) + ".parquet.tmp")

        # Return cached result if available
        if os.path.exists(result_file_path):
            return pd.read_parquet(result_file_path), result_file_path

        self.log_df = self._read_logs(fpath)
        if self.log_df.empty:
            return pd.DataFrame(), None

        self.results = pd.DataFrame()

        def extract_template_and_args(logline):
            """Extract Drain3 template and parameters from a log line."""
            result = self.template_miner.add_log_message(logline)
            template = result["template_mined"]
            params = self.template_miner.get_parameter_list(template, logline)
            return template, params

        # Apply Drain3 to each log line
        self.log_df[["template", "parameter_list"]] = self.log_df["loglines"].apply(
            lambda x: pd.Series(list(extract_template_and_args(x)))
        )

        self.results = self.log_df[['timestamp', 'loglines', 'template', 'parameter_list']].copy()
        self.results.to_parquet(tmp_result_file_path, index=False)
        os.replace(str(tmp_result_file_path), str(result_file_path))

        try:
            self.template_miner.save_state()
        except Exception:
            pass

        return self.results, result_file_path

    def parse_lines(
        self,
        lines: List[str],
        source_name: str,
        source_files: Optional[List[str]] = None,
    ) -> Tuple[pd.DataFrame, Optional[Path]]:
        """
        Parse pre-filtered lines through Drain3 (rg+Drain3 pipeline entry).

        This method accepts lines that have been pre-filtered by ripgrep,
        extracts timestamps, and runs Drain3 template extraction only on
        the filtered subset. This is 6-10x faster than full-file parsing.

        Args:
            lines: Pre-filtered log lines from ripgrep.
            source_name: Identifier for cache naming (e.g., "wireless_rg").
            source_files: Optional list of source filenames (one per line,
                         same length as ``lines``). Stored as a ``source_file``
                         column in the parquet so the Pattern page can filter
                         by individual file within a domain.

        Returns:
            Tuple of (DataFrame with columns [timestamp, loglines, template,
            source_file?], Path to parquet cache file or None).

        Note:
            parameter_list is NOT extracted during bulk indexing for performance.
            Use ``extract_parameters()`` on a subset of rows for on-demand
            parameter extraction (e.g. when the user selects a specific template).

        Example:
            >>> parser = Pattern(project_dir=Path("my_project"))
            >>> rg_lines = ["2025-01-29T14:30:45 WiFi client disconnected"]
            >>> df, path = parser.parse_lines(rg_lines, "wireless_rg")
        """
        if not lines:
            logger.info(f"[Pattern] No lines to parse for {source_name}")
            return pd.DataFrame(), None

        # Determine parquet cache path
        if self.project_dir:
            parquet_path = Path(self.project_dir) / f"{source_name}.parquet"
        else:
            parquet_path = Path(f"{source_name}.parquet")
        tmp_path = parquet_path.with_suffix(".parquet.tmp")

        # Build extra columns dict for data that should survive sort/filter
        extra = {}
        if source_files and len(source_files) == len(lines):
            extra["source_file"] = source_files

        # Convert lines to DataFrame with timestamp extraction
        log_df = self._logs_to_dataframe(lines, extra_columns=extra or None)
        if log_df.empty:
            logger.warning(f"[Pattern] No parseable lines for {source_name}")
            return pd.DataFrame(), None

        # Extract templates via Drain3 (parameter extraction is deferred
        # to on-demand calls via extract_parameters() for performance).
        start = time.perf_counter()
        templates = []
        for logline in log_df["loglines"]:
            result = self.template_miner.add_log_message(logline)
            templates.append(result["template_mined"])
        elapsed = time.perf_counter() - start

        logger.info(
            f"[Pattern] parse_lines: {len(log_df)} lines -> "
            f"template extraction took {elapsed:.4f}s for {source_name}"
        )

        log_df["template"] = templates

        # Prepare result -- include source_file if available
        cols = ["timestamp", "loglines", "template"]
        if "source_file" in log_df.columns:
            cols.append("source_file")
        result_df = log_df[cols].copy()

        # Save to parquet cache (atomic write)
        result_df.to_parquet(tmp_path, index=False)
        os.replace(str(tmp_path), str(parquet_path))

        # Save Drain3 state for incremental learning
        try:
            self.template_miner.save_state()
        except Exception:
            pass

        return result_df, parquet_path
    
    def _read_logs(self, fpath):
        logdf = pd.DataFrame()
        try:
            with open(fpath, "r", encoding='utf-8', errors='ignore') as fin:
                lines = fin.readlines()
                start = time.perf_counter()
                logdf = self._logs_to_dataframe(lines)
                end = time.perf_counter()
                print(f"Execution time: {end - start:.4f} seconds")
        except Exception as e:
            print("Read log file failed. Exception {} filename {}".format(e, fpath))
        #print(logdf)
        return logdf


    def _logs_to_dataframe(self, log_lines, extra_columns=None):
        """
        Convert raw log lines to a DataFrame with timestamp extraction.

        Args:
            log_lines: List of raw log line strings.
            extra_columns: Optional dict mapping column name to a list of
                values (same length as ``log_lines``). These columns are
                carried through all sort/filter steps alongside the log data.
                Example: ``{"source_file": ["uuid1.txt", "uuid2.txt", ...]}``
        """
        if not log_lines:
            return pd.DataFrame()

        # Step 1: Extract timestamp + logline using your regex
        matches = [self.preprocess_regex.match(log) for log in log_lines]
        data = [
            (m.group("timestamp"), m.group("loglines")) if m else (None, log)
            for log, m in zip(log_lines, matches)
        ]
        df = pd.DataFrame(data, columns=["raw_timestamp", "loglines"])

        # Attach any extra columns early so they survive sort/filter steps
        if extra_columns:
            for col_name, col_values in extra_columns.items():
                if len(col_values) == len(df):
                    df[col_name] = col_values

        # Step 2: Parse timestamps robustly (does NOT touch hostapd float uptimes)
        def try_parse(ts):
            if pd.isna(ts) or not isinstance(ts, str) or not ts.strip():
                return pd.NaT

            ts = ts.strip()

            # Skip pure uptime floats here; convert later using base_time
            if re.match(r"^\d+\.\d+$", ts):
                return pd.NaT

            # YYYY-MM-DD-HH-MM-SS fallback
            if re.match(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$", ts):
                try:
                    return datetime.strptime(ts, "%Y-%m-%d-%H-%M-%S")
                except Exception:
                    return pd.NaT

            # short ISO like 230102-12:34:56.123 -> parse manually
            if re.match(r"^\d{6}-\d{2}:\d{2}:\d{2}\.\d+", ts):
                try:
                    # take YYMMDD-HH:MM:SS (first 15 chars)
                    return datetime.strptime(ts[:15], "%y%m%d-%H:%M:%S")
                except Exception:
                    pass

            # syslog style (e.g. "Sep  3 00:28:37") - dateparser will default year=1900
            if re.match(r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}$", ts):
                dt = dateparser.parse(ts)
                if dt:
                    # Inject current year later (use base_time year)
                    return dt

            # fallback to dateparser for everything else
            dt = dateparser.parse(ts)
            if dt is None:
                return pd.NaT

            # If aware, normalize to UTC-naive
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

            return dt

        df["timestamp"] = df["raw_timestamp"].apply(try_parse)

        # Quick diagnostic
        parsed_count = df["timestamp"].notna().sum()
        print(f"Parsed timestamps: {parsed_count}/{len(df)}")

        # Step 3: Determine base_time using only parsed timestamps (no forward-fill yet)
        real_times = df["timestamp"].dropna()
        if not real_times.empty:
            # use min parsed time as base
            base_time = real_times.min()
        else:
            base_time = datetime.now()
        #print(f"Base time for hostapd timestamps: {base_time}")

        # Step 4: Convert hostapd uptime floats (raw_timestamp matches float pattern)
        def convert_hostapd_value(ts, base):
            try:
                if isinstance(ts, str) and re.match(r"^\d+\.\d+$", ts):
                    return base + timedelta(seconds=float(ts))
            except Exception:
                pass
            return pd.NaT

        hostapd_mask = df["timestamp"].isna() & df["raw_timestamp"].notna() & df["raw_timestamp"].astype(str).str.match(r"^\d+\.\d+$")
        if hostapd_mask.any():
            df.loc[hostapd_mask, "timestamp"] = df.loc[hostapd_mask, "raw_timestamp"].apply(lambda x: convert_hostapd_value(x, base_time))

        # Step 5: Forward-fill timestamps for continuation / non-timestamped lines
        # Naive forward-fill example (may over-fill in some cases):
        df["timestamp"] = df["timestamp"].ffill()

        # Step 6: Syslog-style year injection (only operate where timestamp exists and year==1900)
        try:
            syslog_mask = df["timestamp"].notna() & (df["timestamp"].dt.year == 1900)
            if syslog_mask.any():
                current_year = base_time.year
                df.loc[syslog_mask, "timestamp"] = df.loc[syslog_mask, "timestamp"].apply(lambda dt: dt.replace(year=current_year))
        except Exception as e:
            print("Syslog year injection failed:", e)

        # Step 7: Final normalization: ensure dtype is datetime64[ns] and tz-naive
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.tz_localize(None)

        # Step 8: Sort (NaT will be placed last)
        df = df.sort_values("timestamp", na_position="last").reset_index(drop=True)

        remaining_nat = df["timestamp"].isna().sum()
        if remaining_nat:
            print(f"Remaining NaT timestamps after processing: {remaining_nat}")

        # Step 9: Cleanup loglines (strip, remove empty lines)
        df = self.cleanup_loglines(df)
        return df

    def cleanup_loglines(self, df):
        df["loglines"] = df["loglines"].astype(str).str.strip()
        df = df[df["loglines"].ne("")]   # keep non-empty rows only
        df = df[~df["loglines"].eq("\\n")]  # drop literal "\n" if any
        df = df[~df["loglines"].eq("\n")]   # drop actual newline-only lines
        df = df.reset_index(drop=True)
        return df
    
    def _normalize_timestamp(ts_str, base_time=None):
        """
        Try to parse timestamp string into datetime.
        - If it's a float-like uptime (e.g. 175383.097855), convert to base_time + timedelta
        - Else, use dateutil.parser
        """
        try:
            # hostapd uptime style
            if re.match(r"^\d+\.\d+$", ts_str):
                if base_time is None:
                    # Default base: UNIX epoch (1970-01-01)
                    base_time = datetime(1970, 1, 1)
                seconds = float(ts_str)
                return base_time + timedelta(seconds=seconds)
            
            # try parsing standard datetime formats
            return dateparser.parse(ts_str)
        except Exception:
            return None


def extract_parameters(
    template: str,
    loglines: List[str],
    project_dir: str = None,
    domain: str = None,
) -> List[list]:
    """
    Extract positional parameters from log lines using Drain3's native API.

    Uses ``TemplateMiner.get_parameter_list(template, logline)`` which
    correctly handles all masking tokens (``<*>``, ``<THREADID>``,
    ``<IP>``, ``<NUM>``, ``<MAC>``, ``<DATETIME>``, etc.) as defined
    in ``drain3.ini``.

    When ``project_dir`` and ``domain`` are provided, loads the saved
    Drain3 state so the miner has full template knowledge. Otherwise
    creates a fresh miner (still works -- ``get_parameter_list`` only
    needs the config masking rules, not learned templates).

    Args:
        template: Drain3 template string (e.g. "User <*> logged in at <NUM>").
        loglines: List of original log line strings matching this template.
        project_dir: Optional project directory containing Drain3 state files.
        domain: Optional domain name for loading the per-domain state.

    Returns:
        List of parameter lists, one per log line. Each is a list of
        extracted wildcard values.

    Example:
        >>> extract_parameters("User <NUM> logged in", ["User 123 logged in"])
        [["123"]]
    """
    if not template or not loglines:
        return [[] for _ in loglines]

    # Load a TemplateMiner with the masking config from drain3.ini.
    # If a saved state exists for the domain, load it for accuracy.
    try:
        config = TemplateMinerConfig()
        config.load("drain3.ini")

        persistence = None
        if project_dir and domain:
            state_path = os.path.join(str(project_dir), f"drain3_{domain}.json")
            if os.path.exists(state_path):
                persistence = FilePersistence(state_path)

        miner = TemplateMiner(persistence, config=config)
    except Exception as e:
        logger.warning(f"[extract_parameters] Failed to init TemplateMiner: {e}")
        return [[] for _ in loglines]

    result = []
    for line in loglines:
        try:
            params = miner.get_parameter_list(template, str(line))
            result.append(params if params else [])
        except Exception:
            result.append([])

    return result

