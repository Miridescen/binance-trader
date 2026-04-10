#!/bin/bash
# 注册 binance-btc-trend systemd 服务
# 用法：sudo bash start_btc_trend.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3)"
USER="$(whoami)"
SERVICE_NAME="binance-btc-trend"

echo "======================================"
echo " BTC 趋势信号服务安装"
echo "======================================"
echo " 项目目录：$PROJECT_DIR"
echo " Python：  $PYTHON"
echo " 用户：    $USER"
echo ""

# 创建日志目录
mkdir -p "${PROJECT_DIR}/logs"

# 写入 service 文件
cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=BTC 趋势信号虚拟盘（每小时检查 SMA200+RSI 信号）
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON} ${PROJECT_DIR}/btc_trend.py
Restart=always
RestartSec=30
StartLimitIntervalSec=0

# 崩溃日志
StandardOutput=append:${PROJECT_DIR}/logs/${SERVICE_NAME}.log
StandardError=append:${PROJECT_DIR}/logs/${SERVICE_NAME}.log

[Install]
WantedBy=multi-user.target
EOF

echo "已写入 /etc/systemd/system/${SERVICE_NAME}.service"

# 重载并启用
systemctl daemon-reload
systemctl enable  ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}
sleep 2

status=$(systemctl is-active ${SERVICE_NAME})
if [ "$status" = "active" ]; then
    echo "✅ ${SERVICE_NAME} 启动成功"
else
    echo "❌ ${SERVICE_NAME} 启动异常，请运行：journalctl -u ${SERVICE_NAME} -n 30"
fi

echo ""
echo "常用命令："
echo " 查看状态：  systemctl status ${SERVICE_NAME}"
echo " 查看日志：  tail -f ${PROJECT_DIR}/logs/${SERVICE_NAME}.log"
echo " 重启服务：  systemctl restart ${SERVICE_NAME}"
echo " 停止服务：  systemctl stop ${SERVICE_NAME}"
