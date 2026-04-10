"""
Syslog Parser
=============

Parses merged syslog.txt files and extracts structured events with metadata.

Format (common): <timestamp> telekom: <EVENT_ID> <MODULE>.<LOG_LEVEL> [tid=<thread_id>] <message>

Example:
2026-02-27 13:02:30.000 telekom: W019-1 WIFI.INFO [tid=12703]  CosaDMLWiFi_Send_ReceivedHostDetails_To_LMLite-21588 [0C:19:F8:10:DC:6B,NULL,Device.WiFi.SSID.1,0,0]

Format (no level / no thread id): <timestamp> telekom: <EVENT_ID> <MODULE>: <message>

Example:
2026-02-21 13:38:20.000 telekom: W017 ACSD: wl1 Channel switched to 0xe832 . Reason :5 : TXOP
"""

import json
import logging
import re
import yaml
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from logai.timestamp_parser import parse_timestamp

logger = logging.getLogger(__name__)


def decode_chanspec(chanspec_hex: str) -> Dict[str, Any]:
    """
    Decode Broadcom chanspec (channel specification) from hex value.
    
    Broadcom chanspec format varies by chipset. This is a best-effort decoder.
    Common format:
    - Lower byte (bits 0-7): Channel number
    - Upper bytes contain bandwidth and band information
    
    Heuristic approach:
    - If upper nibble >= 0xE: 80MHz
    - Else if upper byte >= 0x18: likely 20MHz with extended info
    - Else if upper byte >= 0x10: 20MHz, 5GHz
    - Else: 20MHz, 2.4GHz
    
    Examples from user data:
    - 0x100b, 0x1007, 0x1809, 0x1803: channel X, 20MHz, 5GHz
    - 0xe832: channel 50, 80MHz, 5GHz
    
    Returns dict with channel, bandwidth_mhz, band
    """
    try:
        # Remove 0x prefix if present
        hex_str = chanspec_hex.replace('0x', '').replace('0X', '')
        value = int(hex_str, 16)
        
        # Extract channel number (bits 0-7)
        channel = value & 0xFF
        
        # Extract upper byte for band/BW hints
        upper_byte = (value >> 8) & 0xFF
        upper_nibble = (value >> 12) & 0x0F
        
        # Heuristic bandwidth detection
        if upper_nibble >= 0x0E:
            # 0xEXXX pattern suggests 80MHz
            bandwidth_mhz = 80
        elif upper_nibble >= 0x0D:
            # 0xDXXX pattern suggests 40MHz
            bandwidth_mhz = 40
        else:
            # Default to 20MHz for 0x1XXX patterns
            bandwidth_mhz = 20
        
        # Band detection: if upper_byte >= 0x10, likely 5GHz
        band = '5GHz' if upper_byte >= 0x10 else '2.4GHz'
        
        # Sideband info (for 40MHz+) - simplified
        sideband = None
        
        return {
            'channel': channel,
            'bandwidth_mhz': bandwidth_mhz,
            'band': band,
            'sideband': sideband
        }
    except (ValueError, TypeError) as e:
        logger.debug(f"Failed to decode chanspec {chanspec_hex}: {e}")
        return {
            'channel': None,
            'bandwidth_mhz': None,
            'band': None,
            'sideband': None
        }

# Format 1: Telekom event format with event IDs (from specialized log files)
# <timestamp> telekom: <EVENT_ID> <MODULE>.<LOG_LEVEL> [tid=<thread_id>] <message>
TELEKOM_EVENT_REGEX = re.compile(
    r'^(?P<timestamp>[\d\-\s:T\.]+)\s+telekom:\s+(?P<event_id>\S+)\s+(?P<module>\S+)\s+\[tid=(?P<thread_id>\d+)\]\s+(?P<message>.*)$'
)

# Format 2: Telekom format without event IDs but with module (from logs like WiFilog.txt, TELCOVOICEMANAGERLog.txt)
# <timestamp> telekom: <MODULE>.<LOG_LEVEL> [tid=<thread_id>] <message>
TELEKOM_MODULE_REGEX = re.compile(
    r'^(?P<timestamp>[\d\-\s:T\.]+)\s+telekom:\s+(?P<module>\S+)\s+\[tid=(?P<thread_id>\d+)\]\s+(?P<message>.*)$'
)

# Format 2b: Telekom with event id and module as "NAME:" (no .LOG_LEVEL, no [tid=])
# <timestamp> telekom: <EVENT_ID> <MODULE>: <message>
TELEKOM_EVENT_MODULE_COLON_REGEX = re.compile(
    r'^(?P<timestamp>[\d\-\s:T\.]+)\s+telekom:\s+'
    r'(?P<event_id>\S+)\s+'
    r'(?P<module>[A-Za-z][A-Za-z0-9_]*):\s+'
    r'(?P<message>.*)$'
)

# Format 2c: Same as 2b but optional leading event id (module-only prefix)
# <timestamp> telekom: <MODULE>: <message>
TELEKOM_MODULE_COLON_ONLY_REGEX = re.compile(
    r'^(?P<timestamp>[\d\-\s:T\.]+)\s+telekom:\s+'
    r'(?P<module>[A-Za-z][A-Za-z0-9_]*):\s+'
    r'(?P<message>.*)$'
)

# Format 3: Standard syslog format (from syslog.txt)
# <timestamp> telekom <facility>.<priority> <program>: <message>
STANDARD_SYSLOG_REGEX = re.compile(
    r'^(?P<timestamp>[\d\-\s:T\.]+)\s+telekom\s+(?P<facility>\w+)\.(?P<priority>\w+)\s+(?P<program>\S+):\s+(?P<message>.*)$'
)

# Format 4: Simple telekom lines (fallback)
# <timestamp> telekom <facility>.<priority> <message>
SIMPLE_TELEKOM_REGEX = re.compile(
    r'^(?P<timestamp>[\d\-\s:T\.]+)\s+telekom\s+(?P<facility>\w+)\.(?P<priority>\w+)\s+(?P<message>.*)$'
)


def load_event_mapping(config_path: Path) -> Dict:
    """Load event ID mapping from YAML config."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning(f"Event mapping config not found: {config_path}")
        return {}
    except yaml.YAMLError as e:
        logger.error(f"Error parsing event mapping config: {e}")
        return {}


def extract_metadata(message: str, fields: List[str]) -> Dict[str, str]:
    """Extract metadata fields from message text."""
    metadata = {}
    
    if 'mac_address' in fields:
        # Match MAC addresses in various formats
        mac_patterns = [
            r'([0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2})',
            r'([0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2})',
            r'([0-9A-F]{12})'
        ]
        for pattern in mac_patterns:
            mac_match = re.search(pattern, message, re.IGNORECASE)
            if mac_match:
                metadata['mac'] = mac_match.group(1)
                break
    
    if 'ssid' in fields:
        # Extract SSID from Device.WiFi.SSID.X patterns
        ssid_match = re.search(r'Device\.WiFi\.SSID\.(\d+)', message)
        if ssid_match:
            metadata['ssid'] = f"SSID.{ssid_match.group(1)}"
    
    if 'ipv4_address' in fields:
        ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', message)
        if ip_match:
            metadata['ip'] = ip_match.group(1)
    
    if 'download_bandwidth' in fields:
        dl_match = re.search(r'download bandwidth:\s*(\d+)\s*kbit/s', message, re.IGNORECASE)
        if dl_match:
            metadata['download_kbps'] = dl_match.group(1)
    
    if 'upload_bandwidth' in fields:
        ul_match = re.search(r'upload bandwidth:\s*(\d+)\s*kbit/s', message, re.IGNORECASE)
        if ul_match:
            metadata['upload_kbps'] = ul_match.group(1)
    
    if 'domain_name' in fields:
        # Extract domain names from DNS queries
        domain_patterns = [
            r'query\s+for\s+([a-zA-Z0-9\-\.]+)',
            r'domain\s+([a-zA-Z0-9\-\.]+)',
            r'host\s+([a-zA-Z0-9\-\.]+)'
        ]
        for pattern in domain_patterns:
            domain_match = re.search(pattern, message, re.IGNORECASE)
            if domain_match:
                metadata['domain'] = domain_match.group(1)
                break
    
    if 'channel_switch' in fields:
        # Extract ACSD channel switch information
        # Pattern 1 (W017): wl0 Channel switched to 0x1803 . Reason :1 : Manual channel switch triggered by autochannel command
        # Pattern 2 (W018): Channel switched to 0xef32 due to Radar Detection
        
        # Try W018 pattern first (radar detection - no radio interface in message)
        radar_pattern = r'^Channel\s+switched\s+to\s+(?P<chanspec>0x[0-9A-Fa-f]+)\s+due\s+to\s+Radar\s+Detection'
        radar_match = re.search(radar_pattern, message, re.IGNORECASE)
        
        if radar_match:
            # W018 - Radar detection (no wl0/wl1 in message; label for fleet charts)
            metadata['radio_interface'] = 'RADAR'
            metadata['chanspec'] = radar_match.group('chanspec')
            metadata['reason_code'] = '2'  # DFS/Radar
            metadata['reason_text'] = 'Radar Detection'
            metadata['reason_bucket'] = 'radar'
            metadata['event_type'] = 'W018'
            
            # Decode chanspec
            chanspec = radar_match.group('chanspec')
            decoded = decode_chanspec(chanspec)
            if decoded['bandwidth_mhz'] is not None:
                metadata['bandwidth_mhz'] = decoded['bandwidth_mhz']
            if decoded['band'] is not None:
                metadata['band'] = decoded['band']
            if decoded['channel'] is not None:
                metadata['channel'] = decoded['channel']
            if decoded.get('sideband'):
                metadata['sideband'] = decoded['sideband']
        else:
            # Try W017 pattern
            channel_switch_pattern = r'^(?P<radio>wl\d+)\s+Channel\s+switched\s+to\s+(?P<chanspec>0x[0-9A-Fa-f]+)\s+\.\s+Reason\s+:(?P<reason_code>\d+)\s+:\s+(?P<reason_text>.*)$'
            cs_match = re.search(channel_switch_pattern, message)
            if cs_match:
                metadata['radio_interface'] = cs_match.group('radio')
                chanspec = cs_match.group('chanspec')
                metadata['chanspec'] = chanspec
                metadata['reason_code'] = cs_match.group('reason_code')
                metadata['reason_text'] = cs_match.group('reason_text').strip()
                metadata['event_type'] = 'W017'
                
                # Decode chanspec to extract channel number and bandwidth
                decoded = decode_chanspec(chanspec)
                if decoded['bandwidth_mhz'] is not None:
                    metadata['bandwidth_mhz'] = decoded['bandwidth_mhz']
                if decoded['band'] is not None:
                    metadata['band'] = decoded['band']
                if decoded['channel'] is not None:
                    metadata['channel'] = decoded['channel']
                if decoded.get('sideband'):
                    metadata['sideband'] = decoded['sideband']

                # Derive reason bucket from reason code
                # Based on Broadcom ACSD (Auto Channel Selection Daemon) reason codes:
                # 0: None/Unknown
                # 1: Manual (Airties cloud autochannel command)
                # 2: DFS (Radar detection - older firmware)
                # 3: CS_Timer (Periodic ACS run - 900 sec interval)
                # 4: ITFR (Interference)
                # 5: TXOP (Transmission opportunity - channel busy)
                # 6: NONACS (Non-ACS channel switch - typically radar in newer firmware)
                # 7: EXCL (Excluded channel)
                # 8: FCS (Fast channel switch)
                # 9+: Other/Extended reasons
                reason_code = cs_match.group('reason_code')
                reason_code_int = int(reason_code) if reason_code.isdigit() else -1
                
                if reason_code_int == 1:
                    metadata['reason_bucket'] = 'airties_cloud'
                elif reason_code_int in [2, 6]:
                    # Both DFS (old) and NONACS (new) are radar-related
                    metadata['reason_bucket'] = 'radar'
                elif reason_code_int == 5:
                    metadata['reason_bucket'] = 'txop'
                elif reason_code_int == 3:
                    # CS_Timer - periodic ACS run
                    metadata['reason_bucket'] = 'cs_timer'
                elif reason_code_int == 4:
                    # General interference
                    metadata['reason_bucket'] = 'interference'
                elif reason_code_int in [7, 8]:
                    # Excluded channel or fast channel switch
                    metadata['reason_bucket'] = 'acs_policy'
                elif reason_code_int == 0:
                    metadata['reason_bucket'] = 'unknown'
                else:
                    metadata['reason_bucket'] = 'other'
                    # Log unexpected reason codes for debugging
                    logger.info(f"Unexpected ACSD reason code: {reason_code} - '{cs_match.group('reason_text')}')")
    
    return metadata


def categorize_event(event_id: str, module: str, event_mapping: Dict) -> Dict[str, Any]:
    """
    Categorize an event based on event_id and module using the mapping config.
    
    Returns mapping dict with category, description, severity, etc.
    """
    # First, try exact event_id match
    if event_id in event_mapping:
        return event_mapping[event_id]
    
    # Fallback: use category patterns based on module
    category_patterns = event_mapping.get('category_patterns', [])
    for pattern_config in category_patterns:
        pattern = pattern_config.get('pattern', '')
        if re.match(pattern, module, re.IGNORECASE):
            return {
                'category': pattern_config.get('category', 'other'),
                'severity': pattern_config.get('default_severity', 'info'),
                'description': None,  # Will use raw message
                'extract_metadata': []
            }
    
    # Default fallback
    return {
        'category': 'other',
        'severity': 'info',
        'description': None,
        'extract_metadata': []
    }


def parse_syslog_file(syslog_path: Path, event_mapping: Dict) -> Dict:
    """
    Parse merged syslog.txt and return structured events.
    
    Returns:
        {
            "summary": {
                "total_lines": int,
                "parsed_events": int,
                "skipped_lines": int,
                "event_type_counts": {"wifi": 10, "parodus": 5, ...},
                "time_range": {"first": "...", "last": "..."}
            },
            "events": [
                {
                    "timestamp": "2026-02-27T13:02:30",
                    "event_id": "W019-1",
                    "category": "wifi",
                    "module": "WIFI.INFO",
                    "thread_id": "12703",
                    "message": "Client disconnected",
                    "description": "WiFi client disconnected",  # from YAML
                    "severity": "info",
                    "metadata": {"mac": "aa:bb:cc:dd:ee:ff"}
                },
                ...
            ]
        }
    """
    events = []
    total_lines = 0
    parsed_events = 0
    skipped_lines = 0
    event_type_counts = defaultdict(int)
    
    logger.info(f"Starting to parse syslog file: {syslog_path}")
    
    try:
        with open(syslog_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                total_lines += 1
                line = line.strip()
                
                # Skip empty lines
                if not line:
                    skipped_lines += 1
                    continue
                
                # Skip merge markers from log_merger.py
                if 'LOG_MERGE_MARKER' in line:
                    skipped_lines += 1
                    continue
                
                # Try to parse line with different regex patterns
                event_data = None
                
                # Format 1: Telekom event format with event IDs
                match = TELEKOM_EVENT_REGEX.match(line)
                if match:
                    event_data = match.groupdict()
                    event_data['format_type'] = 'telekom_event'
                
                # Format 2: Telekom format without event IDs but with module  
                if not event_data:
                    match = TELEKOM_MODULE_REGEX.match(line)
                    if match:
                        event_data = match.groupdict()
                        event_data['event_id'] = 'NO_ID'  # Generate from module/message
                        event_data['format_type'] = 'telekom_module'

                # Format 2b: telekom: <event_id> <MODULE>: <message> (no .LEVEL, no tid)
                if not event_data:
                    match = TELEKOM_EVENT_MODULE_COLON_REGEX.match(line)
                    if match:
                        event_data = match.groupdict()
                        event_data['format_type'] = 'telekom_event_module_colon'
                        event_data['thread_id'] = '0'

                # Format 2c: telekom: <MODULE>: <message>
                if not event_data:
                    match = TELEKOM_MODULE_COLON_ONLY_REGEX.match(line)
                    if match:
                        event_data = match.groupdict()
                        event_data['event_id'] = 'NO_ID'
                        event_data['format_type'] = 'telekom_module_colon_only'
                        event_data['thread_id'] = '0'
                
                # Format 3: Standard syslog format
                if not event_data:
                    match = STANDARD_SYSLOG_REGEX.match(line)
                    if match:
                        event_data = match.groupdict()
                        # Map syslog fields to our format
                        event_data['event_id'] = 'NO_ID'
                        event_data['module'] = f"{event_data['facility']}.{event_data['priority']}"
                        event_data['thread_id'] = '0'  # Standard syslog doesn't have thread ID
                        event_data['format_type'] = 'standard_syslog'
                
                # Format 4: Simple telekom lines
                if not event_data:
                    match = SIMPLE_TELEKOM_REGEX.match(line)
                    if match:
                        event_data = match.groupdict()
                        event_data['event_id'] = 'NO_ID'
                        event_data['module'] = f"{event_data['facility']}.{event_data['priority']}"
                        event_data['thread_id'] = '0'
                        event_data['format_type'] = 'simple_telekom'
                
                if not event_data:
                    skipped_lines += 1
                    logger.debug(f"Could not parse line {line_num}: {line[:100]}...")
                    continue
                
                # Parse timestamp
                try:
                    timestamp = parse_timestamp(event_data['timestamp'])
                    if not timestamp:
                        # Try manual parsing for various telekom formats
                        timestamp_str = event_data['timestamp'].strip()
                        try:
                            # ISO format: 2026-02-20T03:33:36
                            timestamp = datetime.fromisoformat(timestamp_str.replace('T', ' '))
                        except ValueError:
                            try:
                                # Format with milliseconds: 2026-02-27 13:02:30.000
                                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
                            except ValueError:
                                try:
                                    # Format without milliseconds: 2026-02-27 13:02:30
                                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                                except ValueError:
                                    logger.debug(f"Could not parse timestamp: {timestamp_str}")
                                    skipped_lines += 1
                                    continue
                except Exception as e:
                    logger.debug(f"Timestamp parsing error: {e}")
                    skipped_lines += 1
                    continue
                
                parsed_events += 1
                
                # Get event categorization
                event_id = event_data['event_id']
                module = event_data.get('module', 'UNKNOWN')
                
                # For generated event IDs, create a meaningful ID from the content
                if event_id == 'NO_ID':
                    # Try to generate event ID from program name or message content
                    if event_data['format_type'] == 'standard_syslog':
                        program = event_data.get('program', 'unknown')
                        event_id = f"SYSLOG_{program.upper()}"
                    elif event_data['format_type'] == 'telekom_module_colon_only':
                        event_id = f"LOG_{module.upper()}"
                    else:
                        # Generate from module name
                        module_parts = module.split('.')
                        if len(module_parts) >= 2:
                            event_id = f"LOG_{module_parts[0].upper()}"
                        else:
                            event_id = f"LOG_{module.upper()}"
                
                mapping = categorize_event(event_id, module, event_mapping)
                
                # Extract metadata if specified
                metadata = {}
                if mapping.get('extract_metadata'):
                    metadata = extract_metadata(
                        event_data['message'],
                        mapping['extract_metadata']
                    )
                
                # Build event object
                event = {
                    "timestamp": timestamp.isoformat(),
                    "event_id": event_id,
                    "category": mapping.get('category', 'other'),
                    "module": module,
                    "thread_id": event_data.get('thread_id', '0'),
                    "message": event_data['message'].strip(),
                    "description": mapping.get('description') or event_data['message'].strip(),
                    "severity": mapping.get('severity', 'info'),
                    "metadata": metadata,
                    "line_number": line_num
                }
                
                events.append(event)
                event_type_counts[event['category']] += 1
                
                # Log progress for large files
                if parsed_events % 1000 == 0:
                    logger.info(f"Parsed {parsed_events} events from {total_lines} lines")
    
    except Exception as e:
        logger.error(f"Error parsing syslog file {syslog_path}: {e}")
        raise
    
    # Sort events chronologically
    events.sort(key=lambda e: e['timestamp'])
    
    summary = {
        "total_lines": total_lines,
        "parsed_events": parsed_events,
        "skipped_lines": skipped_lines,
        "event_type_counts": dict(event_type_counts),
        "time_range": {
            "first": events[0]['timestamp'] if events else None,
            "last": events[-1]['timestamp'] if events else None
        }
    }
    
    logger.info(f"Parsing complete: {parsed_events} events from {total_lines} lines")
    logger.info(f"Event categories: {dict(event_type_counts)}")
    
    return {
        "summary": summary,
        "events": events
    }


def save_syslog_cache(project_dir: Path, data: Dict):
    """Save parsed syslog data to cache (follows telemetry pattern)."""
    cache_dir = project_dir / "syslog"
    cache_dir.mkdir(exist_ok=True)
    cache_path = cache_dir / "response.json"
    
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
        logger.info(f"Syslog data cached to: {cache_path}")
    except Exception as e:
        logger.error(f"Failed to save syslog cache: {e}")
        raise


def load_syslog_cache(project_dir: Path) -> Optional[Dict]:
    """Load cached syslog data."""
    cache_path = project_dir / "syslog" / "response.json"
    if not cache_path.exists():
        return None
    
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Loaded syslog cache from: {cache_path}")
        return data
    except Exception as e:
        logger.error(f"Failed to load syslog cache: {e}")
        return None


def parse_syslog_for_project(project_dir: Path, cpe_id: Optional[str] = None) -> Dict:
    """
    Main entry point for parsing syslog for a project/CPE.
    Handles cache loading/saving and event mapping loading.
    """
    # Determine working directory
    work_dir = project_dir
    if cpe_id:
        work_dir = project_dir / cpe_id
    
    # Check cache first
    cached = load_syslog_cache(work_dir)
    if cached:
        return cached
    
    # Find syslog file
    syslog_path = work_dir / "syslog.txt"
    if not syslog_path.exists():
        raise FileNotFoundError(f"syslog.txt not found in {work_dir}")
    
    # Load event mapping
    config_path = Path(__file__).parent.parent / "configs" / "syslog_event_mapping.yaml"
    event_mapping = load_event_mapping(config_path)
    
    # Parse syslog
    parsed_data = parse_syslog_file(syslog_path, event_mapping)
    
    # Build final response
    response = {
        "device_info": {
            "serial": cpe_id or "unknown",
            "cpe_id": cpe_id
        },
        "summary": parsed_data['summary'],
        "events": parsed_data['events'],
        "cached": False
    }
    
    # Cache the response
    save_syslog_cache(work_dir, response)
    
    return response