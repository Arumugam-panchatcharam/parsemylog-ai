"""Extract log identifiers from arbitrary crash-portal JSON trees."""

from __future__ import annotations

from typing import Any, Iterable

_LOG_ID_KEYS = frozenset({"cpeLogFileId", "id", "logId", "logFileId", "fileId"})
_ARRAY_ID_KEYS = frozenset({"cpeLogFileIds", "logFileIds", "logIds"})


def extract_log_ids_from_json(node: Any) -> list[str]:
    found: list[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            for k, v in n.items():
                if k in _ARRAY_ID_KEYS and isinstance(v, list):
                    for item in v:
                        if isinstance(item, bool):
                            continue
                        if isinstance(item, (str, int, float)):
                            text = str(item).strip()
                            if text:
                                found.append(text)
                        elif isinstance(item, dict) and item.get("id") not in (None, ""):
                            found.append(str(item["id"]))
                if k in _LOG_ID_KEYS and v not in (None, "", False):
                    found.append(str(v))
                walk(v)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    walk(node)
    seen: set[str] = set()
    out: list[str] = []
    for i in found:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def chunk_list(items: list[str], size: int) -> Iterable[list[str]]:
    if size <= 0:
        size = 100
    for i in range(0, len(items), size):
        yield items[i : i + size]


PAGE_SIZE_DEFAULT = 100


def clamp_page_size() -> int:
    return max(10, min(500, int(PAGE_SIZE_DEFAULT)))
