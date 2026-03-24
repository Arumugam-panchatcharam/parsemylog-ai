"""
LLM Service — OpenAI (primary) + OpenRouter (fallback) client, evidence-grounded prompt builder.
==================================================================================================

Uses OpenAI's API as primary provider with function calling support for tool access.
Falls back to OpenRouter's free-tier models on errors or when OpenAI is not configured.
Builds evidence-grounded prompts from the parsed pipeline data.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENROUTER_BASE_URL = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
).rstrip("/")
OPENROUTER_API_KEY = (os.environ.get("OPENROUTER_API_KEY") or "").strip()

# Default free models (ordered; first is preferred). Override with OPENROUTER_MODELS.
_DEFAULT_OPENROUTER_MODELS = [
    "qwen/qwen3-coder:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "deepseek/deepseek-r1-0528:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-small-3.1-24b-instruct-2507:free",
]

def _get_openrouter_models() -> List[str]:
    """Ordered list of OpenRouter model IDs to try (with fallback)."""
    raw = os.environ.get("OPENROUTER_MODELS", "").strip()
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    return _DEFAULT_OPENROUTER_MODELS.copy()

MAX_CONCURRENT = int(os.environ.get("LLM_MAX_CONCURRENT", "2"))
MAX_HISTORY_MESSAGES = int(os.environ.get("LLM_MAX_HISTORY_MESSAGES", "20"))  # Conversation memory window for follow-ups
MAX_CONTEXT_CHARS = 6000   # Approx chars of log evidence injected
REQUEST_TIMEOUT = 180

# Retryable HTTP status codes (try next model)
RETRYABLE_STATUS_CODES = {429, 502, 503}

_semaphore = threading.Semaphore(MAX_CONCURRENT)
_queue_size = 0
_queue_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Health / availability
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """
    LLM is available if either OpenAI or OpenRouter is configured.
    Prioritizes OpenAI, falls back to OpenRouter.
    """
    try:
        from api.openai_service import is_available as openai_available
        if openai_available():
            return True
    except Exception as e:
        logger.warning(f"[LLM] OpenAI check failed: {e}")
    
    return bool(OPENROUTER_API_KEY)


def get_model_info() -> Optional[Dict[str, Any]]:
    """Return provider/model info for the UI (no external call)."""
    # Try OpenAI first
    try:
        from api.openai_service import get_model_info as openai_model_info
        info = openai_model_info()
        if info:
            return info
    except Exception as e:
        logger.warning(f"[LLM] OpenAI model info failed: {e}")
    
    # Fallback to OpenRouter
    if not OPENROUTER_API_KEY:
        return None
    models = _get_openrouter_models()
    first = models[0] if models else "openrouter"
    return {
        "id": first,
        "object": "provider",
        "provider": "OpenRouter (free, fallback)",
    }


def is_enabled(dbm) -> bool:
    """Check if LLM is enabled in system settings."""
    val = dbm.get_setting("llm_enabled", "false")
    return val.lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Request queue helpers
# ---------------------------------------------------------------------------

def queue_position() -> int:
    """Return current number of waiting requests."""
    with _queue_lock:
        return _queue_size


def _acquire_slot():
    """Acquire an LLM inference slot (blocks if busy)."""
    global _queue_size
    with _queue_lock:
        _queue_size += 1
    _semaphore.acquire()
    with _queue_lock:
        _queue_size -= 1


def _release_slot():
    """Release an LLM inference slot."""
    _semaphore.release()


# ---------------------------------------------------------------------------
# Evidence-grounded system prompt builder
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """You are an RDK/CPE log analyst assistant. ONLY answer based on the evidence provided below. If the logs do not contain enough information, say so clearly. Always cite log file names and timestamps as evidence when available.

Do NOT speculate or invent information not present in the logs. If you are uncertain, state your uncertainty.

=== PROJECT INFO ===
{project_info}

=== LOG EVIDENCE ===

{evidence}

=== INSTRUCTIONS ===
- Use the conversation history (previous user and assistant messages) to understand follow-up questions. Answer in context; e.g. "that", "it", "the reboots" refer to earlier topics in this conversation.
- Provide thorough and complete answers. Cover ALL relevant evidence sections (device info, reboots, telemetry, error patterns) when summarizing.
- When referencing events, include timestamps and filenames.
- If asked about something not covered by the evidence, say "I don't have enough log data to answer that."
- Format your responses in clear markdown with headers for different topics.
- Always finish your response completely — do not stop mid-sentence or mid-section.
"""


def _load_reboots(project_dir: Path) -> str:
    """Load reboot timeline from cache."""
    cache = project_dir / ".reboots_cache.json"
    if not cache.exists():
        return "No reboot data available."
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        # Handle both old format (list) and new format (dict with "reboots" key)
        if isinstance(data, dict) and "reboots" in data:
            reboots = data["reboots"]
        elif isinstance(data, list):
            reboots = data
        else:
            return "Invalid reboot cache format."
        
        if not reboots:
            return "No reboots detected."
        lines = [f"Total reboots: {len(reboots)}"]
        for r in reboots[:20]:  # Limit to 20 most relevant
            lines.append(f"  - {r.get('timestamp', '?')}: {r.get('reason', 'unknown')}")
        if len(reboots) > 20:
            lines.append(f"  ... and {len(reboots) - 20} more")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[LLM] Error loading reboots cache: {e}")
        return "Error loading reboot data."


def _load_telemetry_summary(project_dir: Path) -> str:
    """Load telemetry summary from cache and format for LLM context."""
    cache = project_dir / "telemetry" / "response.json"
    if not cache.exists():
        return "No telemetry data available."
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        
        lines = []
        
        # === Device Info ===
        device = data.get("device_info", {})
        if device:
            lines.append("Device Information:")
            for k, v in device.items():
                lines.append(f"  {k}: {v}")
        
        # === Telemetry Summary (time range and report stats) ===
        summary = data.get("summary", {})
        if summary:
            lines.append("\nTelemetry Summary:")
            if "total" in summary or "parsed" in summary:
                lines.append(f"  Reports: {summary.get('parsed', 0)}/{summary.get('total', 0)}")
            if "overall_time_range" in summary and summary["overall_time_range"]:
                time_range = summary["overall_time_range"]
                start = time_range.get("first") or time_range.get("start", "?")
                end = time_range.get("last") or time_range.get("end", "?")
                lines.append(f"  Time range: {start} to {end}")
        
        # === Key Metrics (performance indicators) ===
        key_metrics = data.get("key_metrics", [])
        if key_metrics:
            lines.append("\nKey Metrics:")
            for metric in key_metrics:
                label = metric.get("label", "Unknown")
                
                # Format based on metric type
                if label == "Reports":
                    value = metric.get("value", "N/A")
                    time_range = metric.get("time_range", "")
                    lines.append(f"  {label}: {value}" + (f" ({time_range})" if time_range else ""))
                
                elif label == "Memory Free":
                    first = metric.get("first")
                    last = metric.get("last")
                    total = metric.get("total")
                    unit = metric.get("unit", "KB")
                    trend = metric.get("trend", "stable")
                    if first is not None and last is not None:
                        lines.append(f"  {label}: {first}{unit} → {last}{unit} (total: {total or '?'}{unit}, trend: {trend})")
                    else:
                        lines.append(f"  {label}: Not available")
                
                elif label == "CPU Usage":
                    avg = metric.get("avg")
                    peak = metric.get("peak")
                    unit = metric.get("unit", "%")
                    if avg is not None and peak is not None:
                        lines.append(f"  {label}: avg {avg}{unit}, peak {peak}{unit}")
                    else:
                        lines.append(f"  {label}: Not available")
                
                elif label == "Uptime":
                    first = metric.get("first")
                    last = metric.get("last")
                    resets = metric.get("resets", 0)
                    unit = metric.get("unit", "")
                    if first is not None and last is not None:
                        lines.append(f"  {label}: {first}{unit} → {last}{unit} (resets: {resets})")
                    else:
                        lines.append(f"  {label}: Not available")
                
                elif label == "Reboot Reasons":
                    counts = metric.get("counts", {})
                    if counts:
                        reasons_str = ", ".join(f"{reason} ({count})" for reason, count in counts.items())
                        lines.append(f"  {label}: {reasons_str}")
                    else:
                        lines.append(f"  {label}: None detected")
                
                elif label == "Connected Devices":
                    avg = metric.get("avg")
                    peak = metric.get("peak")
                    if avg is not None and peak is not None:
                        lines.append(f"  {label}: avg {avg}, peak {peak}")
                    else:
                        lines.append(f"  {label}: Not available")
                
                elif label in ("DSL Downstream", "DSL Upstream"):
                    min_val = metric.get("min")
                    max_val = metric.get("max")
                    unit = metric.get("unit", "")
                    if min_val is not None and max_val is not None:
                        lines.append(f"  {label}: {min_val}{unit} - {max_val}{unit}")
                    else:
                        lines.append(f"  {label}: Not available")
                
                else:
                    # Generic fallback
                    value = metric.get("value") or metric.get("avg") or metric.get("first") or "N/A"
                    lines.append(f"  {label}: {value}")
        
        # === Status Labels (device health/connectivity) ===
        status_labels = data.get("status_labels", [])
        if status_labels:
            lines.append("\nStatus Labels (Device Health):")
            for label in status_labels:
                label_type = label.get("type", "Unknown")
                instance = label.get("instance", "")
                status = label.get("status", "Unknown")
                meta = label.get("meta", {})
                
                # Format label line
                if instance:
                    label_line = f"  {label_type} {instance}: {status}"
                else:
                    label_line = f"  {label_type}: {status}"
                
                # Add metadata if present
                if meta:
                    meta_str = ", ".join(f"{k}={v}" for k, v in meta.items())
                    label_line += f" ({meta_str})"
                
                lines.append(label_line)
        
        result = "\n".join(lines)
        return result if result.strip() else "Telemetry data present but empty."
    
    except Exception as e:
        logger.warning(f"[LLM] Error loading telemetry: {e}")
        return "Error loading telemetry data."


def _load_device_info(project_dir: Path) -> str:
    """Load device info from version.txt or fallback."""
    try:
        from logai.info_extractor import find_and_parse_version_txt, find_and_build_fallback_device_info

        version = find_and_parse_version_txt(project_dir)
        if version:
            lines = []
            for k, v in version.items():
                if v and k not in ("raw_blocks",):
                    lines.append(f"  {k}: {v}")
            return "From version.txt:\n" + "\n".join(lines) if lines else ""

        fallback = find_and_build_fallback_device_info(project_dir)
        if fallback:
            lines = [f"  {k}: {v}" for k, v in fallback.items()]
            return "Device info (fallback):\n" + "\n".join(lines)

        return "No device info available."
    except Exception as e:
        logger.warning(f"[LLM] Error loading device info: {e}")
        return "Error loading device info."


def _detect_cpe_mention(user_query: str, project_id: str, user_id: int) -> Optional[str]:
    """
    Detect if user mentioned a specific CPE by MAC, serial, or ID in their message.
    Returns the CPE ID if found, otherwise None (indicating multi-CPE analysis).
    """
    if not user_query:
        return None
    
    query_lower = user_query.lower()
    
    # Try to find all available CPEs for this project
    from pathlib import Path
    from logai.utils.constants import UPLOAD_DIRECTORY
    
    project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    if not project_dir.exists():
        return None
    
    # Get all CPE directories
    cpe_dirs = []
    for item in project_dir.iterdir():
        if item.is_dir() and not item.name.startswith(('.', '_')):
            cpe_id = item.name
            # Check if it looks like a valid CPE
            if (item / "telemetry" / "response.json").exists() or \
               (item / ".reboots_cache.json").exists():
                cpe_dirs.append(cpe_id)
    
    if not cpe_dirs:
        return None
    
    # Check if any CPE ID is mentioned directly
    for cpe_id in cpe_dirs:
        if cpe_id.lower() in query_lower:
            return cpe_id
        # Also check partial matches (first 8 chars of serial)
        if len(cpe_id) >= 8 and cpe_id[:8].lower() in query_lower:
            return cpe_id
    
    # Check for common MAC address patterns (XX:XX:XX:XX:XX:XX or XXXXXXXXXXXX)
    import re
    mac_pattern = r'([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}|[0-9a-fA-F]{12}'
    mac_matches = re.findall(mac_pattern, query_lower)
    
    if mac_matches:
        # Try to find CPE with this MAC
        for cpe_id in cpe_dirs:
            cpe_dir = project_dir / cpe_id
            device_info = _load_device_info(cpe_dir)
            if device_info and any(mac.replace(':', '').lower() in device_info.lower() for mac in mac_matches):
                return cpe_id
    
    # No specific CPE mentioned, use all CPEs
    return None


def _load_rag_context(project_id: str, cpe_id: Optional[str],
                      query: str, top_k: int = 5) -> str:
    """Retrieve semantic search results from Qdrant for the user query."""
    try:
        from logai.utils.constants import QDRANT_URL
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        from api.app import get_embedding_model

        # STRATEGY: Single collection per project with CPE metadata filtering
        collection = f"project_{project_id}"
        
        # Build metadata filter if searching within a specific CPE
        query_filter = None
        if cpe_id:
            query_filter = Filter(must=[
                FieldCondition(key="cpe_serial", match=MatchValue(value=cpe_id))
            ])

        client = QdrantClient(url=QDRANT_URL, timeout=10)

        # Check collection exists
        try:
            client.get_collection(collection)
        except Exception:
            return "No indexed log data available for semantic search."

        model = get_embedding_model()
        query_vector = model.encode([query], normalize_embeddings=True)[0].tolist()

        results = client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
        )

        points = results.points if hasattr(results, "points") else []
        if not points:
            return "No matching log templates found."

        lines = ["Matching log patterns (by semantic similarity):"]
        for i, r in enumerate(points, 1):
            payload = r.payload or {}
            template = payload.get("template", "N/A")
            count = payload.get("count", "?")
            sample = payload.get("sample", "")
            source = payload.get("source_file", "")
            lines.append(f"\n  [{i}] Template: {template}")
            lines.append(f"      Count: {count}")
            if source:
                lines.append(f"      Source: {source}")
            if sample:
                lines.append(f"      Sample: {sample[:300]}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[LLM] RAG retrieval error: {e}")
        return "Semantic search unavailable."


def _get_all_cpe_dirs(project_root: Path) -> List[tuple[str, Path]]:
    """Get all CPE directories in the project root."""
    cpe_dirs = []
    if not project_root.exists():
        return cpe_dirs
    
    for item in project_root.iterdir():
        if item.is_dir() and not item.name.startswith(('.', '_')):
            # Check if this looks like a CPE directory (contains telemetry or log files)
            if (item / "telemetry" / "response.json").exists() or \
               (item / ".reboots_cache.json").exists() or \
               any(item.glob("*.txt")) or \
               any(item.glob("*.log")):
                cpe_dirs.append((item.name, item))
    
    return sorted(cpe_dirs)


def _load_all_cpes_summary(project_root: Path) -> str:
    """Load summary from all CPEs in project when no specific CPE is selected."""
    cpe_dirs = _get_all_cpe_dirs(project_root)
    
    if not cpe_dirs:
        return "No CPE data available."
    
    if len(cpe_dirs) == 1:
        # Single CPE, load normally
        cpe_id, cpe_dir = cpe_dirs[0]
        return _load_telemetry_summary(cpe_dir)
    
    # Multiple CPEs: aggregate summary
    lines = [f"Project has {len(cpe_dirs)} devices:\n"]
    
    for cpe_id, cpe_dir in cpe_dirs:
        lines.append(f"\n=== Device: {cpe_id} ===")
        
        # Device info
        device = _load_device_info(cpe_dir)
        if device and "No device info" not in device:
            # Just get the first line (model/version)
            first_line = device.split('\n')[0] if '\n' in device else device
            lines.append(first_line)
        
        # Reboots summary
        reboots = _load_reboots(cpe_dir)
        if "No reboot" not in reboots:
            # Extract count
            lines.append(reboots.split('\n')[0] if '\n' in reboots else reboots)
        
        # Telemetry status
        telemetry = _load_telemetry_summary(cpe_dir)
        if telemetry and "No telemetry" not in telemetry:
            # Extract key metrics only (skip full details)
            for line in telemetry.split('\n'):
                if any(x in line for x in ['Memory Free', 'CPU Usage', 'Reboot Reasons', 'Connected Devices']):
                    lines.append(f"  {line.strip()}")
    
    return "\n".join(lines) if lines else "No CPE data available."


def build_system_prompt(project_name: str, project_dir: Path,
                        project_id: str, cpe_id: Optional[str],
                        user_query: str, user_id: int = 1) -> str:
    """
    Build a grounded system prompt with all available pipeline evidence.
    
    When cpe_id is None, detects if user mentioned a specific CPE in their query.
    If a CPE is mentioned, loads data for that CPE.
    Otherwise, loads data from all CPEs in the project.
    """
    # Detect if user mentioned a specific CPE
    if cpe_id is None:
        detected_cpe = _detect_cpe_mention(user_query, project_id, user_id)
        cpe_id = detected_cpe
    
    # Project info section
    project_info_parts = [f"Project: {project_name}"]
    
    # Determine if we're looking at single or multiple CPEs
    if cpe_id:
        project_info_parts.append(f"CPE: {cpe_id}")
        working_dir = project_dir / cpe_id if cpe_id else project_dir
    else:
        # cpe_id is None: we're at project root, need to discover all CPEs
        working_dir = project_dir
        cpe_dirs = _get_all_cpe_dirs(project_dir)
        if cpe_dirs:
            cpe_ids = [c[0] for c in cpe_dirs]
            project_info_parts.append(f"Devices: {', '.join(cpe_ids)}")
    
    project_info = "\n".join(project_info_parts)

    # Gather evidence from all pipeline stages
    evidence_sections = []

    # 1. Device info
    if cpe_id:
        device = _load_device_info(working_dir)
    else:
        device = ""
        cpe_dirs = _get_all_cpe_dirs(project_dir)
        for cpe_id_i, cpe_dir_i in cpe_dirs:
            dev_info = _load_device_info(cpe_dir_i)
            if dev_info and "No device info" not in dev_info:
                device += f"Device {cpe_id_i}:\n{dev_info}\n\n"
    
    if device and "No device info" not in device:
        evidence_sections.append(f"-- Device Info --\n{device}")

    # 2. Reboot timeline
    if cpe_id:
        reboots = _load_reboots(working_dir)
    else:
        reboots = _load_all_cpes_summary(project_dir)
    
    evidence_sections.append(f"-- Reboot Timeline / CPE Summary --\n{reboots}")

    # 3. Telemetry
    if cpe_id:
        telemetry = _load_telemetry_summary(working_dir)
    else:
        telemetry = _load_all_cpes_summary(project_dir)
    
    if telemetry and "No telemetry" not in telemetry:
        evidence_sections.append(f"-- Telemetry Status --\n{telemetry}")

    # 4. RAG - semantic search results matching user query
    rag = _load_rag_context(project_id, cpe_id, user_query)
    evidence_sections.append(f"-- Matching Log Patterns --\n{rag}")

    evidence = "\n\n".join(evidence_sections)

    # Truncate if too large (preserve beginning and end)
    if len(evidence) > MAX_CONTEXT_CHARS:
        half = MAX_CONTEXT_CHARS // 2
        evidence = evidence[:half] + "\n\n... [truncated for context window] ...\n\n" + evidence[-half:]

    return SYSTEM_PROMPT_TEMPLATE.format(
        project_info=project_info,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Conversation message assembly
# ---------------------------------------------------------------------------

def build_messages(system_prompt: str, history: list,
                   user_message: str) -> List[Dict[str, str]]:
    """
    Assemble the messages array for the LLM.

    Args:
        system_prompt: The evidence-grounded system prompt.
        history: List of ChatMessage ORM objects (role, content).
        user_message: The new user message.

    Returns:
        List of {role, content} dicts for the LLM API.
    """
    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history (limited window)
    recent = history[-MAX_HISTORY_MESSAGES:] if len(history) > MAX_HISTORY_MESSAGES else history
    for msg in recent:
        if msg.role in ("user", "assistant"):
            messages.append({"role": msg.role, "content": msg.content})

    # Add the new user message
    messages.append({"role": "user", "content": user_message})

    return messages


# ---------------------------------------------------------------------------
# OpenRouter chat completion with fallback (non-streaming request, chunked yield for SSE)
# ---------------------------------------------------------------------------

def _is_retryable_error(resp: Optional[requests.Response], exc: Optional[Exception]) -> bool:
    """True if we should try the next model (rate limit, gateway error, timeout, connection)."""
    if resp is not None and resp.status_code in RETRYABLE_STATUS_CODES:
        return True
    if exc is not None:
        if isinstance(exc, requests.exceptions.Timeout):
            return True
        if isinstance(exc, requests.exceptions.RequestException):
            return True
    return False


def chat_completion_stream(messages: List[Dict[str, str]],
                           user_id: int,
                           project_id: str,
                           cpe_id: Optional[str] = None,
                           temperature: float = 0.4,
                           max_tokens: int = 2048,
                           selected_files: Optional[List[str]] = None) -> Generator[str, None, None]:
    """
    Call LLM (OpenAI primary, OpenRouter fallback) and yield the response in chunks.
    
    OpenAI provider:
    - Supports function calling for tool access
    - Can analyze specific files based on user selection
    - Executes tools and integrates results
    
    OpenRouter fallback:
    - Uses free-tier models with retry logic
    - Evidence-based context only (no tool calling)
    
    Blocks until an inference slot is available (request queue).
    """
    _acquire_slot()
    try:
        # Try OpenAI first
        try:
            from api.openai_service import is_available as openai_available, chat_completion_stream as openai_stream
            
            if openai_available():
                logger.info(f"[LLM] Using OpenAI provider ({len(messages)} messages)")
                for chunk in openai_stream(
                    messages=messages,
                    user_id=user_id,
                    project_id=project_id,
                    cpe_id=cpe_id,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    selected_files=selected_files
                ):
                    yield chunk
                return
        except Exception as e:
            logger.warning(f"[LLM] OpenAI failed, falling back to OpenRouter: {e}")
        
        # Fallback to OpenRouter
        if not OPENROUTER_API_KEY:
            yield "\n\n**Error**: No LLM provider is configured. Please set OPENAI_API_KEY or OPENROUTER_API_KEY."
            return

        models = _get_openrouter_models()
        if not models:
            yield "\n\n**Error**: No OpenRouter models configured. Set OPENROUTER_MODELS."
            return

        logger.info(
            f"[LLM] OpenRouter fallback ({len(messages)} messages, "
            f"max_tokens={max_tokens}, temp={temperature}), models={models}"
        )
        url = f"{OPENROUTER_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        payload_base = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_status: Optional[int] = None
        last_error: Optional[Exception] = None

        for model_id in models:
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json={**payload_base, "model": model_id},
                    timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        logger.warning(f"[LLM] OpenRouter model {model_id}: no choices in response")
                        continue
                    content = choices[0].get("message", {}).get("content", "")
                    finish_reason = choices[0].get("finish_reason", "unknown")
                    usage = data.get("usage", {})
                    logger.info(
                        f"[LLM] OpenRouter model {model_id} responded: {len(content)} chars, "
                        f"finish_reason={finish_reason}, "
                        f"prompt_tokens={usage.get('prompt_tokens')}, "
                        f"completion_tokens={usage.get('completion_tokens')}"
                    )
                    if not content:
                        yield "\n\n*The AI model did not produce a response. Please try rephrasing your question.*"
                        return
                    # Yield response in line-based chunks for progressive SSE display
                    lines = content.split("\n")
                    for i, line in enumerate(lines):
                        if i < len(lines) - 1:
                            yield line + "\n"
                        else:
                            yield line
                    return
                # Non-retryable: do not try other models
                if resp.status_code not in RETRYABLE_STATUS_CODES:
                    logger.error(f"[LLM] OpenRouter model {model_id}: {resp.status_code} (non-retryable)")
                    try:
                        err_body = resp.json()
                        err_msg = err_body.get("error", {}).get("message", resp.text[:200])
                    except Exception:
                        err_msg = resp.text[:200] if resp.text else str(resp.status_code)
                    yield f"\n\n**Error**: OpenRouter returned {resp.status_code}. {err_msg}"
                    return
                last_status = resp.status_code
                logger.warning(f"[LLM] OpenRouter model {model_id}: {resp.status_code}, trying next model")
            except requests.exceptions.Timeout as e:
                last_error = e
                logger.warning(f"[LLM] OpenRouter model {model_id}: timeout, trying next model")
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(f"[LLM] OpenRouter model {model_id}: {e}, trying next model")

        # All models failed
        if last_status is not None:
            yield "\n\n**Error**: All AI models are temporarily unavailable (e.g. rate limited). Please try again later."
        elif last_error is not None:
            yield "\n\n**Error**: Could not reach OpenRouter. Please try again later."
        else:
            yield "\n\n**Error**: All AI models did not produce a response. Please try again later."

    finally:
        _release_slot()
