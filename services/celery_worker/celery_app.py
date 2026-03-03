from celery import Celery
import os

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