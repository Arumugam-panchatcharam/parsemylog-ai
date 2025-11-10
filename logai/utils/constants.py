from enum import Enum
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))

UPLOAD_DIRECTORY = os.path.join(BASE_DIR, "user_uploads")
PARSER_CONFIG_PATH = os.path.join(UPLOAD_DIRECTORY, "rule_parser_config.json")
PARSER_CONFIG_MAX_MATCHES = 100  # Stop counting after this (flood detection threshold)

MERGED_LOGS_DIR_NAME = "merged_logs"
MERGED_LOGS_ARCHIVE_NAME = "mergedlogs"
TELEMETRY_PROFILES_DIR_NAME = "telemetry"

NON_TEXT_EXTENSIONS = ['.xls', '.xlsx', '.tgz', '.zip']
IGNORE_FILENAME_LIST = ['telemetry2', 'snapshot', 'SelfHeal']

# Log viewer constants
LINES_PER_PAGE = 1000

# Sentence Transformer
SENTENCE_TRANSFORMER_MODE_NAME = "all-MiniLM-L6-v2-local"