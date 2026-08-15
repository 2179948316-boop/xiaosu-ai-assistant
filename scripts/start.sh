#!/usr/bin/env bash
# 小苏 AI 助手 - 一键启动脚本
# 用法:
#   ./scripts/start.sh        # Docker 方式启动全套（MySQL + Redis + 后端 + 前端）
#   ./scripts/start.sh dev    # 本地开发模式（需要本机已有 MySQL/Redis）
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f backend/.env ]]; then
  echo "❌ 缺少 backend/.env，请先复制模板并填写配置:"
  echo "   cp backend/.env.example backend/.env"
  exit 1
fi

MODE="${1:-docker}"

if [[ "$MODE" == "docker" ]]; then
  echo "🐳 Docker 模式启动中..."
  docker compose up -d --build
  echo "✅ 启动完成: 前端 http://localhost  后端 http://localhost:8000/docs"
else
  echo "🛠  本地开发模式启动中..."
  # 后端
  (cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) &
  BACKEND_PID=$!
  # 前端
  (cd frontend && pnpm dev) &
  FRONTEND_PID=$!
  BOT_PID=""
  # 飞书机器人（配置了凭据才启动）
  if grep -qE '^FEISHU_APP_ID=.+' backend/.env; then
    (cd backend && sleep 3 && uv run python bot_service.py) &
    BOT_PID=$!
    echo "🤖 飞书机器人已启动"
  else
    echo "ℹ️  未配置 FEISHU_APP_ID，跳过飞书机器人"
  fi
  trap "kill $BACKEND_PID $FRONTEND_PID $BOT_PID 2>/dev/null || true" EXIT
  echo "✅ 后端 http://localhost:8000/docs  前端 http://localhost:5173"
  wait
fi
