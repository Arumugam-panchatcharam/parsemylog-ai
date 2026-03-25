"""
Log viewer: materialized invert-filter view (same directory as the log).

When "Remove Duplicate" is on, enabled regexes are OR-merged into ripgrep -v:
lines matching any pattern are dropped; the rest are written to a sidecar file.
Viewer + search use that file only; line numbers are 1-based in the alias file.

Sidecars:
  <original>.logview-dedup   — filtered text (invert match vs. enabled patterns)
  <original>.logview-dedup.meta — staleness (orig mtime/size + config hash)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

LOG_VIEWER_DEDUP_FILENAME = "log_viewer_dedup_patterns.json"
LOGVIEW_DEDUP_SUFFIX = ".logview-dedup"


def materialized_paths(original: Path) -> tuple[Path, Path]:
    """Alias body + .meta, same directory as original."""
    r = original.resolve()
    base = Path(str(r) + LOGVIEW_DEDUP_SUFFIX)
    return base, Path(str(base) + ".meta")


def dedup_materialization_signature(cfg: dict[str, Any]) -> str:
    plist = cfg.get("patterns") or []
    rows: list[tuple[str, str, bool]] = []
    if isinstance(plist, list):
        for p in plist:
            if not isinstance(p, dict):
                continue
            rows.append(
                (
                    str(p.get("id", "")),
                    str(p.get("regex", "")),
                    bool(p.get("enabled", True)),
                )
            )
    blob = json.dumps(
        {"dedup_active": bool(cfg.get("dedup_active")), "patterns": rows},
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _orig_stat_fields(path: Path) -> tuple[int, int]:
    st = path.stat()
    try:
        mtime_ns = st.st_mtime_ns
    except AttributeError:
        mtime_ns = int(st.st_mtime * 1_000_000_000)
    return mtime_ns, int(st.st_size)


def enabled_invert_patterns(cfg: dict[str, Any]) -> list[str]:
    """Regex strings for rg -v -e … (lines matching any are omitted)."""
    out: list[str] = []
    plist = cfg.get("patterns") or []
    if not isinstance(plist, list):
        return out
    for p in plist:
        if not isinstance(p, dict) or not p.get("enabled", True):
            continue
        r = str(p.get("regex", "")).strip()
        if r:
            out.append(r)
    return out


def compile_enabled_patterns(
    patterns: list[dict[str, Any]],
) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for p in patterns:
        if not p.get("enabled"):
            continue
        r = str(p.get("regex", "")).strip()
        if not r:
            continue
        compiled.append(re.compile(r, re.IGNORECASE))
    return compiled


def _invert_filter_python(lines: list[str], compiled: list[re.Pattern[str]]) -> list[str]:
    return [ln for ln in lines if not any(c.search(ln) for c in compiled)]


def ensure_dedup_materialized(original: Path, cfg: dict[str, Any]) -> None:
    """Write <original>.logview-dedup (+ meta) if missing or stale."""
    pats = enabled_invert_patterns(cfg)
    if not pats:
        return
    body, meta_p = materialized_paths(original)
    sig = dedup_materialization_signature(cfg)
    mtime_ns, size = _orig_stat_fields(original)
    need = True
    if body.is_file() and meta_p.is_file():
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            need = (
                meta.get("sig") != sig
                or int(meta.get("mtime_ns", -1)) != mtime_ns
                or int(meta.get("size", -1)) != size
                or "alias_line_count" not in meta
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            need = True
    if not need:
        return

    with open(original, "rb") as f:
        content = f.read()
    orig_lines = [
        line.decode("utf-8", errors="ignore").rstrip("\r\n")
        for line in content.split(b"\n")
    ]
    if orig_lines and orig_lines[-1] == "":
        orig_lines = orig_lines[:-1]
    orig_count = len(orig_lines)

    rg = shutil.which("rg")
    text_out: str
    if rg:
        cmd = [
            rg,
            "-v",
            "-i",
            "-N",
            "--no-heading",
            "--max-filesize",
            "50M",
        ]
        for p in pats:
            cmd.extend(["-e", p])
        cmd.append(str(original))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
        except (subprocess.TimeoutExpired, OSError):
            compiled = compile_enabled_patterns(cfg.get("patterns") or [])
            kept = _invert_filter_python(orig_lines, compiled)
            text_out = "\n".join(kept) + ("\n" if kept else "")
        else:
            if proc.returncode not in (0, 1):
                compiled = compile_enabled_patterns(cfg.get("patterns") or [])
                kept = _invert_filter_python(orig_lines, compiled)
                text_out = "\n".join(kept) + ("\n" if kept else "")
            else:
                kept = (proc.stdout or "").splitlines()
                text_out = "\n".join(kept) + ("\n" if kept else "")
    else:
        compiled = compile_enabled_patterns(cfg.get("patterns") or [])
        kept = _invert_filter_python(orig_lines, compiled)
        text_out = "\n".join(kept) + ("\n" if kept else "")

    meta_obj = {
        "sig": sig,
        "mtime_ns": mtime_ns,
        "size": size,
        "orig_line_count": orig_count,
        "alias_line_count": len((text_out or "").splitlines()),
    }
    tmp_body = Path(str(body) + ".tmp")
    tmp_meta = Path(str(meta_p) + ".tmp")
    try:
        tmp_body.write_text(text_out, encoding="utf-8")
        tmp_meta.write_text(json.dumps(meta_obj, indent=2), encoding="utf-8")
        os.replace(tmp_body, body)
        os.replace(tmp_meta, meta_p)
    except OSError:
        for p in (tmp_body, tmp_meta):
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass
        raise


def read_alias_view(original: Path) -> tuple[list[str], int]:
    """Lines in the alias file (1-based indices in viewer) + original line count from meta."""
    body, meta_p = materialized_paths(original)
    raw = body.read_bytes()
    lines = [
        line.decode("utf-8", errors="ignore").rstrip("\r\n")
        for line in raw.split(b"\n")
    ]
    if lines and lines[-1] == "":
        lines = lines[:-1]
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    orig_line_count = int(meta.get("orig_line_count", 0))
    return lines, orig_line_count


def line_to_content_pages(lines: list[str], lpp: int) -> dict[int, int]:
    if lpp < 1:
        lpp = 1000
    return {ln: ((ln - 1) // lpp + 1) for ln in range(1, len(lines) + 1)}


def dedup_patterns_path(project_dir: Path) -> Path:
    return project_dir / LOG_VIEWER_DEDUP_FILENAME


def load_dedup_config(path: Path) -> dict[str, Any]:
    default: dict[str, Any] = {"dedup_active": False, "patterns": []}
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return default
    if not isinstance(data, dict):
        return default
    plist = data.get("patterns")
    if not isinstance(plist, list):
        plist = []
    out_patterns: list[dict[str, Any]] = []
    for p in plist:
        if not isinstance(p, dict):
            continue
        if "id" not in p or "name" not in p or "regex" not in p:
            continue
        out_patterns.append(
            {
                "id": str(p["id"]),
                "name": str(p["name"]),
                "regex": str(p["regex"]),
                "enabled": bool(p.get("enabled", True)),
            }
        )
    return {
        "dedup_active": bool(data.get("dedup_active", False)),
        "patterns": out_patterns,
    }


def validate_patterns_json(patterns: Any) -> tuple[str | None, list[dict[str, Any]]]:
    if not isinstance(patterns, list):
        return "patterns must be an array", []
    out: list[dict[str, Any]] = []
    for p in patterns:
        if not isinstance(p, dict):
            continue
        pid, name, regex = p.get("id"), p.get("name"), p.get("regex")
        if pid is None or name is None or regex is None:
            continue
        rs = str(regex).strip()
        if not rs:
            return f"Empty regex in pattern: {name}", []
        try:
            re.compile(rs, re.IGNORECASE)
        except re.error as e:
            return f"Invalid regex in pattern “{name}”: {e}", []
        out.append(
            {
                "id": str(pid),
                "name": str(name),
                "regex": rs,
                "enabled": bool(p.get("enabled", True)),
            }
        )
    return None, out
