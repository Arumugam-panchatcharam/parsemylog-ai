#!/usr/bin/env python3
"""
Process CPE Logs: Deduplicate, remove empty folders, and zip .tgz archives.

- Computes MD5 checksums of all .tgz / .tar.gz files within each subdirectory.
- Removes duplicate .tgz files (same MD5), keeping the first occurrence.
- Removes subdirectories that contain no .tgz files.
- Creates one .zip per remaining subdirectory (containing its unique .tgz files).
- If there are no subdirectories but *.tgz / *.tar.gz files sit directly under the
  target dir (flat upload), normally creates one .zip per archive file.

- **Auto single-CPE:** if there are 2+ archives and every basename matches the same
  CPE log prefix (e.g. ``vendor_MAC`` before ``_YYYY-MM-DD-HH-MM-SS_``, or before
  ``_CPELogs_``), all are merged into **one** ``archive/<project-name>.zip``.

Usage:
    python process_cpe_logs.py              # Execute for real
    python process_cpe_logs.py --dry-run    # Preview actions without making changes
"""

import argparse
import glob
import hashlib
import os
import re
import shutil
import zipfile

# CPE log bundle names, e.g. telekom-cz_DC08DAE34B1F_2026-03-19-18-16-13_CPELogs_...tgz
_RE_CPE_TS_PREFIX = re.compile(
    r"^(.+?)_\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}_",
    re.IGNORECASE,
)
_RE_CPE_DATE_PREFIX = re.compile(
    r"^(.+?)_\d{4}-\d{2}-\d{2}_",
    re.IGNORECASE,
)
_RE_CPELOGS_PREFIX = re.compile(r"^(.+?)_CPELogs_", re.IGNORECASE)
# vendor + 12 hex (MAC) at word boundary before next segment
_RE_VENDOR_MAC_PREFIX = re.compile(r"^(.+?_[0-9a-f]{12})_", re.IGNORECASE)


def _archive_stem_filename(basename: str) -> str:
    lower = basename.lower()
    if lower.endswith(".tar.gz"):
        return basename[:-7]
    if lower.endswith(".tgz"):
        return basename[:-4]
    return os.path.splitext(basename)[0]


def cpe_log_identity_from_basename(basename: str) -> str | None:
    """
    Stable device/session prefix for CPE log archive names.
    Returns None if the name does not look like a known CPE log bundle pattern.
    """
    stem = _archive_stem_filename(basename)
    m = _RE_CPE_TS_PREFIX.match(stem)
    if m:
        return m.group(1).strip().lower()
    m = _RE_CPELOGS_PREFIX.match(stem)
    if m:
        inner = m.group(1).strip()
        m2 = _RE_CPE_DATE_PREFIX.match(inner)
        if m2:
            return m2.group(1).strip().lower()
        return inner.lower()
    m = _RE_CPE_DATE_PREFIX.match(stem)
    if m:
        return m.group(1).strip().lower()
    m = _RE_VENDOR_MAC_PREFIX.match(stem)
    if m:
        return m.group(1).strip().lower()
    return None


def _all_tgz_candidates(target_dir: str, subdirs: list[str]) -> list[str]:
    out: list[str] = []
    if not subdirs:
        out.extend(collect_tgz_files_in_dir(target_dir))
    else:
        for folder in subdirs:
            out.extend(collect_tgz_files_in_dir(folder))
    return out


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


def collect_tgz_files_in_dir(folder: str) -> list[str]:
    """Return sorted unique paths for .tgz and .tar.gz directly under folder."""
    patterns = ("*.tgz", "*.tar.gz", "*.TGZ", "*.TAR.GZ")
    seen: set[str] = set()
    out: list[str] = []
    for pattern in patterns:
        for path in sorted(glob.glob(os.path.join(folder, pattern))):
            if path not in seen:
                seen.add(path)
                out.append(path)
    return out


def cpe_stem_from_archive(path: str) -> str:
    """Base name for the output .zip (without extension)."""
    base = os.path.basename(path)
    lower = base.lower()
    if lower.endswith(".tar.gz"):
        return base[:-7]
    if lower.endswith(".tgz"):
        return base[:-4]
    return os.path.splitext(base)[0]


def _safe_bundle_stem(project_name: str | None) -> str:
    """Filesystem-safe stem for the single-CPE bundle zip."""
    raw = (project_name or "single_cpe").strip() or "single_cpe"
    stem = os.path.splitext(os.path.basename(raw))[0] or "single_cpe"
    cleaned = "".join(c if (c.isalnum() or c in "._-") else "_" for c in stem)
    return (cleaned[:180] or "single_cpe")


def _single_cpe_bundle(
    target_dir: str,
    archive_dir: str,
    subdirs: list[str],
    project_name: str | None,
    dry_run: bool,
) -> tuple[list[str], list[str], int]:
    """Merge all tarballs into one archive zip; drop empty subfolders."""
    removed_folders: list[str] = []
    created_zips: list[str] = []
    total_duplicates = 0
    target_abs = os.path.abspath(target_dir)

    candidates: list[str] = []
    if not subdirs:
        candidates.extend(collect_tgz_files_in_dir(target_dir))
    else:
        for folder in subdirs:
            folder_name = os.path.basename(folder)
            tgz_in = collect_tgz_files_in_dir(folder)
            if not tgz_in:
                if dry_run:
                    print(f"[DRY-RUN] Would remove folder (no archives): {folder_name}/")
                else:
                    shutil.rmtree(folder)
                    print(f"Removed folder (no archives): {folder_name}/")
                removed_folders.append(folder_name)
            else:
                candidates.extend(tgz_in)

    if not candidates:
        print("Single-CPE mode: no .tgz / .tar.gz files found under upload root or subfolders")
        return created_zips, removed_folders, total_duplicates

    print(f"Single-CPE mode: bundling {len(candidates)} archive file(s) into one job zip...")
    unique_files, dup_count = deduplicate_tgz(candidates, "single_cpe", dry_run)
    total_duplicates = dup_count

    zip_filename = f"{_safe_bundle_stem(project_name)}.zip"
    zip_path = os.path.join(archive_dir, zip_filename)

    if dry_run:
        print(
            f"  [DRY-RUN] Would create {zip_filename} "
            f"with {len(unique_files)} archive file(s)"
        )
    else:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for tgz in unique_files:
                rel = os.path.relpath(os.path.abspath(tgz), target_abs)
                if rel.startswith(".."):
                    rel = os.path.basename(tgz)
                zf.write(tgz, arcname=rel.replace("\\", "/"))
        print(f"  Created {zip_filename} with {len(unique_files)} archive file(s)")
    created_zips.append(zip_filename)

    return created_zips, removed_folders, total_duplicates


def process(
    target_dir: str,
    project_name: str = None,
    dry_run: bool = False,
) -> None:
    removed_folders = []
    created_zips = []
    total_duplicates = 0

    # Create archive directory for output zip files
    archive_dir = os.path.join(target_dir, "archive")
    if not dry_run and not os.path.exists(archive_dir):
        os.makedirs(archive_dir)
        print(f"Created archive directory: {archive_dir}")

    # Collect all immediate subdirectories (sorted for consistent ordering)
    entries = sorted(os.listdir(target_dir))
    subdirs = [
        os.path.join(target_dir, entry)
        for entry in entries
        if os.path.isdir(os.path.join(target_dir, entry)) and entry != "archive"
    ]

    cand = _all_tgz_candidates(target_dir, subdirs)
    ids = [cpe_log_identity_from_basename(os.path.basename(p)) for p in cand]
    merge_one_cpe = (
        len(cand) >= 2
        and all(i is not None for i in ids)
        and len(set(ids)) == 1
    )
    if merge_one_cpe:
        print(f"Auto single-CPE: merging {len(cand)} archives (shared identity {ids[0]!r})")
        cz, rf, td = _single_cpe_bundle(target_dir, archive_dir, subdirs, project_name, dry_run)
        created_zips.extend(cz)
        removed_folders.extend(rf)
        total_duplicates += td
    elif not subdirs:
        root_archives = collect_tgz_files_in_dir(target_dir)
        for tgz_path in root_archives:
            folder_name = cpe_stem_from_archive(tgz_path)
            print(f"Processing flat layout {folder_name} (1 archive at upload root)...")
            unique_files, dup_count = deduplicate_tgz([tgz_path], folder_name, dry_run)
            total_duplicates += dup_count
            zip_filename = folder_name + ".zip"
            zip_path = os.path.join(archive_dir, zip_filename)
            if dry_run:
                print(
                    f"  [DRY-RUN] Would create {zip_filename} "
                    f"with {len(unique_files)} unique archive file(s)"
                )
            else:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                    for tgz in unique_files:
                        zf.write(tgz, arcname=os.path.basename(tgz))
                print(
                    f"  Created {zip_filename} "
                    f"with {len(unique_files)} archive file(s)"
                )
            created_zips.append(zip_filename)

    if not merge_one_cpe:
        for folder in subdirs:
            folder_name = os.path.basename(folder)
            tgz_files = collect_tgz_files_in_dir(folder)

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
                zip_path = os.path.join(archive_dir, zip_filename)

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

    # ---------- Create Final Project Archive ----------
    if created_zips and not dry_run:
        final_archive_name = project_name or "batch_project"
        final_archive_path = os.path.join(target_dir, f"{final_archive_name}.zip")
        
        print(f"\nCreating final project archive: {final_archive_name}.zip")
        
        with zipfile.ZipFile(final_archive_path, "w", zipfile.ZIP_DEFLATED) as final_zip:
            # Add all files from the archive directory
            for root, dirs, files in os.walk(archive_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    archive_name = os.path.relpath(file_path, target_dir)
                    final_zip.write(file_path, arcname=archive_name)
                    
        print(f"Final archive created: {final_archive_path}")

    # ---------- Summary ----------
    print("\n--- Summary ---")
    print(f"Folders removed   : {len(removed_folders)}")
    print(f"Duplicates removed: {total_duplicates}")
    print(f"Zip files created : {len(created_zips)}")
    if created_zips and not dry_run:
        print(f"Archive directory : archive/ ({len(created_zips)} zip files)")
        print(f"Final archive     : {project_name or 'batch_project'}.zip")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Remove empty CPE log folders and zip .tgz archives."
    )
    parser.add_argument(
        "--target-dir",
        default=os.path.dirname(os.path.abspath(__file__)),
        help="Directory containing CPE log folders to process (default: script directory).",
    )
    parser.add_argument(
        "--project-name",
        default="batch_project",
        help="Name for the final project archive (default: batch_project).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without making any changes.",
    )
    args = parser.parse_args()

    process(
        target_dir=args.target_dir,
        project_name=args.project_name,
        dry_run=args.dry_run,
    )
