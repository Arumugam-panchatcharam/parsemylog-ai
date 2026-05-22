"""Load raw CPE log files when lines are missing from *_rg.parquet."""

from __future__ import annotations

import fnmatch
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set

import polars as pl

from logai.analytics.wifi_protocol.event_map import _glob_to_polars_regex

logger = logging.getLogger(__name__)

_LOG_TS_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
_DEFAULT_MAX_LINES = 500_000


def collect_globs_from_events(events: Dict[str, Any]) -> Set[str]:
    """Collect non-empty ``source_file_glob`` from event bodies and matchers."""
    globs: Set[str] = set()
    for spec in events.values():
        if not isinstance(spec, dict):
            continue
        fg = spec.get("source_file_glob")
        if isinstance(fg, str) and fg.strip():
            globs.add(fg.strip())
        for m in spec.get("matchers") or []:
            if not isinstance(m, dict):
                continue
            and_list = m.get("and")
            if isinstance(and_list, list):
                for sub in and_list:
                    if isinstance(sub, dict):
                        g = sub.get("source_file_glob")
                        if isinstance(g, str) and g.strip():
                            globs.add(g.strip())
            elif m.get("source_file_glob"):
                g = str(m["source_file_glob"])
                if g.strip():
                    globs.add(g.strip())
    return globs


def _glob_matches_any_source(parquet_df: pl.DataFrame, glob_pat: str) -> bool:
    if parquet_df.height == 0 or "source_file" not in parquet_df.columns:
        return False
    rx = _glob_to_polars_regex(glob_pat)
    hit = parquet_df.filter(
        pl.col("source_file").fill_null("").str.contains(rx)
    )
    return hit.height > 0


def globs_needing_raw_fallback(parquet_df: pl.DataFrame, globs: Set[str]) -> List[str]:
    """Globs with no matching ``source_file`` rows in parquet."""
    out: List[str] = []
    for g in sorted(globs):
        if not _glob_matches_any_source(parquet_df, g):
            out.append(g)
    return out


def _parse_line_timestamp(line: str) -> datetime | None:
    m = _LOG_TS_RE.search(line)
    if not m:
        return None
    raw = m.group(1).replace(" ", "T")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _files_matching_glob(cpe_dir: Path, glob_pat: str) -> List[Path]:
    if not cpe_dir.is_dir():
        return []
    names = [p.name for p in cpe_dir.iterdir() if p.is_file()]
    matched = [n for n in names if fnmatch.fnmatch(n, glob_pat)]
    return sorted(cpe_dir / n for n in matched)


def load_raw_lines_for_globs(
    cpe_dir: Path,
    globs: Set[str],
    *,
    max_lines_per_file: int = _DEFAULT_MAX_LINES,
) -> tuple[pl.DataFrame, List[str]]:
    """
    Read raw log files under ``cpe_dir`` for each fnmatch glob.

    Returns:
        (dataframe, list of file basenames read)
    """
    rows: List[Dict[str, Any]] = []
    files_read: List[str] = []

    for glob_pat in sorted(globs):
        for path in _files_matching_glob(cpe_dir, glob_pat):
            if path.name in files_read:
                continue
            try:
                count = 0
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if count >= max_lines_per_file:
                            logger.warning(
                                "Truncating raw read at %s lines: %s",
                                max_lines_per_file,
                                path.name,
                            )
                            break
                        text = line.rstrip("\n\r")
                        if not text.strip():
                            continue
                        rows.append(
                            {
                                "loglines": text,
                                "source_file": path.name,
                                "template": "",
                                "timestamp": _parse_line_timestamp(text),
                                "data_source": "raw",
                            }
                        )
                        count += 1
                if count > 0:
                    files_read.append(path.name)
            except OSError as e:
                logger.warning("Could not read raw log %s: %s", path, e)

    if not rows:
        return (
            pl.DataFrame(
                schema={
                    "loglines": pl.Utf8,
                    "source_file": pl.Utf8,
                    "template": pl.Utf8,
                    "timestamp": pl.Datetime("us"),
                    "data_source": pl.Utf8,
                }
            ),
            files_read,
        )

    return pl.DataFrame(rows), files_read
