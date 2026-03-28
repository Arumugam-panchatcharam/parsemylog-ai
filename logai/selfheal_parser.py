"""
SelfHeal.txt Parser
===================

Parses ``SelfHeal.txt`` log files to extract periodic memory snapshots and
CPU usage samples. Each snapshot contains a process list with RSS values
and /proc/meminfo data, allowing analysis of memory trends and identification
of memory leaks or anomalies.

Snapshot Structure (periodic, ~6 minutes apart):
- Asterisk delimiter (``***``)
- Wall-clock timestamp (e.g., "Fri Feb 20 21:03:57 UTC 2026")
- Memory summary line (``Mem total:..., anon:..., map:..., free:...``)
- Process table header + rows (PID, VSZ, VSZRW, RSS, SHR, DIRTY, STACK, COMMAND)
- /proc/meminfo dump (MemTotal, MemFree, MemAvailable, etc.)
- CachedMemory summary line

Continuous Data:
- CPU usage samples: ``RDKB_SELFHEAL : CPU usage is <N> at timestamp ...``

Usage:
    >>> from logai.selfheal_parser import parse_selfheal_file
    >>> result = parse_selfheal_file(project_dir, cpe_serial)
    >>> print(result["summary"]["peak_memory_usage_pct"])
"""

from __future__ import annotations

import logging
import re
import shlex
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for parsing
# ---------------------------------------------------------------------------

# Snapshot delimiter and timestamp
_SNAPSHOT_DELIMITER_RE = re.compile(r"\*{5,}")
_SNAPSHOT_TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+(\w+\s+\w+\s+\d{2}\s+\d{2}:\d{2}:\d{2}\s+UTC\s+\d{4})"
)

# Memory summary lines
_MEM_SUMMARY_RE = re.compile(
    r"Mem total:(\d+)\s+anon:(\d+)\s+map:(\d+)\s+free:(\d+)"
)
_SLAB_SUMMARY_RE = re.compile(
    r"slab:(\d+)\s+buf:(\d+)\s+cache:(\d+)\s+dirty:(\d+)\s+write:(\d+)"
)

# Process table header marker
_PROCESS_TABLE_HEADER_RE = re.compile(r"PID\^{3}VSZ\^VSZRW\s+RSS")

# Process table row (flexible parsing for variable spacing; VSZ/VSZRW may use k/m/g suffix)
_PROCESS_ROW_RE = re.compile(
    r"^\s*(\d+)\s+(\d+|[0-9]+[gmk])\s+(\d+|[0-9]+[gmk])\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.*)"
)

# /proc/meminfo: MemTotal, Active(anon), Inactive(file), etc.
_MEMINFO_FIELD_RE = re.compile(
    r"^([\w]+(?:\([^)]+\))?):\s+(\d+)\s+kB\s*$"
)

# CPU usage sample
_CPU_SAMPLE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+RDKB_SELFHEAL\s*:\s*CPU usage is (\d+)"
)

# Telemetry 2.0 feature flag
_TELEMETRY2_RE = re.compile(r"Telemetry 2\.0 feature is (true|false)", re.IGNORECASE)

# IPv6 presence
_IPV6_RE = re.compile(r"Global IPv6 is present", re.IGNORECASE)

# Swap info
_SWAP_INFO_RE = re.compile(r"^Swap total:(\d+)\s+free:(\d+)")

# `{threadname}`: if followed by a shell running a script, skip the whole line;
# if followed by a real binary (e.g. `{wdtctl} wdtd`), keep the binary name only.
_THREAD_NAME_PREFIX_RE = re.compile(r"^\{[^}]+\}\s+")

# Defunct/zombie state in ps/top: command shows as `[name]`
_ZOMBIE_COMM_RE = re.compile(r"^\[[^\]]+\]")

# How many applications to include in the top-process bar chart (peak list caps
# process-series retention; trend list is what the UI ranks by RSS increase).
SELFHEAL_RANKED_PROCESS_LIMIT = 80


def _rss_linear_trend_slope_kb_per_step(rss_values: List[int]) -> float:
    """
    Least-squares slope of total RSS (KB) vs equally spaced snapshot index.

    Positive slope means an overall increasing trend across the capture window.
    Uses OLS: slope = Σ((i - mean_x) * (y - mean_y)) / Σ((i - mean_x)²)
    where x = [0, 1, 2, ..., n-1]

    Optimization: Compute sums in single pass for O(n) time, constant space.
    """
    n = len(rss_values)
    if n < 2:
        return 0.0

    mean_x = (n - 1) / 2.0
    mean_y = sum(rss_values) / n

    # Single pass: compute both var_x and cov_xy simultaneously
    var_x = 0.0
    cov_xy = 0.0
    for i in range(n):
        dx = i - mean_x
        dy = rss_values[i] - mean_y
        var_x += dx * dx
        cov_xy += dx * dy

    if var_x <= 0:
        return 0.0

    return cov_xy / var_x

# Basenames treated as ephemeral shell/utilities (not product apps)
_EPHEMERAL_PROCESS_BASES_LOWER: frozenset[str] = frozenset(
    {
        "sleep",
        "sort",
        "crond",
        "cron",
        "top",
        "cat",
        "tac",
        "head",
        "tail",
        "grep",
        "awk",
        "sed",
        "find",
        "xargs",
        "nice",
        "ionice",
        "timeout",
        "watch",
        "ps",
        "pgrep",
        "pidof",
        "ls",
        "cp",
        "mv",
        "rm",
        "mkdir",
        "rmdir",
        "chmod",
        "chown",
        "ln",
        "logger",
        "stat",
        "date",
        "env",
        "printenv",
        "which",
        "id",
        "tee",
        "more",
        "less",
        "cut",
        "tr",
        "uniq",
        "wc",
        "expr",
        "test",
        "[",
        "true",
        "false",
        "echo",
        "printf",
        "readlink",
        "dirname",
        "basename",
        "ping",
        "curl",
        "dmcli",
        "wl"
    }
)


def _tokenize_command(command: str) -> List[str]:
    s = command.strip()
    if s.endswith(" &"):
        s = s[:-2].rstrip()
    try:
        return shlex.split(s, posix=True)
    except ValueError:
        return s.split()


def process_application_key(command: str) -> Optional[str]:
    """
    Map a full `top` command line to a single application name for charts/summaries.

    Uses the first argv token only (basename if absolute path); flags/options are ignored.
    Returns None for:
    - ``{thread} /bin/sh ...`` script helpers (thread + shell; not the real app)
    - Zombie / defunct rows ``[awk]``, ``[grep]``, …
    - ``execute_dir /etc/cron/...`` cron driver lines
    - Ephemeral utilities (sleep, sort, …)
    """
    if not command or not command.strip():
        return None

    cmd = command.strip()
    if cmd.endswith(" &"):
        cmd = cmd[:-2].rstrip()

    # RDK cron wrappers (not a persistent application)
    if cmd.startswith("execute_dir ") and "/etc/cron/" in cmd:
        return None

    wrapper = _THREAD_NAME_PREFIX_RE.match(cmd)
    if wrapper:
        remainder = cmd[wrapper.end() :].strip()
        first_tok = remainder.split(None, 1)[0] if remainder else ""
        if first_tok in (
            "/bin/sh",
            "/bin/bash",
            "/bin/dash",
            "/usr/bin/sh",
            "/usr/bin/bash",
            "sh",
            "bash",
            "dash",
        ):
            return None
        cmd = remainder

    parts = _tokenize_command(cmd)
    if not parts:
        return None

    first = parts[0]
    if _ZOMBIE_COMM_RE.match(first):
        return None
    if first.startswith("-"):
        return None

    base = PurePosixPath(first).name
    if not base:
        return None
    if base in ("&", "|", "&&", "||", ";"):
        return None
    if len(base) == 1 and not base.isalnum():
        return None
    if base.isdigit():
        return None

    blo = base.lower()
    if blo in _EPHEMERAL_PROCESS_BASES_LOWER:
        return None
    if blo in ("sh", "bash", "dash") and len(parts) > 1:
        return None

    return base


@dataclass
class ProcessSnapshot:
    """Single process record from a snapshot."""

    pid: int
    vsz_kb: int
    rss_kb: int
    shr_kb: int
    dirty_kb: int
    stack_kb: int
    command: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemInfoSnapshot:
    """Memory info fields from /proc/meminfo."""

    timestamp: str
    mem_total: int
    mem_free: int
    mem_available: int
    buffers: int
    cached: int
    swap_total: int
    swap_free: int
    active: int
    inactive: int
    slab: int
    sreclaimable: int
    sunreclaim: int
    committed_as: int
    commit_limit: int
    kernel_stack: int
    anonpages: int
    shmem: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Snapshot:
    """A complete periodic snapshot (every ~6 minutes)."""

    timestamp: str
    wall_clock: str
    mem_total: int
    mem_free_summary: int
    mem_available: int
    processes: List[ProcessSnapshot]
    meminfo: MemInfoSnapshot
    meminfo_all: Dict[str, int]
    cached_memory: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "wall_clock": self.wall_clock,
            "mem_total": self.mem_total,
            "mem_free_summary": self.mem_free_summary,
            "mem_available": self.mem_available,
            "processes": [p.to_dict() for p in self.processes],
            "meminfo": self.meminfo.to_dict(),
            "meminfo_all": dict(self.meminfo_all),
            "cached_memory": self.cached_memory,
        }


def _parse_size_value(val: str) -> int:
    """Convert size string (e.g., '100m', '50k', '2g') to KB."""
    val = val.strip().lower()
    if val.endswith("g"):
        return int(val[:-1]) * 1024 * 1024
    if val.endswith("m"):
        return int(val[:-1]) * 1024
    if val.endswith("k"):
        return int(val[:-1])
    return int(val)


_SIZE_TOKEN_RE = re.compile(r"^-?\d+$|^\d+[gmkGMK]$")


def _parse_process_row(line: str) -> Optional[ProcessSnapshot]:
    """
    Parse a single SelfHeal / ``top`` process row.

    RDK emits either:
    - **8 numeric fields** after PID: VSZ, VSZRW, RSS, SHR, DIRTY, …, STACK (stack is last)
    - **6 numeric fields** after PID: VSZ, RSS, SHR, DIRTY, STACK (no VSZRW — common on
      some builds); without this branch RSS was read from the wrong column.
    """
    raw = line.strip()
    raw = re.sub(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\s+",
        "",
        raw,
    )
    parts = raw.split()
    if len(parts) < 7:
        return None

    nums: List[str] = []
    try:
        nums.append(str(int(parts[0].replace(",", ""))))
    except ValueError:
        return None

    i = 1
    while i < len(parts):
        tok = parts[i].replace(",", "")
        if _SIZE_TOKEN_RE.match(tok):
            nums.append(tok)
            i += 1
        else:
            break

    command = " ".join(parts[i:]).strip()
    if not command:
        return None

    def _from_tokens() -> Optional[ProcessSnapshot]:
        try:
            if len(nums) == 6:
                return ProcessSnapshot(
                    pid=int(nums[0]),
                    vsz_kb=_parse_size_value(nums[1]),
                    rss_kb=int(nums[2]),
                    shr_kb=int(nums[3]),
                    dirty_kb=int(nums[4]),
                    stack_kb=int(nums[5]),
                    command=command,
                )
            if len(nums) == 8:
                return ProcessSnapshot(
                    pid=int(nums[0]),
                    vsz_kb=_parse_size_value(nums[1]),
                    rss_kb=int(nums[3]),
                    shr_kb=int(nums[4]),
                    dirty_kb=int(nums[5]),
                    stack_kb=int(nums[7]),
                    command=command,
                )
        except (ValueError, IndexError):
            return None
        return None

    snap = _from_tokens()
    if snap is not None:
        return snap

    raw_nc = raw.replace(",", "")
    match = _PROCESS_ROW_RE.match(raw_nc)
    if not match:
        return None

    try:
        pid = int(match.group(1))
        vsz = _parse_size_value(match.group(2))
        rss = int(match.group(4))
        shr = int(match.group(5))
        dirty = int(match.group(6))
        stack = int(match.group(8))
        cmd = match.group(9).strip()

        return ProcessSnapshot(
            pid=pid,
            vsz_kb=vsz,
            rss_kb=rss,
            shr_kb=shr,
            dirty_kb=dirty,
            stack_kb=stack,
            command=cmd,
        )
    except (ValueError, IndexError) as e:
        logger.debug("Failed to parse process row: %s - %s", line, e)
        return None


def _parse_meminfo_block(
    lines: List[str], meminfo_timestamp: str = ""
) -> Tuple[Optional[MemInfoSnapshot], Dict[str, int]]:
    """Parse /proc/meminfo block from lines (already stripped of ISO prefix per line)."""
    all_fields: Dict[str, int] = {}

    for line in lines:
        line = line.strip()
        if not line:
            break

        match = _MEMINFO_FIELD_RE.match(line)
        if match:
            field_name = match.group(1)
            value = int(match.group(2))
            all_fields[field_name] = value

    if not all_fields:
        return None, {}

    mem = MemInfoSnapshot(
        timestamp=meminfo_timestamp,
        mem_total=all_fields.get("MemTotal", 0),
        mem_free=all_fields.get("MemFree", 0),
        mem_available=all_fields.get("MemAvailable", 0),
        buffers=all_fields.get("Buffers", 0),
        cached=all_fields.get("Cached", 0),
        swap_total=all_fields.get("SwapTotal", 0),
        swap_free=all_fields.get("SwapFree", 0),
        active=all_fields.get("Active", 0),
        inactive=all_fields.get("Inactive", 0),
        slab=all_fields.get("Slab", 0),
        sreclaimable=all_fields.get("SReclaimable", 0),
        sunreclaim=all_fields.get("SUnreclaim", 0),
        committed_as=all_fields.get("Committed_AS", 0),
        commit_limit=all_fields.get("CommitLimit", 0),
        kernel_stack=all_fields.get("KernelStack", 0),
        anonpages=all_fields.get("AnonPages", 0),
        shmem=all_fields.get("Shmem", 0),
    )
    return mem, all_fields


def parse_snapshots(content: str) -> List[Snapshot]:
    """
    Extract periodic snapshots from SelfHeal.txt.

    Returns:
        List of Snapshot objects, ordered by timestamp.
    """
    snapshots: List[Snapshot] = []
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Look for snapshot delimiter (with optional timestamp prefix)
        if _SNAPSHOT_DELIMITER_RE.search(line):
            # Extract timestamp from current line if present
            iso_ts = ""
            match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
            if match:
                iso_ts = match.group(1)
            
            i += 1
            if i >= len(lines):
                break

            # Next line should be the wall-clock timestamp
            ts_line = lines[i]
            ts_match = _SNAPSHOT_TIMESTAMP_RE.match(ts_line)
            if not ts_match:
                # Try to extract ISO timestamp from this line
                ts_match_iso = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+(.+)", ts_line)
                if ts_match_iso:
                    iso_ts = ts_match_iso.group(1)
                    wall_clock = ts_match_iso.group(2)
                else:
                    i += 1
                    continue
            else:
                if not iso_ts:
                    iso_ts = ts_match.group(1)
                wall_clock = ts_match.group(2)

            i += 1

            # Parse memory summary
            if i >= len(lines):
                break
            mem_summary_line = lines[i]
            # Strip timestamp if present
            mem_summary_line = re.sub(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\s+", "", mem_summary_line)
            mem_match = _MEM_SUMMARY_RE.search(mem_summary_line)
            if not mem_match:
                i += 1
                continue

            mem_total = int(mem_match.group(1))
            mem_free_summary = int(mem_match.group(4))
            i += 1

            # Skip slab summary line
            if i < len(lines):
                i += 1

            # Find process table header
            while i < len(lines) and not _PROCESS_TABLE_HEADER_RE.search(lines[i]):
                i += 1

            if i >= len(lines):
                break

            i += 1
            processes: List[ProcessSnapshot] = []

            # Parse process rows until we hit Swap line
            while i < len(lines):
                proc_line = lines[i]
                if proc_line.strip().startswith("Swap total:"):
                    break

                proc = _parse_process_row(proc_line)
                if proc:
                    processes.append(proc)

                i += 1

            # Parse swap info
            if i < len(lines) and lines[i].strip().startswith("Swap total:"):
                i += 1

            # Parse /proc/meminfo block
            meminfo_lines: List[str] = []
            meminfo_iso = ""
            mem_available = mem_free_summary

            while i < len(lines):
                meminfo_raw = lines[i].strip()

                if not meminfo_raw:
                    i += 1
                    break

                if meminfo_raw.startswith("CachedMemory:") or re.sub(
                    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\s+",
                    "",
                    meminfo_raw,
                ).startswith("CachedMemory:"):
                    break

                iso_m = re.match(
                    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+", meminfo_raw
                )
                meminfo_content = re.sub(
                    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\s+", "", meminfo_raw
                )
                if meminfo_content.startswith("MemTotal") and iso_m:
                    meminfo_iso = iso_m.group(1)

                meminfo_lines.append(meminfo_content)
                i += 1

            meminfo, meminfo_all = _parse_meminfo_block(meminfo_lines, meminfo_iso)
            if meminfo:
                mem_available = meminfo.mem_available

            # Parse CachedMemory line
            cached_memory = 0
            if i < len(lines):
                cached_line = lines[i].strip()
                cached_line = re.sub(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\s+", "", cached_line)
                if cached_line.startswith("CachedMemory:"):
                    cached_match = re.match(r"CachedMemory:\s+(\d+)", cached_line)
                    if cached_match:
                        cached_memory = int(cached_match.group(1))
                    i += 1

            if meminfo:
                snapshot = Snapshot(
                    timestamp=iso_ts,
                    wall_clock=wall_clock,
                    mem_total=mem_total,
                    mem_free_summary=mem_free_summary,
                    mem_available=mem_available,
                    processes=processes,
                    meminfo=meminfo,
                    meminfo_all=meminfo_all,
                    cached_memory=cached_memory,
                )
                snapshots.append(snapshot)
        else:
            i += 1

    return snapshots


def parse_cpu_samples(content: str) -> List[Dict[str, Any]]:
    """
    Extract CPU usage samples from continuous RDKB_SELFHEAL lines.

    Returns:
        List of {timestamp, cpu_usage_pct} dicts.
    """
    samples: List[Dict[str, Any]] = []

    for line in content.split("\n"):
        match = _CPU_SAMPLE_RE.search(line)
        if match:
            timestamp = match.group(1)
            cpu_usage = int(match.group(2))
            samples.append({"timestamp": timestamp, "cpu_usage_pct": cpu_usage})

    return samples


def parse_device_flags(content: str) -> Dict[str, Any]:
    """
    Extract device flags (Telemetry 2.0, IPv6 support).

    Returns:
        Dict with telemetry2_enabled and ipv6_support booleans.
    """
    flags: Dict[str, Any] = {"telemetry2_enabled": None, "ipv6_support": False}

    for line in content.split("\n"):
        telemetry_match = _TELEMETRY2_RE.search(line)
        if telemetry_match:
            flags["telemetry2_enabled"] = (
                telemetry_match.group(1).lower() == "true"
            )

        if _IPV6_RE.search(line):
            flags["ipv6_support"] = True

    return flags


def _meminfo_from_dict(mi: Any) -> MemInfoSnapshot:
    """Build MemInfoSnapshot from cached JSON dict (or pass through dataclass)."""
    if isinstance(mi, MemInfoSnapshot):
        return mi
    d = mi if isinstance(mi, dict) else {}

    def _i(key: str) -> int:
        v = d.get(key, 0)
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    return MemInfoSnapshot(
        timestamp=str(d.get("timestamp", "")),
        mem_total=_i("mem_total"),
        mem_free=_i("mem_free"),
        mem_available=_i("mem_available"),
        buffers=_i("buffers"),
        cached=_i("cached"),
        swap_total=_i("swap_total"),
        swap_free=_i("swap_free"),
        active=_i("active"),
        inactive=_i("inactive"),
        slab=_i("slab"),
        sreclaimable=_i("sreclaimable"),
        sunreclaim=_i("sunreclaim"),
        committed_as=_i("committed_as"),
        commit_limit=_i("commit_limit"),
        kernel_stack=_i("kernel_stack"),
        anonpages=_i("anonpages"),
        shmem=_i("shmem"),
    )


def _snapshot_from_dict(s: Dict[str, Any]) -> Snapshot:
    """Rebuild Snapshot from ``parse_selfheal_file`` JSON (dict processes/meminfo)."""
    procs: List[ProcessSnapshot] = []
    for p in s.get("processes") or []:
        if not isinstance(p, dict):
            continue
        try:
            procs.append(
                ProcessSnapshot(
                    pid=int(p.get("pid", 0) or 0),
                    vsz_kb=int(p.get("vsz_kb", 0) or 0),
                    rss_kb=int(p.get("rss_kb", 0) or 0),
                    shr_kb=int(p.get("shr_kb", 0) or 0),
                    dirty_kb=int(p.get("dirty_kb", 0) or 0),
                    stack_kb=int(p.get("stack_kb", 0) or 0),
                    command=str(p.get("command", "")),
                )
            )
        except (TypeError, ValueError):
            continue
    meminfo = _meminfo_from_dict(s.get("meminfo"))
    ma = s.get("meminfo_all")
    meminfo_all: Dict[str, int] = {}
    if isinstance(ma, dict):
        for k, v in ma.items():
            try:
                meminfo_all[str(k)] = int(v)
            except (TypeError, ValueError):
                meminfo_all[str(k)] = 0

    def _si(key: str) -> int:
        v = s.get(key, 0)
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    return Snapshot(
        timestamp=str(s.get("timestamp", "")),
        wall_clock=str(s.get("wall_clock", "")),
        mem_total=_si("mem_total"),
        mem_free_summary=_si("mem_free_summary"),
        mem_available=_si("mem_available"),
        processes=procs,
        meminfo=meminfo,
        meminfo_all=meminfo_all,
        cached_memory=_si("cached_memory"),
    )


def _coerce_snapshots_for_summary(snapshots: List[Any]) -> List[Snapshot]:
    """Accept dataclass snapshots or dicts from ``raw_selfheal_cache.json``."""
    if not snapshots:
        return []
    first = snapshots[0]
    if isinstance(first, Snapshot):
        return [s for s in snapshots if isinstance(s, Snapshot)]
    out: List[Snapshot] = []
    for item in snapshots:
        if isinstance(item, Snapshot):
            out.append(item)
        elif isinstance(item, dict):
            out.append(_snapshot_from_dict(item))
    return out


def sort_snapshots_chronologically(snapshots: List[Any]) -> List[Any]:
    """Order snapshots by ISO ``timestamp`` then ``wall_clock`` (dict or ``Snapshot``)."""

    def sort_key(s: Any) -> tuple[str, str]:
        if isinstance(s, dict):
            return (str(s.get("timestamp") or ""), str(s.get("wall_clock") or ""))
        if isinstance(s, Snapshot):
            return (s.timestamp or "", s.wall_clock or "")
        return ("", "")

    return sorted(snapshots, key=sort_key)


def extract_summary(
    snapshots: List[Any], cpu_samples: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compute aggregated summary metrics from snapshots and samples.

    Returns:
        Dict with peak/avg memory, process stats, memory pressure indicators.
    """
    import time

    snapshots = _coerce_snapshots_for_summary(snapshots)
    
    snapshots = sort_snapshots_chronologically(snapshots)
    
    proc_rows = sum(len(s.processes) for s in snapshots)
    summary: Dict[str, Any] = {
        "snapshot_count": len(snapshots),
        "process_row_count": proc_rows,
        "cpu_sample_count": len(cpu_samples),
        "peak_memory_usage_pct": 0,
        "min_memory_available_kb": None,
        "avg_memory_available_kb": None,
        "mem_available_min_pct": None,
        "mem_available_avg_pct": None,
        "slab_ols_slope_kb_per_step": None,
        "total_user_rss_ols_slope_kb_per_step": None,
        "peak_cpu_usage_pct": 0,
        "avg_cpu_usage_pct": None,
        "alerts": [],
        "top_processes_by_rss": [],
        "top_processes_by_rss_trend": [],
        "memory_pressure_indicators": {},
        "overall_time_range": {},
    }

    if not snapshots:
        return summary

    # Same endpoints as ``rss_list[0]`` / ``rss_list[-1]`` (chronologically sorted snapshots).
    summary["overall_time_range"] = {
        "first": snapshots[0].timestamp or "",
        "last": snapshots[-1].timestamp or "",
    }

    # Memory statistics
    available_values = [s.meminfo.mem_available for s in snapshots if s.meminfo]
    total_values = [s.meminfo.mem_total for s in snapshots if s.meminfo]

    if available_values:
        summary["min_memory_available_kb"] = min(available_values)
        summary["avg_memory_available_kb"] = sum(available_values) / len(
            available_values
        )

        if total_values:
            peak_usage_pct = (
                100
                * (
                    max(total_values)
                    - min(available_values)
                )
                / max(total_values)
            )
            summary["peak_memory_usage_pct"] = round(peak_usage_pct, 2)

        # MemAvailable as % of MemTotal per snapshot (fleet histograms / pressure)
        memavail_pcts: List[float] = []
        for s in snapshots:
            mi = s.meminfo
            if mi and mi.mem_total > 0:
                memavail_pcts.append(100.0 * mi.mem_available / mi.mem_total)
        if memavail_pcts:
            summary["mem_available_min_pct"] = round(min(memavail_pcts), 2)
            summary["mem_available_avg_pct"] = round(
                sum(memavail_pcts) / len(memavail_pcts), 2
            )

    # CPU statistics
    if cpu_samples:
        cpu_values = [s["cpu_usage_pct"] for s in cpu_samples]
        summary["peak_cpu_usage_pct"] = max(cpu_values)
        summary["avg_cpu_usage_pct"] = round(sum(cpu_values) / len(cpu_values), 2)
    else:
        summary["avg_cpu_usage_pct"] = None

    # Per-snapshot total RSS by application (one value per snapshot index; 0 if absent
    # that snapshot). Sparse append-only lists skewed slopes and hid real end-to-end growth.
    # OPTIMIZATION: Cache command → app_key to avoid repeated regex on same commands
    cmd_to_app_cache: Dict[str, Optional[str]] = {}
    per_snapshot_totals: List[Dict[str, int]] = []
    all_app_keys: set[str] = set()
    for snapshot in snapshots:
        rss_by_app: Dict[str, int] = defaultdict(int)
        for proc in snapshot.processes:
            cmd = proc.command
            if cmd not in cmd_to_app_cache:
                cmd_to_app_cache[cmd] = process_application_key(cmd)
            app_key = cmd_to_app_cache[cmd]
            if app_key is None:
                continue
            rss_by_app[app_key] += proc.rss_kb
        snap_totals = dict(rss_by_app)
        per_snapshot_totals.append(snap_totals)
        all_app_keys.update(snap_totals.keys())

    nsnap = len(snapshots)

    # Slab vs total process RSS trends (fleet scatter: kernel vs userspace growth)
    total_rss_per_snap = [sum(p.rss_kb for p in s.processes) for s in snapshots]
    if nsnap >= 2 and total_rss_per_snap:
        summary["total_user_rss_ols_slope_kb_per_step"] = round(
            _rss_linear_trend_slope_kb_per_step(total_rss_per_snap), 4
        )
    slab_series = [s.meminfo.slab for s in snapshots if s.meminfo]
    if len(slab_series) >= 2:
        summary["slab_ols_slope_kb_per_step"] = round(
            _rss_linear_trend_slope_kb_per_step(slab_series), 4
        )

    process_rss_map: Dict[str, List[int]] = {
        app: [totals.get(app, 0) for totals in per_snapshot_totals]
        for app in all_app_keys
    }

    top_processes = sorted(
        [
            {
                "command": cmd,
                "peak_rss_kb": max(rss_list),
                "avg_rss_kb": round(sum(rss_list) / nsnap, 0) if nsnap else 0,
                "sample_count": nsnap,
            }
            for cmd, rss_list in process_rss_map.items()
        ],
        key=lambda x: x["peak_rss_kb"],
        reverse=True,
    )[:SELFHEAL_RANKED_PROCESS_LIMIT]

    summary["top_processes_by_rss"] = top_processes

    if len(all_app_keys) > SELFHEAL_RANKED_PROCESS_LIMIT * 5:
        # Optimization: only compute trends for top processes to save time
        top_keys = sorted(all_app_keys, key=lambda k: max(process_rss_map[k]), reverse=True)[:SELFHEAL_RANKED_PROCESS_LIMIT * 5]
        target_keys = set(top_keys)
    else:
        target_keys = all_app_keys

    trend_rows: List[Dict[str, Any]] = []
    if nsnap >= 2:
        denom = nsnap - 1
        for cmd in target_keys:
            rss_list = process_rss_map[cmd]
            ols = _rss_linear_trend_slope_kb_per_step(rss_list)
            first_v = rss_list[0]
            last_v = rss_list[-1]
            delta = last_v - first_v
            per_step = delta / denom
            if ols <= 0 and delta <= 0:
                continue
            effective = ols if ols > 0 else per_step
            trend_rows.append(
                {
                    "command": cmd,
                    "rss_trend_slope_kb": round(effective, 2),
                    "rss_ols_slope_kb": round(ols, 2),
                    "rss_first_kb": first_v,
                    "rss_last_kb": last_v,
                    "rss_delta_kb": delta,
                    "peak_rss_kb": max(rss_list),
                    "avg_rss_kb": round(sum(rss_list) / nsnap, 0),
                    "sample_count": nsnap,
                }
            )
        trend_rows.sort(key=lambda x: x["rss_trend_slope_kb"], reverse=True)
    summary["top_processes_by_rss_trend"] = trend_rows[:SELFHEAL_RANKED_PROCESS_LIMIT]

    # Memory pressure indicators
    alerts: List[str] = []
    if summary["min_memory_available_kb"] and summary["min_memory_available_kb"] < 50000:
        alerts.append("LOW_MEMORY")
        summary["memory_pressure_indicators"]["low_memory"] = True

    # Check SUnreclaim (kernel memory leak)
    sunreclaim_vals = [s.meminfo.sunreclaim for s in snapshots if s.meminfo]
    slab_vals = [s.meminfo.slab for s in snapshots if s.meminfo]

    if sunreclaim_vals and slab_vals:
        avg_sunreclaim_pct = (
            100 * sum(sunreclaim_vals) / len(sunreclaim_vals)
        ) / (sum(slab_vals) / len(slab_vals))
        summary["memory_pressure_indicators"]["sunreclaim_pct"] = round(
            avg_sunreclaim_pct, 2
        )

        if avg_sunreclaim_pct > 50:
            alerts.append("KERNEL_LEAK")

    # Cached as % of MemTotal (mean over snapshots with meminfo)
    cached_ratios: List[float] = []
    for s in snapshots:
        mi = s.meminfo
        if mi and mi.mem_total > 0:
            cached_ratios.append(100.0 * mi.cached / mi.mem_total)
    if cached_ratios:
        summary["memory_pressure_indicators"]["cached_pct_of_memtotal"] = round(
            sum(cached_ratios) / len(cached_ratios), 2
        )

    # Check overcommit
    committed_as_vals = [s.meminfo.committed_as for s in snapshots if s.meminfo]
    commit_limit_vals = [s.meminfo.commit_limit for s in snapshots if s.meminfo]

    if committed_as_vals and commit_limit_vals:
        avg_committed = sum(committed_as_vals) / len(committed_as_vals)
        avg_limit = sum(commit_limit_vals) / len(commit_limit_vals)

        if avg_limit > 0:
            overcommit_ratio = avg_committed / avg_limit
            summary["memory_pressure_indicators"]["overcommit_ratio"] = round(
                overcommit_ratio, 2
            )

            if overcommit_ratio > 0.8:
                alerts.append("OVERCOMMIT_RISK")

    # Check swap
    swap_totals = [s.meminfo.swap_total for s in snapshots if s.meminfo]
    if swap_totals and all(s == 0 for s in swap_totals):
        alerts.append("NO_SWAP")

    summary["alerts"] = alerts
    summary["chronological_order_applied"] = True

    _apply_memory_pressure_score(summary)

    return summary


def _apply_memory_pressure_score(summary: Dict[str, Any]) -> None:
    """
    Composite 0-100 (higher = worse). Components (each 0-1), weights 0.35/0.25/0.25/0.15:

    - Low MemAvailable: (100 - mem_available_min_pct) / 100
    - Overcommit ratio (capped at 1)
    - SUnreclaim share: sunreclaim_pct / 100
    - Positive slab OLS slope, normalized by 1000 KB/step
    """
    mpi = summary.get("memory_pressure_indicators") or {}
    w_avail, w_oc, w_sun, w_slab = 0.35, 0.25, 0.25, 0.15

    min_pct = summary.get("mem_available_min_pct")
    if isinstance(min_pct, (int, float)):
        c_avail = max(0.0, min(1.0, (100.0 - float(min_pct)) / 100.0))
    else:
        c_avail = 0.0

    oc = mpi.get("overcommit_ratio")
    c_oc = max(0.0, min(1.0, float(oc))) if isinstance(oc, (int, float)) else 0.0

    su = mpi.get("sunreclaim_pct")
    c_sun = (
        max(0.0, min(1.0, float(su) / 100.0)) if isinstance(su, (int, float)) else 0.0
    )

    slab_slope = summary.get("slab_ols_slope_kb_per_step")
    if isinstance(slab_slope, (int, float)) and float(slab_slope) > 0:
        c_slab = max(0.0, min(1.0, float(slab_slope) / 1000.0))
    else:
        c_slab = 0.0

    score = 100.0 * (
        w_avail * c_avail + w_oc * c_oc + w_sun * c_sun + w_slab * c_slab
    )
    summary["memory_pressure_indicators"]["pressure_score_0_100"] = round(score, 1)


def parse_selfheal_file(
    cpe_dir: Path,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Parse SelfHeal.txt for a CPE.

    Args:
        cpe_dir: Path to CPE directory containing SelfHeal.txt
        force: If True, skip cache and re-parse

    Returns:
        Dict with snapshots, cpu_samples, device_flags, summary.
    """
    selfheal_path = cpe_dir / "SelfHeal.txt"

    if not selfheal_path.exists():
        logger.warning(f"SelfHeal.txt not found at {selfheal_path}")
        return {
            "snapshots": [],
            "cpu_samples": [],
            "device_flags": {},
            "summary": {},
        }

    try:
        content = selfheal_path.read_text(errors="ignore")
    except Exception as e:
        logger.error(f"Failed to read SelfHeal.txt: {e}")
        return {
            "snapshots": [],
            "cpu_samples": [],
            "device_flags": {},
            "summary": {},
        }

    snapshots = sort_snapshots_chronologically(parse_snapshots(content))
    cpu_samples = parse_cpu_samples(content)
    device_flags = parse_device_flags(content)
    summary = extract_summary(snapshots, cpu_samples)

    return {
        "snapshots": [s.to_dict() for s in snapshots],
        "cpu_samples": cpu_samples,
        "device_flags": device_flags,
        "summary": summary,
        "source": str(selfheal_path),
    }
