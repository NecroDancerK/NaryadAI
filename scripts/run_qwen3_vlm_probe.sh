#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
vlm_bind_host="${VLM_HOST:-127.0.0.1}"
export LLAMA_API_KEY="${VLM_API_KEY:-${LLAMA_API_KEY:-}}"
case "$vlm_bind_host" in
  127.0.0.1|localhost|::1) ;;
  *) if [[ -z "$LLAMA_API_KEY" ]]; then
       echo "Для запуска VLM вне loopback задайте VLM_API_KEY" >&2
       exit 1
     fi ;;
esac
exec llama-server \
  -m .local-models/vlm-qwen3/Qwen3VL-4B-Instruct-Q4_K_M.gguf \
  --mmproj .local-models/vlm-qwen3/mmproj-Qwen3VL-4B-Instruct-F16.gguf \
  --alias NaryadAI-Qwen3-VL-4B \
  --host "$vlm_bind_host" --port 8081 \
  --ctx-size 4096 --parallel 1 --n-gpu-layers 99 \
  --image-max-tokens 2048
