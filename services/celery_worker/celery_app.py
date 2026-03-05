from celery import Celery
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so forked workers can import logai, api, etc.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

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

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)