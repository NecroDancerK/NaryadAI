#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
image_tokens="${VLM_IMAGE_MAX_TOKENS:-1024}"
if ! [[ "$image_tokens" =~ ^[0-9]+$ ]] || (( image_tokens < 1024 || image_tokens > 4096 )); then
  echo 'VLM_IMAGE_MAX_TOKENS must be between 1024 and 4096' >&2
  exit 2
fi
exec llama-server \
  -m .local-models/vlm/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf \
  --mmproj .local-models/vlm/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf \
  --host 127.0.0.1 --port 8081 \
  --ctx-size 4096 --parallel 1 --n-gpu-layers 99 \
  --image-max-tokens "$image_tokens"
