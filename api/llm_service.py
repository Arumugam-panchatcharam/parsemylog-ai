"""
LLM Service — Client wrapper, evidence-grounded prompt builder, request queue.
================================================================================

Connects to a local llama-cpp-python server (OpenAI-compatible API) and
builds evidence-grounded prompts from the parsed pipeline data.
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

LLM_URL = os.environ.get("LLM_URL", "http://localhost:8000/v1")
MAX_CONCURRENT = int(os.environ.get("LLM_MAX_CONCURRENT", "2"))
MAX_HISTORY_MESSAGES = 20  # Conversation history window
MAX_CONTEXT_CHARS = 6000   # Approx chars of log evidence injected

_semaphore = threading.Semaphore(MAX_CONCURRENT)
_queue_size = 0
_queue_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Health / availability
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """Check if the LLM server is reachable and has a model loaded."""
    try:
        resp = requests.get(f"{LLM_URL}/models", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def get_model_info() -> Optional[Dict[str, Any]]:
    """Return model metadata from the LLM server."""
    try:
        resp = requests.get(f"{LLM_URL}/models", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", [])
            if models:
                return models[0]
        return None
    except Exception:
        return None


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
        reboots = json.loads(cache.read_text(encoding="utf-8"))
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
    """Load telemetry summary from cache."""
    cache = project_dir / "telemetry" / "response.json"
    if not cache.exists():
        return "No telemetry data available."
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        if not summary:
            return "Telemetry parsed but no summary available."

        lines = []
        device = summary.get("device_info", {})
        if device:
            lines.append("Device Info:")
            for k, v in device.items():
                lines.append(f"  {k}: {v}")

        status = summary.get("status_labels", [])
        if status:
            lines.append("\nStatus Labels:")
            for s in status[:15]:
                lines.append(f"  {s.get('group', '?')}/{s.get('label', '?')}: {s.get('value', 'N/A')}")

        return "\n".join(lines) if lines else "Telemetry data present but no summary fields."
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


def _load_rag_context(project_id: str, cpe_id: Optional[str],
                      query: str, top_k: int = 5) -> str:
    """Retrieve semantic search results from Qdrant for the user query."""
    try:
        from logai.utils.constants import QDRANT_URL
        from qdrant_client import QdrantClient
        from api.app import get_embedding_model

        collection = f"project_{project_id}"
        if cpe_id:
            collection = f"project_{project_id}_cpe_{cpe_id}"

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


def build_system_prompt(project_name: str, project_dir: Path,
                        project_id: str, cpe_id: Optional[str],
                        user_query: str) -> str:
    """
    Build a grounded system prompt with all available pipeline evidence.
    """
    # Project info section
    project_info_parts = [f"Project: {project_name}"]
    if cpe_id:
        project_info_parts.append(f"CPE: {cpe_id}")
    project_info = "\n".join(project_info_parts)

    # Gather evidence from all pipeline stages
    evidence_sections = []

    # 1. Device info
    device = _load_device_info(project_dir)
    if device and "No device info" not in device:
        evidence_sections.append(f"-- Device Info --\n{device}")

    # 2. Reboot timeline
    reboots = _load_reboots(project_dir)
    evidence_sections.append(f"-- Reboot Timeline --\n{reboots}")

    # 3. Telemetry
    telemetry = _load_telemetry_summary(project_dir)
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
# Chat completion (non-streaming to LLM, chunked yield for SSE)
# ---------------------------------------------------------------------------

def chat_completion_stream(messages: List[Dict[str, str]],
                           temperature: float = 0.4,
                           max_tokens: int = 2048) -> Generator[str, None, None]:
    """
    Call the LLM server and yield the response in chunks for SSE delivery.

    Uses a non-streaming request to the LLM to avoid connection drops
    caused by Werkzeug/WSGI closing the chained streaming pipeline.
    The complete response is fetched first, then yielded in line-based
    chunks to provide a progressive display experience.

    Blocks until an inference slot is available (request queue).
    """
    _acquire_slot()
    try:
        logger.info(f"[LLM] Sending non-streaming request ({len(messages)} messages, "
                     f"max_tokens={max_tokens}, temp={temperature})")

        resp = requests.post(
            f"{LLM_URL}/chat/completions",
            json={
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            logger.warning("[LLM] No choices in response")
            yield "\n\n*The AI model did not produce a response. Please try rephrasing your question.*"
            return

        content = choices[0].get("message", {}).get("content", "")
        finish_reason = choices[0].get("finish_reason", "unknown")
        usage = data.get("usage", {})

        # #region agent log — H11: log non-streaming response details
        import time as _t
        _dbg = json.dumps({"location":"llm_service.py:360","message":"llm_complete_response","data":{"content_len":len(content),"finish_reason":finish_reason,"prompt_tokens":usage.get("prompt_tokens"),"completion_tokens":usage.get("completion_tokens"),"content_preview":content[:200] if content else ""},"timestamp":int(_t.time()*1000),"hypothesisId":"H11"})
        with open("/Users/parumugam/Documents/Repos/parsemylog-ai/.cursor/debug.log","a") as _f: _f.write(_dbg+"\n")
        # #endregion

        logger.info(f"[LLM] Response: {len(content)} chars, "
                     f"finish_reason={finish_reason}, "
                     f"prompt_tokens={usage.get('prompt_tokens')}, "
                     f"completion_tokens={usage.get('completion_tokens')}")

        if not content:
            yield "\n\n*The AI model did not produce a response. Please try rephrasing your question.*"
            return

        # Yield response in line-based chunks for progressive SSE display
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if i < len(lines) - 1:
                yield line + '\n'
            else:
                yield line

    except requests.exceptions.Timeout:
        logger.error("[LLM] Request timed out (180s)")
        yield "\n\n**Error**: The AI model took too long to respond. Please try a simpler question."
    except requests.exceptions.RequestException as e:
        logger.error(f"[LLM] Request error: {e}")
        yield f"\n\n**Error**: Could not reach the LLM server. Please try again later."
    finally:
        _release_slot()
