"""
PCAP Analyzer API Routes
=========================

Standalone endpoints for PCAP file upload, listing, deletion, and analysis.
Not tied to the project system — files are stored per-user under a pcap/ directory.

Each user's pcap/ directory also has a ``_meta.json`` sidecar file that stores
per-file metadata: auto-detected protocol, user-specified tags, etc.
"""

import json
import os
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from werkzeug.utils import secure_filename

from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY

logger = logging.getLogger(__name__)

pcap_bp = Blueprint("pcap", __name__)

ALLOWED_EXTENSIONS = {".pcap", ".pcapng"}
COMPRESSED_EXTENSIONS = {".zip", ".gz"}
UPLOAD_EXTENSIONS = ALLOWED_EXTENSIONS | COMPRESSED_EXTENSIONS
MAX_PCAP_SIZE = 500 * 1024 * 1024  # 500 MB per file
META_FILENAME = "_meta.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pcap_dir(user_id: int) -> Path:
    """Get the PCAP storage directory for a user."""
    return Path(UPLOAD_DIRECTORY) / str(user_id) / "pcap"


def _meta_path(user_id: int) -> Path:
    return _pcap_dir(user_id) / META_FILENAME


def _load_meta(user_id: int) -> dict:
    """Load the per-user metadata sidecar (filename -> {protocol, tags})."""
    mp = _meta_path(user_id)
    if mp.exists():
        try:
            return json.loads(mp.read_text())
        except Exception:
            pass
    return {}


def _save_meta(user_id: int, meta: dict):
    mp = _meta_path(user_id)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(meta, indent=2))


def _file_meta(filepath: Path, meta: dict) -> dict:
    """Build enriched metadata dict for a PCAP file."""
    stat = filepath.stat()
    file_info = meta.get(filepath.name, {})
    return {
        "filename": filepath.name,
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "uploaded_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "protocol": file_info.get("protocol", "unknown"),
        "tags": file_info.get("tags", []),
    }


def _run_detection_async(user_id: int, filename: str, filepath: str):
    """Run protocol detection in a background thread and update meta."""
    def _detect():
        try:
            from api.pcap_analyzer import detect_protocol
            protocol = detect_protocol(filepath)
            meta = _load_meta(user_id)
            if filename not in meta:
                meta[filename] = {}
            meta[filename]["protocol"] = protocol
            _save_meta(user_id, meta)
            logger.info("Auto-detected protocol for %s: %s", filename, protocol)
        except Exception as exc:
            logger.warning("Protocol detection failed for %s: %s", filename, exc)

    thread = threading.Thread(target=_detect, daemon=True)
    thread.start()


def _extract_zip(zip_path: Path, target_dir: Path) -> list[Path]:
    """Extract .pcap/.pcapng files from a ZIP, filtering macOS metadata."""
    import zipfile

    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        pcap_names = [
            n for n in zf.namelist()
            if os.path.splitext(n)[1].lower() in ALLOWED_EXTENSIONS
            and not n.startswith("__MACOSX")
            and not os.path.basename(n).startswith(".")
        ]
        for name in pcap_names:
            basename = secure_filename(os.path.basename(name))
            if not basename:
                continue
            dest = target_dir / basename
            counter = 1
            stem, ext = os.path.splitext(basename)
            while dest.exists():
                dest = target_dir / f"{stem}_{counter}{ext}"
                counter += 1
            with zf.open(name) as src, open(dest, "wb") as dst:
                dst.write(src.read())
            extracted.append(dest)
    return extracted


def _extract_gz(gz_path: Path, target_dir: Path) -> Path | None:
    """Extract a gzip-compressed PCAP file."""
    import gzip

    stem = gz_path.stem  # e.g. "capture.pcap" from "capture.pcap.gz"
    if os.path.splitext(stem)[1].lower() not in ALLOWED_EXTENSIONS:
        stem = stem + ".pcap"
    basename = secure_filename(stem)
    if not basename:
        return None
    dest = target_dir / basename
    counter = 1
    name_stem, ext = os.path.splitext(basename)
    while dest.exists():
        dest = target_dir / f"{name_stem}_{counter}{ext}"
        counter += 1
    try:
        with gzip.open(gz_path, "rb") as src, open(dest, "wb") as dst:
            dst.write(src.read())
        return dest
    except Exception as exc:
        logger.warning("Failed to extract gzip %s: %s", gz_path.name, exc)
        if dest.exists():
            dest.unlink()
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pcap_bp.route("/upload", methods=["POST"])
@jwt_required()
def upload_pcap():
    """Upload one or more PCAP files. Auto-detects protocol in background."""
    user_id = get_user_id()

    if "files" not in request.files:
        return jsonify({"error": "No files provided"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided"}), 400

    pcap_dir = _pcap_dir(user_id)
    pcap_dir.mkdir(parents=True, exist_ok=True)

    meta = _load_meta(user_id)
    uploaded = []
    errors = []

    for f in files:
        if not f.filename:
            continue

        name = secure_filename(f.filename)
        ext = os.path.splitext(name)[1].lower()

        if ext not in UPLOAD_EXTENSIONS:
            errors.append(f"{f.filename}: unsupported format (only .pcap/.pcapng/.zip/.gz)")
            continue

        dest = pcap_dir / name

        # Deduplicate: add numeric suffix if file exists
        counter = 1
        stem = dest.stem
        while dest.exists():
            dest = pcap_dir / f"{stem}_{counter}{ext}"
            counter += 1

        f.save(str(dest))

        if dest.stat().st_size > MAX_PCAP_SIZE:
            dest.unlink()
            errors.append(f"{f.filename}: exceeds {MAX_PCAP_SIZE // (1024*1024)} MB limit")
            continue

        # Extract PCAP from compressed archives
        extracted_files = []
        if ext == ".zip":
            extracted_files = _extract_zip(dest, pcap_dir)
            dest.unlink()
            if not extracted_files:
                errors.append(f"{f.filename}: no .pcap/.pcapng files found in ZIP")
                continue
        elif ext == ".gz":
            extracted = _extract_gz(dest, pcap_dir)
            dest.unlink()
            if not extracted:
                errors.append(f"{f.filename}: could not extract .pcap/.pcapng from gzip")
                continue
            extracted_files = [extracted]

        pcap_files = extracted_files if extracted_files else [dest]
        for pcap_path in pcap_files:
            if pcap_path.stat().st_size > MAX_PCAP_SIZE:
                pcap_path.unlink()
                errors.append(f"{pcap_path.name}: exceeds {MAX_PCAP_SIZE // (1024*1024)} MB limit")
                continue

            meta[pcap_path.name] = {"protocol": "detecting...", "tags": []}
            _save_meta(user_id, meta)
            uploaded.append(_file_meta(pcap_path, meta))
            logger.info("PCAP uploaded: %s for user %s", pcap_path.name, user_id)
            _run_detection_async(user_id, pcap_path.name, str(pcap_path))

    return jsonify({
        "uploaded": uploaded,
        "errors": errors,
    }), 201 if uploaded else 400


@pcap_bp.route("/files", methods=["GET"])
@jwt_required()
def list_pcap_files():
    """List all PCAP files for the current user, enriched with protocol and tags."""
    user_id = get_user_id()
    pcap_dir = _pcap_dir(user_id)

    if not pcap_dir.exists():
        return jsonify({"files": []})

    meta = _load_meta(user_id)

    files = []
    for fp in sorted(pcap_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if fp.suffix.lower() in ALLOWED_EXTENSIONS:
            files.append(_file_meta(fp, meta))

    return jsonify({"files": files})


@pcap_bp.route("/files/<filename>", methods=["DELETE"])
@jwt_required()
def delete_pcap_file(filename: str):
    """Delete a specific PCAP file, its metadata, and cache files."""
    user_id = get_user_id()
    safe_name = secure_filename(filename)
    filepath = _pcap_dir(user_id) / safe_name

    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    filepath.unlink()

    # Clean up cache files
    for suffix in [".ml_cache.csv", ".analysis_cache.csv"]:
        cache_path = _pcap_dir(user_id) / f"{safe_name}{suffix}"
        if cache_path.exists():
            try:
                cache_path.unlink()
                logger.info("Removed cache %s", cache_path.name)
            except OSError as exc:
                logger.warning("Failed to remove cache %s: %s", cache_path.name, exc)

    # Clean up metadata
    meta = _load_meta(user_id)
    meta.pop(safe_name, None)
    _save_meta(user_id, meta)

    logger.info("PCAP deleted: %s for user %s", safe_name, user_id)
    return jsonify({"deleted": safe_name})


@pcap_bp.route("/files/<filename>/tags", methods=["PUT"])
@jwt_required()
def update_tags(filename: str):
    """Set tags for a PCAP file. Body: { "tags": ["tag1", "tag2"] }"""
    user_id = get_user_id()
    safe_name = secure_filename(filename)
    filepath = _pcap_dir(user_id) / safe_name

    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    data = request.get_json(silent=True) or {}
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        return jsonify({"error": "tags must be a list of strings"}), 400

    # Sanitize: strip whitespace, remove empties, deduplicate, limit length
    clean_tags = list(dict.fromkeys(t.strip() for t in tags if isinstance(t, str) and t.strip()))[:20]

    meta = _load_meta(user_id)
    if safe_name not in meta:
        meta[safe_name] = {}
    meta[safe_name]["tags"] = clean_tags
    _save_meta(user_id, meta)

    return jsonify({"filename": safe_name, "tags": clean_tags})


@pcap_bp.route("/files/<filename>/detect", methods=["POST"])
@jwt_required()
def redetect_protocol(filename: str):
    """Re-run protocol auto-detection for a file (synchronous)."""
    user_id = get_user_id()
    safe_name = secure_filename(filename)
    filepath = _pcap_dir(user_id) / safe_name

    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    try:
        from api.pcap_analyzer import detect_protocol
        protocol = detect_protocol(str(filepath))

        meta = _load_meta(user_id)
        if safe_name not in meta:
            meta[safe_name] = {}
        meta[safe_name]["protocol"] = protocol
        _save_meta(user_id, meta)

        return jsonify({"filename": safe_name, "protocol": protocol})
    except Exception as exc:
        logger.exception("Protocol re-detection failed for %s", safe_name)
        return jsonify({"error": str(exc)}), 500


@pcap_bp.route("/analyze", methods=["POST"])
@jwt_required()
def analyze_fast():
    """Run full fast analysis (overview, client list, AP list) on a PCAP file."""
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}
    filename = data.get("filename")

    if not filename:
        return jsonify({"error": "filename is required"}), 400

    safe_name = secure_filename(filename)
    filepath = _pcap_dir(user_id) / safe_name

    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    try:
        from api.pcap_analyzer import PcapFastAnalyzer
        analyzer = PcapFastAnalyzer(str(filepath))
        analyzer.ensure_exported(force=bool(data.get("force", False)))
        overview = analyzer.get_overview()
        clients = analyzer.get_client_list()
        aps = analyzer.get_ap_list()
        mesh = analyzer.get_1905_overview()
        return jsonify({
            "overview": overview,
            "clients": clients,
            "aps": aps,
            "mesh_1905": mesh,
        })
    except Exception as exc:
        logger.exception("Fast analysis failed for %s", safe_name)
        return jsonify({"error": str(exc)}), 500


@pcap_bp.route("/analyze/client/<path:mac>", methods=["GET"])
@jwt_required()
def analyze_client_detail(mac: str):
    """Get detailed analysis for a specific client MAC."""
    user_id = get_user_id()
    filename = request.args.get("filename")

    if not filename:
        return jsonify({"error": "filename query param is required"}), 400

    safe_name = secure_filename(filename)
    filepath = _pcap_dir(user_id) / safe_name

    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    try:
        from api.pcap_analyzer import PcapFastAnalyzer
        analyzer = PcapFastAnalyzer(str(filepath))
        result = analyzer.get_client_detail(mac)
        return jsonify(result)
    except Exception as exc:
        logger.exception("Client detail analysis failed for %s", mac)
        return jsonify({"error": str(exc)}), 500


@pcap_bp.route("/analyze/ap/<path:bssid>", methods=["GET"])
@jwt_required()
def analyze_ap_detail(bssid: str):
    """Get detailed analysis for a specific AP BSSID."""
    user_id = get_user_id()
    filename = request.args.get("filename")

    if not filename:
        return jsonify({"error": "filename query param is required"}), 400

    safe_name = secure_filename(filename)
    filepath = _pcap_dir(user_id) / safe_name

    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    try:
        from api.pcap_analyzer import PcapFastAnalyzer
        analyzer = PcapFastAnalyzer(str(filepath))
        result = analyzer.get_ap_detail(bssid)
        return jsonify(result)
    except Exception as exc:
        logger.exception("AP detail analysis failed for %s", bssid)
        return jsonify({"error": str(exc)}), 500


@pcap_bp.route("/analyze/1905", methods=["GET"])
@jwt_required()
def analyze_1905():
    """Get IEEE 1905.1 analysis. Optional query params: al_mac, src, dst, exclude_periodic."""
    user_id = get_user_id()
    filename = request.args.get("filename")

    if not filename:
        return jsonify({"error": "filename query param is required"}), 400

    safe_name = secure_filename(filename)
    filepath = _pcap_dir(user_id) / safe_name

    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    al_mac = request.args.get("al_mac")
    src = request.args.get("src")
    dst = request.args.get("dst")
    exclude_periodic = request.args.get("exclude_periodic", "").lower() in ("1", "true", "yes")

    has_filter = bool(al_mac or src or dst or exclude_periodic)

    try:
        from api.pcap_analyzer import PcapFastAnalyzer
        analyzer = PcapFastAnalyzer(str(filepath))

        if has_filter:
            result = analyzer.get_1905_conversation(
                al_mac=al_mac or None,
                src_mac=src or None,
                dst_mac=dst or None,
                exclude_periodic=exclude_periodic,
            )
        else:
            result = analyzer.get_1905_overview()

        return jsonify(result)
    except Exception as exc:
        logger.exception("1905.1 analysis failed for %s", safe_name)
        return jsonify({"error": str(exc)}), 500
