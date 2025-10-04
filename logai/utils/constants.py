from enum import Enum
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))

UPLOAD_DIRECTORY = os.path.join(BASE_DIR, "user_uploads")
MERGED_LOGS_DIR_NAME = "merged_logs"
MERGED_LOGS_ARCHIVE_NAME = "mergedlogs"
TELEMETRY_PROFILES_DIR_NAME = "telemetry"

LINES_PER_PAGE = 1000

