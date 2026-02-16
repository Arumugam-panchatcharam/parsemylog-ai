#!/bin/bash
# download-model.sh — Idempotent model downloader for the LLM init container.
# Downloads the GGUF model into a persistent Docker volume on first run.

set -e

MODEL_DIR="/models"
MODEL_FILE="$MODEL_DIR/qwen2.5-coder-7b-instruct-q4_k_m.gguf"

if [ -f "$MODEL_FILE" ]; then
    echo "[llm-init] Model already exists at $MODEL_FILE — skipping download."
    exit 0
fi

mkdir -p "$MODEL_DIR"

echo "[llm-init] Downloading Qwen2.5-Coder-7B-Instruct (Q4_K_M, ~4.5 GB)..."
python -c "
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id='Qwen/Qwen2.5-Coder-7B-Instruct-GGUF',
    filename='qwen2.5-coder-7b-instruct-q4_k_m.gguf',
    local_dir='$MODEL_DIR',
)
print('[llm-init] Download complete.')
"

echo "[llm-init] Model saved to $MODEL_FILE"
