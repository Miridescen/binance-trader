#!/bin/bash
# 重新构建前端并重载 nginx
set -e
cd "$(dirname "$0")/frontend"
echo "拉取最新代码..."
git -C .. pull
echo "构建前端..."
npm run build
echo "重载 nginx..."
systemctl reload nginx
echo "✅ 前端已更新"
