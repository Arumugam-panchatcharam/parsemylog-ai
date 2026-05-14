from celery import Celery
import logging
import os
import platform
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

# Ensure project root is on sys.path so forked workers can import logai, api, etc.
_PROJECT_ROOT_PATH = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = str(_PROJECT_ROOT_PATH)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Celery worker is a separate OS process from Flask; Docker Compose passes `.env` as env-file, but locally
# you only inherit variables you `export` unless we load `.env` here (e.g. CPE_REMOTE_LOG_CDN_BASE).
_dotenv_file = _PROJECT_ROOT_PATH / ".env"
if _dotenv_file.is_file():
    try:
        from dotenv import load_dotenv

        load_dotenv(_dotenv_file, override=False)
    except ImportError:
        pass


def _celery_running_inside_container() -> bool:
    """Docker and many runtimes create ``/.dockerenv`` in the container root."""
    try:
        return Path("/.dockerenv").is_file()
    except OSError:
        return False


def _rewrite_qdrant_url_for_host_workers() -> None:
    """
    Compose often sets ``QDRANT_URL=http://qdrant:6333``. Celery workers started on the
    host cannot resolve Docker service hostnames, which yields
    ``[Errno 8] nodename nor servname provided, or not known`` when indexing.

    Rewrite ``qdrant`` → ``127.0.0.1`` only when not inside a container. In Docker-sidecar
    workers, hostname ``qdrant`` stays valid; set ``KEEP_DOCKER_QDRANT_HOST=1`` to force
    that behavior if ``/.dockerenv`` is absent (e.g. some Podman setups).
    """
    if os.environ.get("KEEP_DOCKER_QDRANT_HOST", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return
    if _celery_running_inside_container():
        return
    raw = (os.environ.get("QDRANT_URL") or "").strip()
    if not raw:
        os.environ.setdefault("QDRANT_URL", "http://127.0.0.1:6333")
        return
    parsed = urlparse(raw)
    if (parsed.scheme or "").lower() not in ("http", "https"):
        return
    if (parsed.hostname or "").lower() != "qdrant":
        return
    port = parsed.port if parsed.port is not None else 6333
    new_netloc = f"127.0.0.1:{port}"
    new_parsed = parsed._replace(netloc=new_netloc)
    new_url = urlunparse(new_parsed)
    logger.info(
        "Celery on host: QDRANT_URL uses docker hostname "
        "\"qdrant\" (not resolvable here); using %s instead. "
        "Set KEEP_DOCKER_QDRANT_HOST=1 inside containers if needed.",
        new_url,
    )
    os.environ["QDRANT_URL"] = new_url


_rewrite_qdrant_url_for_host_workers()


def _use_solo_worker_pool_on_macos() -> bool:
    """
    Celery's default prefork pool forks worker processes before heavy ML libs load.
    On macOS, PyTorch / tokenizers in a forked child can crash with SIGSEGV
    during SentenceTransformer.encode. Use the threads-based 'solo' pool locally.

    Linux/Docker workers keep prefork (better isolation). Opt out with
    CELERY_USE_PREFORK_ON_MACOS=1 if you need prefork on Darwin.
    """
    if platform.system() != "Darwin":
        return False
    flag = (os.environ.get("CELERY_USE_PREFORK_ON_MACOS") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return False
    return True


# Hugging Face tokenizers warn and can misbehave across fork / extra threads in workers
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# CRITICAL: Disable PyTorch MPS (Metal Performance Shaders) to prevent SIGABRT in forked processes on macOS
# These MUST be set BEFORE any PyTorch/transformers imports
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"

# Force CPU-only mode for all ML frameworks
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["MPS_DISABLE"] = "1"

# Set PyTorch to use CPU only (critical for avoiding MPS in forked processes)
os.environ["PYTORCH_DEVICE"] = "cpu"

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery = Celery(
    "tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["services.celery_worker.tasks"]
)

_celery_settings = {
    "task_serializer": "json",
    "accept_content": ["json"],
    "result_serializer": "json",
    "timezone": "UTC",
    "enable_utc": True,
}
if _use_solo_worker_pool_on_macos():
    _celery_settings["worker_pool"] = "solo"
    logger.info(
        "Celery: worker_pool=solo on macOS (avoids ML stack crashes in prefork workers). "
        "Set CELERY_USE_PREFORK_ON_MACOS=1 to use the default pool."
    )

celery.conf.update(**_celery_settings)