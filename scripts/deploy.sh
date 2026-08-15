#!/usr/bin/env bash
# 部署到服务器（增量同步变更文件 + 重建容器）
# 用法: ./scripts/deploy.sh <user@host> [remote_dir]
set -euo pipefail
REMOTE="${1:?用法: ./scripts/deploy.sh user@host [remote_dir]}"
REMOTE_DIR="${2:-/root/xiaosu}"

echo "📦 同步代码到 $REMOTE:$REMOTE_DIR ..."
rsync -avz --delete \
  --exclude '.venv' --exclude 'node_modules' --exclude '__pycache__' \
  --exclude '.env' --exclude 'data' --exclude 'logs' --exclude '.git' \
  ./ "$REMOTE:$REMOTE_DIR/"

echo "🔄 远程重建容器..."
ssh "$REMOTE" "cd $REMOTE_DIR && docker compose up -d --build backend frontend"
echo "✅ 部署完成"
