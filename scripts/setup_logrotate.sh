#!/bin/bash
# 一次性安装 logrotate 配置到 /etc/logrotate.d/binance-trader
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${PROJECT_DIR}/logrotate.binance-trader.conf"
DST="/etc/logrotate.d/binance-trader"

if [ ! -f "$SRC" ]; then
    echo "❌ 找不到模板 $SRC"
    exit 1
fi

cp "$SRC" "$DST"
chmod 644 "$DST"
chown root:root "$DST"

echo "✅ 安装完成：$DST"
echo
echo "=== 当前 logrotate 配置 ==="
cat "$DST"
echo
echo "=== 验证 ==="
logrotate -d "$DST" 2>&1 | tail -20
echo
echo "=== 立即试运行（不真正轮转）==="
logrotate --debug "$DST" 2>&1 | head -10
echo
echo "logrotate 系统默认每天 6:25 (cron.daily) 自动执行。"
echo "如需立即轮转：logrotate --force $DST"
