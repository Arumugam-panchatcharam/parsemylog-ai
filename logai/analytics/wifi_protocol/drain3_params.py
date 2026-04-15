"""Batch Drain3 ``extract_parameters`` for wireless templates."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import polars as pl

from logai.pattern import build_template_miner_for_extract, extract_parameters_with_miner

logger = logging.getLogger(__name__)


def add_parameter_list_column(
    df: pl.DataFrame,
    project_dir: Path,
    domain: str = "wireless",
) -> pl.DataFrame:
    """
    Add ``parameter_list`` as a list-of-strings column using Drain3, grouped by template.
    """
    if df.height == 0:
        return df

    if "template" not in df.columns or "loglines" not in df.columns:
        logger.warning("add_parameter_list_column: missing template/loglines; skipping")
        return df.with_columns(
            pl.lit([]).cast(pl.List(pl.Utf8)).alias("parameter_list")
        )

    df_idx = df.with_row_index("_param_row_idx")
    n = df_idx.height
    params_col: List[List[str]] = [[] for _ in range(n)]

    miner = build_template_miner_for_extract(project_dir=project_dir, domain=domain)
    if miner is None:
        logger.warning(
            "add_parameter_list_column: TemplateMiner unavailable; parameter_list empty"
        )
        return df_idx.drop("_param_row_idx").with_columns(
            pl.lit([]).cast(pl.List(pl.Utf8)).alias("parameter_list")
        )

    templates = df_idx["template"].unique().to_list()
    for tpl in templates:
        if tpl is None or str(tpl).strip() == "":
            continue
        sub = df_idx.filter(pl.col("template") == tpl)
        indices = sub["_param_row_idx"].to_list()
        lines = [str(x) for x in sub["loglines"].to_list()]
        template_str = str(tpl)
        try:
            extracted = extract_parameters_with_miner(miner, template_str, lines)
        except Exception as e:
            logger.warning(
                "extract_parameters_with_miner failed for template prefix %r: %s",
                template_str[:80],
                e,
            )
            extracted = [[] for _ in lines]
        for i, p in zip(indices, extracted):
            params_col[i] = list(p) if p else []

    return df_idx.drop("_param_row_idx").with_columns(
        pl.Series("parameter_list", params_col, dtype=pl.List(pl.Utf8))
    )
