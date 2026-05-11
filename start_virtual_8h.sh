#!/bin/bash
# 注册 binance-virtual-8h systemd 服务
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3)"
USER="$(whoami)"
SERVICE_NAME="binance-virtual-8h"

echo "======================================"
echo " 8h 周期虚拟盘服务安装"
echo "======================================"
echo " 项目目录：$PROJECT_DIR"

mkdir -p "${PROJECT_DIR}/logs"

cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=8h 周期虚拟盘（00:30 / 08:30 / 16:30 开仓，组内 +10u 提前平仓）
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON} ${PROJECT_DIR}/virtual_trade_8h.py
Restart=always
RestartSec=30
StartLimitIntervalSec=0

StandardOutput=append:${PROJECT_DIR}/logs/${SERVICE_NAME}.log
StandardError=append:${PROJECT_DIR}/logs/${SERVICE_NAME}.log

[Install]
WantedBy=multi-user.target
EOF

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
