"""SelfHeal analytics: on-disk cache (Parquet) and fleet insight builders."""

from .cache_io import (
    RAW_SELFHEAL_PARQUET_NAME,
    load_raw_selfheal_dict,
    migrate_json_cache_if_present,
    save_raw_selfheal_dict,
)
from .insights import (
    build_selfheal_insights_dataframe,
    build_selfheal_insights_row,
    key_metrics_from_insights_row,
    selfheal_insights_empty_schema,
)

__all__ = [
    "RAW_SELFHEAL_PARQUET_NAME",
    "build_selfheal_insights_dataframe",
    "build_selfheal_insights_row",
    "key_metrics_from_insights_row",
    "load_raw_selfheal_dict",
    "migrate_json_cache_if_present",
    "save_raw_selfheal_dict",
    "selfheal_insights_empty_schema",
]
