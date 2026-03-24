"""
OpenAI Service — OpenAI client with function calling support
=============================================================

Uses OpenAI's API with function calling to access log analysis tools.
Integrates with existing log analysis pipeline (info_extractor, telemetry,
pcap analyzer, etc.) and allows the AI to call these tools based on context.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from openai import AzureOpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENAI_API_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()
OPENAI_ENDPOINT = os.environ.get("OPENAI_BASE_URL", "https://home-openai-v1.openai.azure.com").strip().rstrip('/')
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1")
OPENAI_API_VERSION = os.environ.get("OPENAI_API_VERSION", "2024-08-01-preview")
OPENAI_MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "4096"))

# Initialize Azure OpenAI client
_client: Optional[AzureOpenAI] = None

def _get_client() -> AzureOpenAI:
    """Get or initialize the Azure OpenAI client."""
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not configured")
        
        logger.info(f"[Azure OpenAI] Initializing client")
        logger.info(f"[Azure OpenAI] Endpoint: {OPENAI_ENDPOINT}")
        logger.info(f"[Azure OpenAI] Deployment: {OPENAI_MODEL}")
        logger.info(f"[Azure OpenAI] API Version: {OPENAI_API_VERSION}")
        
        _client = AzureOpenAI(
            api_key=OPENAI_API_KEY,
            azure_endpoint=OPENAI_ENDPOINT,
            api_version=OPENAI_API_VERSION
        )
    return _client


def is_available() -> bool:
    """Check if OpenAI is available (API key is set)."""
    return bool(OPENAI_API_KEY)


def get_model_info() -> Optional[Dict[str, Any]]:
    """Return provider/model info for the UI."""
    if not OPENAI_API_KEY:
        return None
    return {
        "id": OPENAI_MODEL,
        "object": "provider",
        "provider": "OpenAI",
    }


# ---------------------------------------------------------------------------
# Function tool definitions
# ---------------------------------------------------------------------------

def get_function_tools() -> List[Dict[str, Any]]:
    """
    Define OpenAI function tools that map to our log analysis capabilities.
    
    These tools allow the AI to:
    - Extract device info from logs
    - Parse telemetry data
    - Analyze telemetry CSV files
    - Analyze PCAP files
    - Search log patterns
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "extract_device_info",
                "description": "Extract device information from log files including firmware version, device model, serial number, MAC address, and reboot history. Useful for understanding device configuration and identity.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_dir": {
                            "type": "string",
                            "description": "Path to the project directory containing log files"
                        }
                    },
                    "required": ["project_dir"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "parse_telemetry",
                "description": "Parse telemetry logs (RDKB_Telemetry.txt, xOpsAnalytics.log, etc.) to extract status labels, performance metrics, and diagnostic information. Returns structured telemetry data including device status, network stats, and system health metrics.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_dir": {
                            "type": "string",
                            "description": "Path to the project directory containing telemetry logs"
                        },
                        "force": {
                            "type": "boolean",
                            "description": "Force re-parsing even if cached data exists",
                            "default": False
                        }
                    },
                    "required": ["project_dir"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_telemetry_csv",
                "description": "Analyze telemetry CSV files to extract time-series metrics, trends, and statistics. Returns data points with timestamps, metric values, and statistical summaries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Name of the telemetry CSV file to analyze"
                        },
                        "metric_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of metric names to extract (e.g., ['CPU_Usage', 'Memory_Free', 'Temperature'])"
                        },
                        "max_points": {
                            "type": "integer",
                            "description": "Maximum number of data points to return",
                            "default": 100
                        }
                    },
                    "required": ["filename"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_pcap",
                "description": "Analyze PCAP network capture files to extract WiFi statistics, client information, AP details, and network protocols. Returns network analysis including connected clients, signal strength, frame types, and protocol distribution.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Name of the PCAP file to analyze"
                        },
                        "analysis_type": {
                            "type": "string",
                            "enum": ["overview", "client_detail", "ap_detail", "1905_protocol"],
                            "description": "Type of analysis to perform",
                            "default": "overview"
                        },
                        "mac_address": {
                            "type": "string",
                            "description": "MAC address for client or AP detail analysis (required for client_detail and ap_detail)"
                        }
                    },
                    "required": ["filename", "analysis_type"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_log_patterns",
                "description": "Search for specific patterns in indexed log files using semantic search. Returns matching log templates with occurrence counts and sample entries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query or pattern to find in logs"
                        },
                        "project_id": {
                            "type": "string",
                            "description": "Project ID to search within"
                        },
                        "cpe_id": {
                            "type": "string",
                            "description": "Optional CPE ID to narrow search scope"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of top results to return",
                            "default": 5
                        }
                    },
                    "required": ["query", "project_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_reboot_timeline",
                "description": "Get chronological list of device reboots with timestamps and reasons. Useful for troubleshooting stability issues and understanding device history.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_dir": {
                            "type": "string",
                            "description": "Path to the project directory"
                        },
                        "max_reboots": {
                            "type": "integer",
                            "description": "Maximum number of reboots to return",
                            "default": 20
                        }
                    },
                    "required": ["project_dir"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_available_files",
                "description": "List all available files in the project that can be analyzed. Returns categorized lists of log files, telemetry CSVs, and PCAP files with metadata.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_dir": {
                            "type": "string",
                            "description": "Path to the project directory"
                        },
                        "file_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["logs", "csv", "pcap", "all"]
                            },
                            "description": "Types of files to list",
                            "default": ["all"]
                        }
                    },
                    "required": ["project_dir"]
                }
            }
        }
    ]


# ---------------------------------------------------------------------------
# Function tool implementations
# ---------------------------------------------------------------------------

def execute_function(
    name: str,
    arguments: Dict[str, Any],
    user_id: int,
    project_id: str,
    cpe_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a function tool call and return the result.
    
    Args:
        name: Function name
        arguments: Function arguments
        user_id: User ID for file access
        project_id: Project ID
        cpe_id: Optional CPE ID
        
    Returns:
        Result dictionary with status and data/error
    """
    try:
        if name == "extract_device_info":
            return _execute_extract_device_info(arguments, user_id, project_id, cpe_id)
        elif name == "parse_telemetry":
            return _execute_parse_telemetry(arguments, user_id, project_id, cpe_id)
        elif name == "analyze_telemetry_csv":
            return _execute_analyze_telemetry_csv(arguments, user_id)
        elif name == "analyze_pcap":
            return _execute_analyze_pcap(arguments, user_id)
        elif name == "search_log_patterns":
            return _execute_search_log_patterns(arguments, project_id, cpe_id)
        elif name == "get_reboot_timeline":
            return _execute_get_reboot_timeline(arguments, user_id, project_id, cpe_id)
        elif name == "list_available_files":
            return _execute_list_available_files(arguments, user_id, project_id, cpe_id)
        else:
            return {"status": "error", "error": f"Unknown function: {name}"}
    except Exception as e:
        logger.exception(f"Error executing function {name}")
        return {"status": "error", "error": str(e)}


def _execute_extract_device_info(args: Dict, user_id: int, project_id: str, cpe_id: Optional[str]) -> Dict:
    """Execute device info extraction."""
    from logai.info_extractor import find_and_parse_version_txt, find_and_build_fallback_device_info
    from logai.utils.constants import UPLOAD_DIRECTORY
    
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir
    
    # Try version.txt first
    version_info = find_and_parse_version_txt(project_dir)
    if version_info:
        return {"status": "success", "data": version_info}
    
    # Fallback to device info
    device_info = find_and_build_fallback_device_info(project_dir)
    if device_info:
        return {"status": "success", "data": device_info}
    
    return {"status": "error", "error": "No device info found"}


def _execute_parse_telemetry(args: Dict, user_id: int, project_id: str, cpe_id: Optional[str]) -> Dict:
    """Execute telemetry parsing."""
    from logai.utils.constants import UPLOAD_DIRECTORY
    
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir
    
    # Check for cached telemetry response
    response_path = project_dir / "telemetry" / "response.json"
    if response_path.exists():
        try:
            data = json.loads(response_path.read_text(encoding="utf-8"))
            return {"status": "success", "data": data.get("summary", {})}
        except Exception as e:
            logger.warning(f"Failed to read telemetry cache: {e}")
    
    return {"status": "error", "error": "Telemetry data not available. Please parse telemetry first."}


def _execute_analyze_telemetry_csv(args: Dict, user_id: int) -> Dict:
    """Execute telemetry CSV analysis."""
    filename = args.get("filename", "")
    if not filename:
        return {"status": "error", "error": "filename is required"}
    
    # This would integrate with the telemetry_csv module
    # For now, return a placeholder
    return {"status": "error", "error": "Telemetry CSV analysis not yet implemented in tool executor"}


def _execute_analyze_pcap(args: Dict, user_id: int) -> Dict:
    """Execute PCAP analysis."""
    filename = args.get("filename", "")
    if not filename:
        return {"status": "error", "error": "filename is required"}
    
    # This would integrate with the pcap module
    # For now, return a placeholder
    return {"status": "error", "error": "PCAP analysis not yet implemented in tool executor"}


def _execute_search_log_patterns(args: Dict, project_id: str, cpe_id: Optional[str]) -> Dict:
    """Execute log pattern search using RAG."""
    from logai.utils.constants import QDRANT_URL
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    
    query = args.get("query", "")
    top_k = args.get("top_k", 5)
    
    if not query:
        return {"status": "error", "error": "query is required"}
    
    try:
        from api.app import get_embedding_model
        
        collection = f"project_{project_id}"
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
            return {"status": "error", "error": "No indexed log data available"}
        
        model = get_embedding_model()
        query_vector = model.encode([query], normalize_embeddings=True)[0].tolist()
        
        results = client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
        )
        
        points = results.points if hasattr(results, "points") else []
        matches = []
        for r in points:
            payload = r.payload or {}
            matches.append({
                "template": payload.get("template", "N/A"),
                "count": payload.get("count", 0),
                "sample": payload.get("sample", ""),
                "source_file": payload.get("source_file", ""),
                "score": r.score if hasattr(r, "score") else 0
            })
        
        return {"status": "success", "data": {"matches": matches, "total": len(matches)}}
    except Exception as e:
        logger.exception("Error in log pattern search")
        return {"status": "error", "error": str(e)}


def _execute_get_reboot_timeline(args: Dict, user_id: int, project_id: str, cpe_id: Optional[str]) -> Dict:
    """Execute reboot timeline retrieval."""
    from logai.utils.constants import UPLOAD_DIRECTORY
    
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir
    
    cache_path = project_dir / ".reboots_cache.json"
    max_reboots = args.get("max_reboots", 20)
    
    if not cache_path.exists():
        return {"status": "error", "error": "No reboot data available"}
    
    try:
        reboots = json.loads(cache_path.read_text(encoding="utf-8"))
        limited_reboots = reboots[:max_reboots] if len(reboots) > max_reboots else reboots
        return {
            "status": "success",
            "data": {
                "reboots": limited_reboots,
                "total": len(reboots),
                "shown": len(limited_reboots)
            }
        }
    except Exception as e:
        logger.exception("Error reading reboot timeline")
        return {"status": "error", "error": str(e)}


def _execute_list_available_files(args: Dict, user_id: int, project_id: str, cpe_id: Optional[str]) -> Dict:
    """Execute file listing."""
    from logai.utils.constants import UPLOAD_DIRECTORY
    
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir
    
    file_types = args.get("file_types", ["all"])
    
    files = {
        "logs": [],
        "csv": [],
        "pcap": []
    }
    
    if not project_dir.exists():
        return {"status": "error", "error": "Project directory not found"}
    
    try:
        # List log files
        if "all" in file_types or "logs" in file_types:
            for log_file in project_dir.glob("**/*.txt"):
                if log_file.is_file():
                    files["logs"].append({
                        "name": log_file.name,
                        "path": str(log_file.relative_to(project_dir)),
                        "size": log_file.stat().st_size
                    })
        
        # List CSV files
        if "all" in file_types or "csv" in file_types:
            csv_dir = project_dir / "telemetry_csv"
            if csv_dir.exists():
                for csv_file in csv_dir.glob("*.csv"):
                    files["csv"].append({
                        "name": csv_file.name,
                        "size": csv_file.stat().st_size
                    })
        
        # List PCAP files
        if "all" in file_types or "pcap" in file_types:
            pcap_dir = project_dir / "pcap"
            if pcap_dir.exists():
                for pcap_file in pcap_dir.glob("*"):
                    if pcap_file.suffix in [".pcap", ".pcapng", ".cap"]:
                        files["pcap"].append({
                            "name": pcap_file.name,
                            "size": pcap_file.stat().st_size
                        })
        
        return {"status": "success", "data": files}
    except Exception as e:
        logger.exception("Error listing files")
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# OpenAI chat completion with function calling
# ---------------------------------------------------------------------------

def chat_completion_stream(
    messages: List[Dict[str, str]],
    user_id: int,
    project_id: str,
    cpe_id: Optional[str] = None,
    temperature: float = 0.4,
    max_tokens: int = OPENAI_MAX_TOKENS,
    selected_files: Optional[List[str]] = None
) -> Generator[str, None, None]:
    """
    Call OpenAI with function calling support and yield the response in chunks.
    
    Handles function calls by executing the requested tools and feeding results
    back to the model for final response generation.
    
    Args:
        messages: Conversation messages
        user_id: User ID for tool execution
        project_id: Project ID
        cpe_id: Optional CPE ID
        temperature: Sampling temperature
        max_tokens: Max tokens to generate
        selected_files: Optional list of file contexts user selected
        
    Yields:
        Response chunks for SSE delivery
    """
    if not OPENAI_API_KEY:
        yield "\n\n**Error**: OpenAI API key is not configured. Please set OPENAI_API_KEY."
        return
    
    try:
        client = _get_client()
        
        # Add file context to system message if provided
        if selected_files:
            file_context = "\n\n=== SELECTED FILES FOR ANALYSIS ===\n"
            file_context += "\n".join(f"- {f}" for f in selected_files)
            file_context += "\n\nThe user wants you to analyze these specific files. Use the appropriate tools to extract information from them."
            
            # Prepend to system message
            if messages and messages[0]["role"] == "system":
                messages[0]["content"] += file_context
        
        logger.info(f"[OpenAI] Request with {len(messages)} messages, temp={temperature}, max_tokens={max_tokens}")
        
        # Initial request with function tools
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=get_function_tools(),
            tool_choice="auto"
        )
        
        # Process response and handle function calls
        max_iterations = 5  # Prevent infinite loops
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            choice = response.choices[0]
            message = choice.message
            
            # Check if model wants to call functions
            if message.tool_calls:
                logger.info(f"[OpenAI] Model requested {len(message.tool_calls)} tool calls")
                
                # Add assistant message to conversation
                messages.append({
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in message.tool_calls
                    ]
                })
                
                # Execute each tool call
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    logger.info(f"[OpenAI] Executing tool: {function_name} with args: {function_args}")
                    
                    # Execute the function
                    result = execute_function(
                        function_name,
                        function_args,
                        user_id,
                        project_id,
                        cpe_id
                    )
                    
                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result)
                    })
                
                # Make another request with the tool results
                response = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=get_function_tools(),
                    tool_choice="auto"
                )
            else:
                # No more function calls, yield the final response
                content = message.content or ""
                
                if not content:
                    yield "\n\n*The AI model did not produce a response. Please try rephrasing your question.*"
                    return
                
                logger.info(f"[OpenAI] Final response: {len(content)} chars, finish_reason={choice.finish_reason}")
                
                # Yield response in line-based chunks for progressive SSE display
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if i < len(lines) - 1:
                        yield line + "\n"
                    else:
                        yield line
                return
        
        # Max iterations reached
        yield "\n\n**Error**: Maximum function call iterations reached. Please simplify your question."
        
    except Exception as e:
        logger.exception("[OpenAI] Error in chat completion")
        yield f"\n\n**Error**: {str(e)}"
