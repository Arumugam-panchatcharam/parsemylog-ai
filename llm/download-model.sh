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
huggingface-cli download \
    Qwen/Qwen2.5-Coder-7B-Instruct-GGUF \
    qwen2.5-coder-7b-instruct-q4_k_m.gguf \
    --local-dir "$MODEL_DIR"

echo "[llm-init] Download complete. Model saved to $MODEL_FILE"
