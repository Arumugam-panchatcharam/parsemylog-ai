from enum import Enum
import os
from typing import Iterable

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))

UPLOAD_DIRECTORY = os.path.join(BASE_DIR, "user_uploads")
PARSER_CONFIG_PATH = os.path.join(UPLOAD_DIRECTORY, "rule_parser_config.json")
PARSER_CONFIG_MAX_MATCHES = 100  # Stop counting after this (flood detection threshold)

MERGED_LOGS_DIR_NAME = "merged_logs"
MERGED_LOGS_ARCHIVE_NAME = "mergedlogs"
TELEMETRY_PROFILES_DIR_NAME = "telemetry"

NON_TEXT_EXTENSIONS = ['.xls', '.xlsx', '.tgz', '.zip']
IGNORE_FILENAME_LIST = ['telemetry2', 'snapshot', 'SelfHeal']

# Prune when walking uploads/archives (OS / NAS / archive metadata).
SKIP_WALK_DIRECTORY_NAMES = frozenset({
    "__MACOSX",
    ".Trash",
    "Network Trash Folder",
    "Temporary Items",
    "@eaDir",  # Synology
    "System Volume Information",  # Windows
    "$RECYCLE.BIN",
    "RECYCLER",
})

SKIP_OS_JUNK_FILENAMES = frozenset({
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
})


def is_os_junk_dirname(name: str) -> bool:
    """True if this directory segment should be skipped in walks."""
    return name in SKIP_WALK_DIRECTORY_NAMES


def is_os_junk_filename(name: str) -> bool:
    """True if this file is OS/tool metadata (resource forks, thumbnails, etc.)."""
    if name in SKIP_OS_JUNK_FILENAMES:
        return True
    if name.startswith("._"):
        return True
    return False


def path_contains_skipped_dir(parts: Iterable[str]) -> bool:
    """True if any path component is under SKIP_WALK_DIRECTORY_NAMES."""
    return any(p in SKIP_WALK_DIRECTORY_NAMES for p in parts)

# Log viewer constants
LINES_PER_PAGE = 1000

# Sentence Transformer (BGE model for semantic search)
SENTENCE_TRANSFORMER_MODE_NAME = "bge-small-en-v1.5-local"

# Qdrant configuration
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")