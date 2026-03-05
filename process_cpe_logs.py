#!/usr/bin/env python3
"""
Process CPE Logs: Deduplicate, remove empty folders, and zip .tgz archives.

- Computes MD5 checksums of all .tgz files within each subdirectory.
- Removes duplicate .tgz files (same MD5), keeping the first occurrence.
- Removes subdirectories that contain no .tgz files.
- Creates one .zip per remaining subdirectory (containing its unique .tgz files).
- Original (non-duplicate) .tgz files are kept intact.

Usage:
    python process_cpe_logs.py              # Execute for real
    python process_cpe_logs.py --dry-run    # Preview actions without making changes
"""

import argparse
import glob
import hashlib
import os
import shutil
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def md5sum(filepath: str) -> str:
    """Compute the MD5 hash of a file."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def deduplicate_tgz(tgz_files: list[str], folder_name: str, dry_run: bool) -> tuple[list[str], int]:
    """
    Find duplicates by MD5 and remove them.
    Returns (list of unique files to keep, count of duplicates removed).
    """
    seen: dict[str, str] = {}  # md5 -> first filepath
    unique = []
    duplicates = []

    for tgz in tgz_files:
        checksum = md5sum(tgz)
        if checksum in seen:
            duplicates.append((tgz, seen[checksum]))
        else:
            seen[checksum] = tgz
            unique.append(tgz)

    for dup_path, original_path in duplicates:
        dup_name = os.path.basename(dup_path)
        orig_name = os.path.basename(original_path)
        if dry_run:
            print(
                f"  [DRY-RUN] Would remove duplicate: {dup_name} "
                f"(same MD5 as {orig_name})"
            )
        else:
            os.remove(dup_path)
            print(
                f"  Removed duplicate: {dup_name} "
                f"(same MD5 as {orig_name})"
            )

    return unique, len(duplicates)


def process(dry_run: bool = False) -> None:
    removed_folders = []
    created_zips = []
    total_duplicates = 0

    # Collect all immediate subdirectories (sorted for consistent ordering)
    entries = sorted(os.listdir(BASE_DIR))
    subdirs = [
        os.path.join(BASE_DIR, entry)
        for entry in entries
        if os.path.isdir(os.path.join(BASE_DIR, entry))
    ]

    for folder in subdirs:
        folder_name = os.path.basename(folder)
        tgz_files = sorted(glob.glob(os.path.join(folder, "*.tgz")))

        if not tgz_files:
            # ---------- Remove folder with no .tgz files ----------
            if dry_run:
                print(f"[DRY-RUN] Would remove folder: {folder_name}/")
            else:
                shutil.rmtree(folder)
                print(f"Removed folder: {folder_name}/")
            removed_folders.append(folder_name)
        else:
            # ---------- Deduplicate .tgz files by MD5 ----------
            print(f"Processing {folder_name}/ ({len(tgz_files)} .tgz files)...")
            unique_files, dup_count = deduplicate_tgz(tgz_files, folder_name, dry_run)
            total_duplicates += dup_count

            # ---------- Zip unique .tgz files in the folder ----------
            zip_filename = folder_name + ".zip"
            zip_path = os.path.join(BASE_DIR, zip_filename)

            if dry_run:
                print(
                    f"  [DRY-RUN] Would create {zip_filename} "
                    f"with {len(unique_files)} unique .tgz file(s) "
                    f"({dup_count} duplicate(s) removed)"
                )
            else:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                    for tgz in unique_files:
                        zf.write(tgz, arcname=os.path.basename(tgz))
                print(
                    f"  Created {zip_filename} "
                    f"with {len(unique_files)} unique .tgz file(s) "
                    f"({dup_count} duplicate(s) removed)"
                )
            created_zips.append(zip_filename)

    # ---------- Summary ----------
    print("\n--- Summary ---")
    print(f"Folders removed   : {len(removed_folders)}")
    print(f"Duplicates removed: {total_duplicates}")
    print(f"Zip files created : {len(created_zips)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Remove empty CPE log folders and zip .tgz archives."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without making any changes.",
    )
    args = parser.parse_args()

    process(dry_run=args.dry_run)
