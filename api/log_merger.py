import os
import shutil
import tarfile
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

class LogMerger:
    def __init__(self, directory, merged_logs_path):
        self.directory = directory
        self.temp_dir = os.path.join(directory, "temp")
        self.merged_logs_path = merged_logs_path
        os.makedirs(self.merged_logs_path, exist_ok=True)

        # Group 1 : timestamp
        # Group 2 : log name
        # Group 3 : optional rollover index
        self.FILE_NAME_REGEX = re.compile(
            r"^(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})_(.+?)(?:\.(\d+))?$"
            )

    def _parse_timestamp(self, ts):
        return datetime.strptime(ts, "%Y-%m-%d-%H-%M-%S")
    
    def _cleanup(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @staticmethod
    def _tar_open_mode(filename: str):
        """Return (is_tar, mode) for the given filename."""
        if filename.endswith(".tgz") or filename.endswith(".tar.gz"):
            return True, "r:gz"
        if filename.endswith(".tar.bz2"):
            return True, "r:bz2"
        if filename.endswith(".tar"):
            return True, "r:"
        return False, None

    def _extract_logs(self):
        os.makedirs(self.temp_dir, exist_ok=True)
        for file in Path(self.directory).iterdir():
            if file.is_dir() or file.name.startswith("."):
                print(f"Skipping directory: {file}")
                continue

            filename = file.name
            is_tar, mode = self._tar_open_mode(filename)
            if is_tar:
                src_file = file
                # Strip all tar-related suffixes for the dest folder name
                base = filename
                for suffix in (".tar.gz", ".tar.bz2", ".tgz", ".tar"):
                    if base.endswith(suffix):
                        base = base[: -len(suffix)]
                        break
                dest = os.path.join(self.temp_dir, base)
                os.makedirs(dest, exist_ok=True)
                try:
                    with tarfile.open(src_file, mode) as tar:
                        tar.extractall(path=dest, filter="data")
                except Exception as e:
                    print(f"Error extracting {src_file}: {e}")
            else:
                # If the file has a timestamp prefix (e.g. 2026-02-06-06-51-36_WiFilog.txt),
                # move it to temp_dir so _merge_log_files() can strip the prefix and merge.
                # Otherwise move directly to merged output.
                if self.FILE_NAME_REGEX.match(filename):
                    shutil.move(str(file), os.path.join(self.temp_dir, filename))
                else:
                    shutil.move(str(file), self.merged_logs_path)

    def _merge_log_files(self):
        # Collect log files
        logs = defaultdict(list)
        for root, _, files in os.walk(self.temp_dir):
            for fname in files:
                match = self.FILE_NAME_REGEX.match(fname)
                if not match:
                    continue

                ts_str, log_name, index = match.groups()
                logs[log_name].append({
                    "timestamp": self._parse_timestamp(ts_str),
                    "index": int(index) if index else -1,
                    "path": Path(root) / fname
                })

        # Merge logs
        #print(logs)
        for log_name, entries in logs.items():
            # timestamp asc, rollover desc (.1 → .0 → none)
            entries.sort(key=lambda e: (e["timestamp"], -e["index"]))
            out_path = Path(self.merged_logs_path) / log_name

            with open(out_path, "wb") as out:
                for entry in entries:
                    try:
                        with open(entry["path"], "rb") as f:
                            shutil.copyfileobj(f, out)
                            # TODO: do we need marker between merged files?
                    except Exception as e:
                        print(f"[WARN] Failed reading {entry['path']}: {e}")

        print(f"Merged logs are available at: {self.merged_logs_path}")

    def merge_logs(self):
        # Step 1: Extract tarballs to temp directory
        self._extract_logs()
        # Step 2 & 3: Collect and merge log files
        self._merge_log_files()
        # Cleanup temp directory
        self._cleanup()

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge log files from tar.gz archives into chronological logs."
    )

    parser.add_argument(
        "directory",
        help="Directory containing tar.gz log archives",
    )

    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Directory to write merged logs (default: <directory>/merged_logs)",
    )

    args = parser.parse_args()

    directory = os.path.abspath(args.directory)
    output = (
        os.path.abspath(args.output)
        if args.output
        else os.path.join(directory, "merged_logs")
    )

    if not os.path.isdir(directory):
        print(f"Error: directory not found: {directory}", file=sys.stderr)
        sys.exit(1)

    merger = LogMerger(directory, output)
    merger.merge_logs()

if __name__ == "__main__":
    import argparse
    import sys
    main()
