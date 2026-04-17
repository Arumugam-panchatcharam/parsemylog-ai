"""
Raw SelfHeal parse cache on disk: Parquet-backed JSON payload (single row).

Legacy ``raw_selfheal_cache.json`` is still read once and migrated to Parquet
when encountered, so existing projects keep working.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import polars as pl

logger = logging.getLogger(__name__)

RAW_SELFHEAL_PARQUET_NAME = "raw_selfheal_cache.parquet"
RAW_SELFHEAL_JSON_LEGACY = "raw_selfheal_cache.json"


def _parquet_path(cpe_dir: Path) -> Path:
    return cpe_dir / RAW_SELFHEAL_PARQUET_NAME


def _json_path(cpe_dir: Path) -> Path:
    return cpe_dir / RAW_SELFHEAL_JSON_LEGACY


def save_raw_selfheal_dict(cpe_dir: Path, data: Dict[str, Any]) -> None:
    """Persist parsed SelfHeal structures as Parquet (JSON payload column)."""
    path = _parquet_path(cpe_dir)
    try:
        cpe_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str)
        pl.DataFrame({"payload_json": [payload]}).write_parquet(path)
        legacy = _json_path(cpe_dir)
        if legacy.is_file():
            try:
                legacy.unlink()
            except OSError:
                pass
    except Exception as e:
        logger.error("Failed to save raw selfheal Parquet cache %s: %s", path, e)


def migrate_json_cache_if_present(cpe_dir: Path) -> None:
    """If only legacy JSON exists, write Parquet alongside (idempotent if Parquet newer)."""
    js = _json_path(cpe_dir)
    pq = _parquet_path(cpe_dir)
    if not js.is_file():
        return
    if pq.is_file() and pq.stat().st_mtime >= js.stat().st_mtime:
        return
    try:
        data = json.loads(js.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(data, dict):
            save_raw_selfheal_dict(cpe_dir, data)
    except Exception as e:
        logger.warning("SelfHeal JSON→Parquet migration failed for %s: %s", cpe_dir, e)


def load_raw_selfheal_dict(cpe_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Load raw SelfHeal dict. Prefer Parquet; migrate legacy JSON to Parquet when read.
    """
    pq = _parquet_path(cpe_dir)
    if pq.is_file():
        try:
            df = pl.read_parquet(pq)
            if df.height == 0 or "payload_json" not in df.columns:
                return None
            raw = df["payload_json"][0]
            if raw is None:
                return None
            return json.loads(str(raw))
        except Exception as e:
            logger.warning("Failed to load raw selfheal Parquet %s: %s", pq, e)

    js = _json_path(cpe_dir)
    if js.is_file():
        try:
            data = json.loads(js.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                save_raw_selfheal_dict(cpe_dir, data)
                return data
        except Exception as e:
            logger.warning("Failed to load legacy raw selfheal JSON %s: %s", js, e)
    return None


def raw_selfheal_cache_mtime(cpe_dir: Path) -> float:
    """Latest mtime of raw cache artifact (Parquet or legacy JSON), or 0."""
    m = 0.0
    pq = _parquet_path(cpe_dir)
    js = _json_path(cpe_dir)
    if pq.is_file():
        m = max(m, pq.stat().st_mtime)
    if js.is_file():
        m = max(m, js.stat().st_mtime)
    return m
