#!/usr/bin/env bash
# 运行后端自动化测试（不依赖真实 LLM API 的用例可离线跑）
set -euo pipefail
cd "$(dirname "$0")/../backend"
uv run pytest tests/ -v "$@"
