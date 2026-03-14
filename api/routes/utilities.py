"""
Utilities API Blueprint
=======================

General-purpose utility endpoints for tools like MAC OUI lookup.
"""

import logging
import re
import time
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import requests
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

utilities_bp = Blueprint("utilities", __name__)

# Get the base directory (project root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
OUI_FILE_PATH = BASE_DIR / "oui.txt"

# Local OUI database (loaded from oui.txt)
_local_oui_db: Dict[str, str] = {}

# Cache for online OUI lookups
_online_cache: Dict[str, str] = {}


def load_local_oui_database(filepath: Optional[str] = None) -> Dict[str, str]:
    """
    Load the IEEE OUI database from oui.txt file.
    
    The file format is:
        XX-XX-XX   (hex)		Vendor Name
        XXXXXX     (base 16)	Vendor Name
    
    Args:
        filepath: Path to oui.txt file (defaults to BASE_DIR/oui.txt)
        
    Returns:
        Dictionary mapping OUI (XX:XX:XX format) to vendor name
    """
    if filepath is None:
        filepath = str(OUI_FILE_PATH)
    
    oui_db = {}
    
    if not os.path.exists(filepath):
        logger.warning(f"Local OUI database not found at {filepath}. Online-only mode.")
        return oui_db
    
    try:
        logger.info(f"Loading local OUI database from {filepath}")
        current_oui = None
        
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                
                # Match lines like "XX-XX-XX   (hex)		Vendor Name"
                if "(hex)" in line:
                    parts = line.split("(hex)")
                    if len(parts) >= 2:
                        oui_raw = parts[0].strip()
                        vendor = parts[1].strip()
                        
                        # Convert XX-XX-XX to XX:XX:XX
                        oui_normalized = oui_raw.replace("-", ":")
                        
                        if vendor:
                            oui_db[oui_normalized.upper()] = vendor
                            current_oui = oui_normalized.upper()
        
        logger.info(f"Loaded {len(oui_db)} OUI entries from local database")
        return oui_db
        
    except Exception as exc:
        logger.exception(f"Failed to load local OUI database: {exc}")
        return {}


# Load the local database on module import
_local_oui_db = load_local_oui_database()

# Log initial database status
if len(_local_oui_db) == 0 and not os.path.exists(OUI_FILE_PATH):
    logger.warning(
        f"OUI database not found at {OUI_FILE_PATH}. "
        "MAC lookups will use online API only. "
        "Use POST /utilities/oui-update to download the database for faster lookups."
    )
elif len(_local_oui_db) == 0:
    logger.error(
        f"OUI database file exists at {OUI_FILE_PATH} but failed to load. "
        "Check file format or try re-downloading via POST /utilities/oui-update."
    )
else:
    logger.info(f"OUI database loaded successfully: {len(_local_oui_db)} vendors")


def normalize_mac(mac_str: str) -> str:
    """
    Normalize MAC address to standard format XX:XX:XX:XX:XX:XX.
    
    Handles various input formats:
    - Space-separated: "6a e1 95 7a 04 18"
    - Colon-separated: "6a:e1:95:7a:04:18"
    - Hyphen-separated: "6a-e1-95-7a-04-18"
    - No separators: "6ae1957a0418"
    
    Args:
        mac_str: MAC address string in any format
        
    Returns:
        Normalized MAC address in XX:XX:XX:XX:XX:XX format
        
    Raises:
        ValueError: If the MAC address is invalid
    """
    # Remove all separators and whitespace
    clean = re.sub(r'[\s:.\-]', '', mac_str.strip())
    
    # Validate: should be exactly 12 hex characters
    if not re.match(r'^[0-9A-Fa-f]{12}$', clean):
        raise ValueError(f"Invalid MAC address format: {mac_str}")
    
    # Convert to uppercase and insert colons
    clean = clean.upper()
    return ':'.join(clean[i:i+2] for i in range(0, 12, 2))


def is_locally_administered(mac: str) -> bool:
    """
    Check if a MAC address is locally administered (LAA).
    
    The U/L (Universal/Local) bit is the second least significant bit of the 
    first octet. If set to 1, the address is locally administered.
    
    Locally administered addresses are not assigned by manufacturers and 
    therefore have no OUI to lookup.
    
    Args:
        mac: Normalized MAC address (XX:XX:XX:XX:XX:XX)
        
    Returns:
        True if locally administered, False if universally administered
    """
    try:
        # Get the first octet (first two hex digits)
        first_octet_str = mac.split(':')[0]
        first_octet = int(first_octet_str, 16)
        
        # Check if bit 1 (second least significant bit) is set
        # 0x02 = 0b00000010
        is_laa = (first_octet & 0x02) != 0
        
        return is_laa
    except (ValueError, IndexError):
        return False


def get_oui(mac: str) -> str:
    """
    Extract the OUI (Organizationally Unique Identifier) from a MAC address.
    
    The OUI is the first 3 octets (6 hex digits) of the MAC address.
    
    Args:
        mac: Normalized MAC address (XX:XX:XX:XX:XX:XX)
        
    Returns:
        OUI in XX:XX:XX format
    """
    return ':'.join(mac.split(':')[:3])


def lookup_vendor_local(oui: str) -> Optional[str]:
    """
    Look up vendor in the local OUI database.
    
    Args:
        oui: OUI in XX:XX:XX format
        
    Returns:
        Vendor name if found, None otherwise
    """
    return _local_oui_db.get(oui.upper())


def lookup_vendor_online(oui: str) -> str:
    """
    Look up the vendor name for an OUI using the macvendors.com API.
    
    Results are cached to minimize API calls.
    
    Args:
        oui: OUI in XX:XX:XX format
        
    Returns:
        Vendor name or error message
    """
    # Check online cache first
    if oui in _online_cache:
        return _online_cache[oui]
    
    try:
        # Query macvendors.com API
        # Note: Free tier allows 1 request/second, 1000 requests/day
        url = f"https://api.macvendors.com/{oui}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            vendor = response.text.strip()
            _online_cache[oui] = vendor
            return vendor
        elif response.status_code == 404:
            _online_cache[oui] = "Unknown Vendor"
            return "Unknown Vendor"
        elif response.status_code == 429:
            return "Rate limit exceeded"
        else:
            logger.warning(f"OUI lookup failed for {oui}: HTTP {response.status_code}")
            return f"Lookup failed (HTTP {response.status_code})"
            
    except requests.exceptions.Timeout:
        return "Lookup timeout"
    except requests.exceptions.RequestException as exc:
        logger.warning(f"OUI lookup error for {oui}: {exc}")
        return "Network error"
    except Exception as exc:
        logger.exception(f"Unexpected error during OUI lookup for {oui}")
        return f"Error: {str(exc)}"


def lookup_vendor(oui: str) -> str:
    """
    Look up vendor for an OUI.
    
    Strategy:
    1. Check local database first (instant)
    2. If not found, query online API (with rate limiting)
    
    Args:
        oui: OUI in XX:XX:XX format
        
    Returns:
        Vendor name or error message
    """
    # Try local database first
    vendor = lookup_vendor_local(oui)
    if vendor:
        logger.info(f"OUI lookup (local): {oui} -> {vendor}")
        return vendor
    
    # Fallback to online lookup
    logger.info(f"OUI not in local DB, querying online: {oui}")
    vendor = lookup_vendor_online(oui)
    logger.info(f"OUI lookup (online): {oui} -> {vendor}")
    return vendor


@utilities_bp.route("/oui-update", methods=["POST"])
def update_oui_database():
    """
    Download the latest IEEE OUI database from the official source.
    
    This endpoint downloads oui.txt from standards-oui.ieee.org and 
    reloads the in-memory database.
    
    Returns:
        JSON with status, message, and entry count
    """
    global _local_oui_db
    
    try:
        oui_url = "https://standards-oui.ieee.org/oui/oui.txt"
        filepath = str(OUI_FILE_PATH)
        
        logger.info(f"Downloading OUI database from {oui_url} to {filepath}")
        
        # Add headers to make request look legitimate (avoid HTTP 418)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/plain,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # Download with timeout and proper headers
        response = requests.get(oui_url, timeout=60, stream=True, headers=headers, allow_redirects=True)
        
        if response.status_code != 200:
            logger.error(f"OUI download failed: HTTP {response.status_code}")
            return jsonify({
                "status": "error",
                "message": f"Failed to download: HTTP {response.status_code}. The IEEE server may be temporarily unavailable or blocking requests. Please try again later."
            }), 500
        
        # Get total size if available
        total_size = int(response.headers.get('content-length', 0))
        logger.info(f"Downloading {total_size / (1024*1024):.1f} MB...")
        
        # Write to file
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        # Verify file was downloaded
        if not os.path.exists(filepath) or os.path.getsize(filepath) < 1000:
            return jsonify({
                "status": "error",
                "message": "Downloaded file is empty or too small. Please try again."
            }), 500
        
        logger.info(f"OUI database downloaded successfully to {filepath}")
        
        # Reload the database
        _local_oui_db = load_local_oui_database(filepath)
        
        if len(_local_oui_db) == 0:
            return jsonify({
                "status": "error",
                "message": "Downloaded file appears to be invalid (no entries parsed). Please try again."
            }), 500
        
        return jsonify({
            "status": "success",
            "message": f"OUI database updated successfully",
            "entries": len(_local_oui_db),
            "size_mb": round(os.path.getsize(filepath) / (1024 * 1024), 2)
        }), 200
        
    except requests.exceptions.Timeout:
        logger.error("OUI database download timeout")
        return jsonify({
            "status": "error",
            "message": "Download timeout (60 seconds exceeded). The IEEE server may be slow. Please try again."
        }), 500
    except requests.exceptions.RequestException as exc:
        logger.exception(f"Failed to download OUI database: {exc}")
        return jsonify({
            "status": "error",
            "message": f"Network error: {str(exc)}. Please check your internet connection and try again."
        }), 500
    except Exception as exc:
        logger.exception(f"Failed to update OUI database: {exc}")
        return jsonify({
            "status": "error",
            "message": f"Update failed: {str(exc)}"
        }), 500


@utilities_bp.route("/oui-status", methods=["GET"])
def get_oui_status():
    """
    Get status information about the local OUI database.
    
    Returns:
        JSON with database stats and file info
    """
    try:
        filepath = str(OUI_FILE_PATH)
        
        status = {
            "entries": len(_local_oui_db),
            "file_exists": os.path.exists(filepath),
            "file_size_mb": 0,
            "last_modified": None
        }
        
        if os.path.exists(filepath):
            stat = os.stat(filepath)
            status["file_size_mb"] = round(stat.st_size / (1024 * 1024), 2)
            status["last_modified"] = stat.st_mtime
        
        return jsonify(status), 200
        
    except Exception as exc:
        logger.exception(f"Failed to get OUI status: {exc}")
        return jsonify({
            "status": "error",
            "message": str(exc)
        }), 500


@utilities_bp.route("/oui-reload", methods=["POST"])
def reload_oui_database():
    """
    Reload the OUI database from disk without restarting the server.
    
    Useful after manually placing an oui.txt file in the project root,
    or if the database was updated but not loaded.
    
    Returns:
        JSON with reload status and entry count
    """
    global _local_oui_db
    
    try:
        filepath = str(OUI_FILE_PATH)
        
        if not os.path.exists(filepath):
            return jsonify({
                "status": "error",
                "message": f"OUI database file not found at {filepath}. Use POST /utilities/oui-update to download it."
            }), 404
        
        logger.info(f"Reloading OUI database from {filepath}")
        _local_oui_db = load_local_oui_database(filepath)
        
        if len(_local_oui_db) == 0:
            return jsonify({
                "status": "error",
                "message": "OUI database file exists but no entries were loaded. File may be corrupt or in wrong format.",
                "entries": 0
            }), 500
        
        logger.info(f"OUI database reloaded: {len(_local_oui_db)} entries")
        
        return jsonify({
            "status": "success",
            "message": "OUI database reloaded successfully",
            "entries": len(_local_oui_db),
            "size_mb": round(os.path.getsize(filepath) / (1024 * 1024), 2)
        }), 200
        
    except Exception as exc:
        logger.exception(f"Failed to reload OUI database: {exc}")
        return jsonify({
            "status": "error",
            "message": f"Reload failed: {str(exc)}"
        }), 500


@utilities_bp.route("/mac-lookup", methods=["POST"])
def mac_lookup():
    """
    Look up vendor information for MAC addresses.
    
    Request body:
        {
            "macs": ["6a e1 95 7a 04 18", "6e 8b 3e 3f e9 18", ...]
        }
    
    Response:
        [
            {
                "original": "6a e1 95 7a 04 18",
                "mac": "6A:E1:95:7A:04:18",
                "oui": "6A:E1:95",
                "vendor": "Vendor Name",
                "error": null
            },
            ...
        ]
    
    Returns:
        JSON array of lookup results
    """
    try:
        data = request.get_json()
        if not data or "macs" not in data:
            return jsonify({"error": "Missing 'macs' field in request body"}), 400
        
        macs = data["macs"]
        if not isinstance(macs, list):
            return jsonify({"error": "'macs' must be an array"}), 400
        
        if len(macs) > 1000:
            return jsonify({"error": "Maximum 1000 MACs per request"}), 400
        
        results = []
        ouis_to_lookup = set()
        
        # First pass: normalize MACs and collect unique OUIs
        for original_mac in macs:
            result = {
                "original": original_mac,
                "mac": None,
                "oui": None,
                "vendor": None,
                "error": None
            }
            
            try:
                normalized = normalize_mac(original_mac)
                oui = get_oui(normalized)
                
                result["mac"] = normalized
                result["oui"] = oui
                
                # Check if this is a locally administered address
                if is_locally_administered(normalized):
                    result["vendor"] = "LAA (Locally Administered)"
                    logger.info(f"MAC {normalized} is locally administered (LAA)")
                else:
                    # Only add to lookup set if not LAA
                    ouis_to_lookup.add(oui)
                
            except ValueError as exc:
                result["error"] = str(exc)
            except Exception as exc:
                logger.exception(f"Error processing MAC {original_mac}")
                result["error"] = f"Processing error: {str(exc)}"
            
            results.append(result)
        
        # Second pass: lookup vendors for unique OUIs
        # Local lookups are instant, only rate-limit online lookups
        oui_vendors = {}
        ouis_needing_online = []
        
        # First, check all OUIs in local database (instant)
        for oui in ouis_to_lookup:
            vendor = lookup_vendor_local(oui)
            if vendor:
                oui_vendors[oui] = vendor
                logger.info(f"OUI lookup (local): {oui} -> {vendor}")
            else:
                ouis_needing_online.append(oui)
        
        # Then, query online for any OUIs not found locally (rate-limited)
        for i, oui in enumerate(ouis_needing_online):
            # Add delay to respect rate limits (1 request/second for macvendors.com)
            if i > 0:
                time.sleep(1.1)  # Slightly over 1 second to be safe
            
            logger.info(f"OUI not in local DB, querying online: {oui}")
            vendor = lookup_vendor_online(oui)
            oui_vendors[oui] = vendor
            logger.info(f"OUI lookup (online): {oui} -> {vendor}")
        
        # Third pass: assign vendors to results (skip LAA - already marked)
        for result in results:
            if result["oui"] and not result["error"] and not result["vendor"]:
                result["vendor"] = oui_vendors.get(result["oui"], "Unknown")
        
        return jsonify(results), 200
        
    except Exception as exc:
        logger.exception("MAC lookup endpoint error")
        return jsonify({"error": f"Internal server error: {str(exc)}"}), 500
