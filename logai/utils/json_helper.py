import json, pathlib, pandas as pd
from typing import Union, Dict, Any
import pandas as pd
import re

def clean_json_string(raw_str):
    return re.sub(r'[\x00-\x1f\x7f]', '', raw_str)

def load_json(path: Union[str, pathlib.Path]) -> Any:
    """Read file, verify valid JSON, raise with context if broken."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
            cleaned = clean_json_string(raw)
            data = json.loads(cleaned)
            return data
    except json.JSONDecodeError as e:
        return None
        #raise ValueError(f"Bad JSON in {path} → {e}") from None

def _flatten(obj: Any, parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
    """Recursively flattens nested dicts/lists to a single-level dict."""
    items = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            items.update(_flatten(v, f"{parent_key}{k}{sep}" if parent_key else k, sep))
    elif isinstance(obj, list):
        for _, v in enumerate(obj):
            items.update(_flatten(v, f"{parent_key}{sep}" if parent_key else sep))
    else:
        items[parent_key.rstrip(sep)] = obj
    return items

def json_to_df(raw: Any) -> pd.DataFrame:
    """Normalise single-object or list-of-objects JSON to tidy DataFrame."""
    if isinstance(raw, list):
        rows = [_flatten(r) for r in raw]
    elif isinstance(raw, dict):
        # treat top-level dict as one row unless it obviously contains rows
        rows = ([_flatten(raw)] 
                if not all(isinstance(v, (list, dict)) for v in raw.values())
                else [_flatten(raw)])
    else:
        raise TypeError("Unsupported JSON structure")
    
    df = pd.DataFrame(rows)
    # OPTIONAL CLEAN-UP ---------
    df.replace({"": None, "null": None}, inplace=True)
    df.dropna(axis=1, how="all", inplace=True)         # drop empty cols
    df = df.convert_dtypes()                           # best-guess dtypes
    return df
