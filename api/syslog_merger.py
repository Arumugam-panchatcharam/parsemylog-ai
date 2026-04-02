import os
import shutil
import tarfile
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import argparse
import sys

from logai.timestamp_parser import parse_timestamp

class SyslogMerger:
    # Full 6-part timestamp in a tgz filename, e.g. ..._2026-01-27-09-02-03_...
    TGZ_TS_RE = re.compile(r'(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})')

    def __init__(self, temp_dir: str, merged_logs_path: str):
        self.temp_dir = temp_dir
        self.merged_logs_path = merged_logs_path
        
        # Group 1 : timestamp
        # Group 2 : log name  
        # Group 3 : optional rollover index
        self.FILE_NAME_REGEX = re.compile(
            r"^(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})_((?:syslog\.txt|local7notice))(?:\.(\d+))?$"
        )

    def _parse_timestamp(self, ts):
        """Parse timestamp using generic parser with dash-separated fallback."""
        result = parse_timestamp(ts)
        if result:
            return result
        # Fallback to dash-separated format
        return datetime.strptime(ts, "%Y-%m-%d-%H-%M-%S")
        
    def _read_last_lines(self, filepath: Path, num_lines: int = 5) -> list[bytes]:
        """Read the last N lines of a file efficiently."""
        if not filepath.exists() or filepath.stat().st_size == 0:
            return []
            
        with open(filepath, "rb") as f:
            f.seek(0, os.SEEK_END)
            buffer = bytearray()
            pointer_location = f.tell()
            lines = []
            
            while pointer_location >= 0 and len(lines) <= num_lines:
                f.seek(pointer_location)
                pointer_location -= 1
                new_byte = f.read(1)
                if new_byte == b'\n':
                    if buffer:
                        lines.append(buffer[::-1])
                        buffer = bytearray()
                else:
                    buffer.extend(new_byte)
                    
            if buffer:
                lines.append(buffer[::-1])
                
            return lines[::-1][:num_lines]

    def _find_overlap(self, file_path: Path) -> int:
        """
        Efficiently finds overlap using the head signature of the file.
        Returns the byte offset where new content begins, or 0 if no overlap.
        """
        if not hasattr(self, '_known_heads'):
            self._known_heads = {}
            
        if not file_path.exists() or file_path.stat().st_size == 0:
            return 0
            
        file_size = file_path.stat().st_size
        
        # Read the first line as a signature to quickly skip empty files
        with open(file_path, "rb") as f:
            head = f.readline()
            
        # Ignore completely empty files or ones with empty heads
        if not head.strip():
            return 0
            
        # Try to use up to the first 2-3 lines as the signature for better uniqueness,
        # especially for local7notice which might have repeated single-line starts.
        with open(file_path, "rb") as f:
            head_lines = []
            for _ in range(3):
                line = f.readline()
                if not line:
                    break
                head_lines.append(line)
            head = b"".join(head_lines)
            
        if head in self._known_heads:
            known_size = self._known_heads[head]
            if file_size > known_size:
                self._known_heads[head] = file_size
                return known_size
            else:
                return file_size  # Return file_size so we read 0 bytes
        else:
            self._known_heads[head] = file_size
            return 0

    def merge_syslogs(self):
        """
        Smart merge for syslog.txt files (flash-stored) across all extracted tgz contents.
        syslog.txt is stored in flash and appends continuously. When it hits 500KB,
        it rotates to syslog.txt.1 and a new syslog.txt starts.
        Because they are in flash, they survive reboots and need deduplication.
        
        Note: local7notice and other logs are handled by the regular log_merger.py
        """
        # 1. Collect all syslog files
        syslogs = defaultdict(list)
        for root, _, files in os.walk(self.temp_dir):
            for fname in files:
                match = self.FILE_NAME_REGEX.match(fname)
                if match:
                    ts_str, log_name, index = match.groups()
                    
                    # Handle device double-timestamping (e.g. 2026-03-08-00-14-07_2026-03-08-00-00-00_syslog.txt)
                    while re.match(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}_", log_name):
                        log_name = log_name[20:]
                        
                    syslogs[log_name].append({
                        "timestamp": self._parse_timestamp(ts_str),
                        "index": int(index) if index else -1,
                        "path": Path(root) / fname
                    })

        if not syslogs:
            return

        out_path = Path(self.merged_logs_path) / "syslog.txt"
        
        # Process syslog.txt and local7notice separately
        # Group them by base_name so they are merged to their respective files
        syslog_entries = []
        local7_entries = []
        
        for log_name, entries in syslogs.items():
            for e in entries:
                if "syslog.txt" in log_name:
                    e["base_name"] = "syslog.txt"
                    syslog_entries.append(e)
                elif "local7notice" in log_name:
                    e["base_name"] = "local7notice"
                    local7_entries.append(e)
                    
        # Sort by: Timestamp of the tgz upload, then Rollover index
        syslog_entries.sort(key=lambda e: (e["timestamp"], -e["index"]))
        local7_entries.sort(key=lambda e: (e["timestamp"], -e["index"]))
        
        self._merge_syslog_sequence(syslog_entries, Path(self.merged_logs_path) / "syslog.txt")
        self._merge_local7_sequence(local7_entries, Path(self.merged_logs_path) / "local7notice")
        
    def _merge_syslog_sequence(self, entries, out_path: Path):
        if not entries:
            return
            
        self._known_heads = {}
        
        with open(out_path, "wb") as out:
            for entry in entries:
                file_path = entry["path"]
                if file_path.stat().st_size == 0:
                    continue
                    
                # Find overlap with previously written content
                offset = self._find_overlap(file_path)
                
                # If offset == file size, there is no new content
                if offset >= file_path.stat().st_size:
                    continue
                
                # Read new content (skip overlapping part)
                with open(file_path, "rb") as f:
                    f.seek(offset)
                    new_content = f.read()
                    
                if new_content:
                    # Write marker
                    ts_str = entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
                    marker = f"******************** LOG_MERGE_MARKER: {ts_str} ********************\n".encode("utf-8")
                    out.write(marker)
                    out.write(new_content)
                    
        print(f"[SyslogMerger] Merged syslog available at: {out_path}")
        
    def _merge_local7_sequence(self, entries, out_path: Path):
        """
        local7notice acts like a circular buffer dropping logs from the top.
        We cannot use the simple size-based head signature approach.
        Instead, we find where the tail of the previous file overlaps with the new file.
        """
        if not entries:
            return
            
        last_known_lines = []
        
        with open(out_path, "wb") as out:
            for i, entry in enumerate(entries):
                file_path = entry["path"]
                if file_path.stat().st_size == 0:
                    continue
                    
                # Find overlap using tail-to-head matching
                if i == 0:
                    offset = 0
                else:
                    offset = self._find_overlap_circular(last_known_lines, file_path)
                    
                # If offset == file size, there is no new content
                if offset >= file_path.stat().st_size:
                    continue
                
                with open(file_path, "rb") as f:
                    f.seek(offset)
                    new_content = f.read()
                    
                if new_content:
                    ts_str = entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
                    marker = f"******************** LOG_MERGE_MARKER: {ts_str} ********************\n".encode("utf-8")
                    out.write(marker)
                    out.write(new_content)
                    
                    # Update last known lines from what we just wrote
                    # For circular buffers, we need a decent chunk (e.g. last 10 lines) to match against
                    lines = new_content.split(b'\n')
                    # Get lines that are non-empty and not just whitespace
                    valid_lines = [line for line in lines if line.strip()]
                    if valid_lines:
                        # Append to our running buffer of last lines, but keep it bounded to last 20
                        last_known_lines.extend(valid_lines[-20:])
                        last_known_lines = last_known_lines[-20:]
                        
        print(f"[SyslogMerger] Merged local7notice available at: {out_path}")
        
    def _find_overlap_circular(self, last_lines: list[bytes], new_file_path: Path) -> int:
        """
        Finds overlap in circular buffers by matching the tail of previous content 
        somewhere in the new file.
        """
        if not last_lines:
            return 0
            
        with open(new_file_path, "rb") as f:
            content = f.read()
            
        # Try matching larger blocks first, then smaller blocks if needed.
        for num_lines_to_match in range(len(last_lines), 2, -1):
            target_tail = b"\n".join(last_lines[-num_lines_to_match:])
            if not target_tail:
                continue
                
            idx = content.find(target_tail)
            if idx != -1:
                # We found the overlap! The new content starts right after this tail.
                # Find the next newline character to start clean
                end_of_match = idx + len(target_tail)
                next_newline = content.find(b'\n', end_of_match)
                if next_newline != -1:
                    return next_newline + 1
                return end_of_match
                
        # local7notice frequently repeats its tail almost precisely. 
        # A safer strategy for circular buffers where older content gets dropped:
        # Instead of finding the *last* known match which might be somewhere in the middle,
        # we should find where the head of the *new* file appears in our *previous* lines.
        # But wait, local7notice files are uploaded when full. 
        # The new file is generally a superset or overlaps with the tail of the old one.
        
        # Try to find a larger matching block first using exact lines (including timestamps)
        head_content = content[:500000]
        for block_size in range(10, 2, -1):
            if len(last_lines) < block_size:
                continue

            exact_block = b"\n".join(last_lines[-block_size:])
            idx = head_content.find(exact_block)
            if idx != -1:
                next_newline = head_content.find(b'\n', idx + len(exact_block))
                if next_newline != -1:
                    return next_newline + 1
                return idx + len(exact_block)

        # If we didn't find an exact block overlap, we should return 0.
        # local7notice logs from different uploads are often completely disjoint in time,
        # so single-line stripped matching will falsely match generic lines like "firewall operation completed"
        # and cause us to lose data.
        return 0

def merge_syslogs_from_temp(temp_dir: str, merged_logs_path: str):
    merger = SyslogMerger(temp_dir, merged_logs_path)
    merger.merge_syslogs()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smart merge for syslogs")
    parser.add_argument("temp_dir", help="Temp directory containing extracted tgz files")
    parser.add_argument("output", help="Output directory for merged syslog.txt")
    args = parser.parse_args()
    merge_syslogs_from_temp(args.temp_dir, args.output)
