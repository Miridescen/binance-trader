#!/bin/bash
# 日常更新脚本：拉取最新代码 → 构建前端 → 刷新服务
# 用法：bash update.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="/var/www/binance-trader"

echo "======================================"
echo " Binance Trader 更新脚本"
echo "======================================"

# ── 拉取最新代码 ───────────────────────────────────────

echo "▶ 拉取最新代码..."
cd "${PROJECT_DIR}"
git pull
echo ""

# ── 安装 Python 依赖（如有新增） ────────────────────────

pip3 install -r requirements.txt -q
echo "✅ Python 依赖已更新"

# ── 构建前端 ───────────────────────────────────────────

echo "▶ 构建前端..."
cd "${PROJECT_DIR}/frontend"
npm install -q
npm run build -q
echo "✅ 前端构建完成"

# ── 更新 nginx 静态文件 ────────────────────────────────

echo "▶ 更新静态文件..."
mkdir -p "${WEB_DIR}"
cp -r dist/* "${WEB_DIR}/"
echo "✅ 静态文件已更新至 ${WEB_DIR}"

# ── 重启 API 服务 ──────────────────────────────────────

cd "${PROJECT_DIR}"
systemctl restart binance-api
echo "✅ binance-api 已重启"

echo ""
echo "======================================"
echo " 更新完成！访问 http://$(curl -s ifconfig.me 2>/dev/null || echo '<服务器IP>'):8080"
echo "======================================"
