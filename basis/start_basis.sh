#!/bin/bash
# 注册 binance-basis-monitor systemd 服务（基差套利 Phase 1 数据采集）
# 用法：sudo bash basis/start_basis.sh
set -e

BASIS_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${BASIS_DIR}/.." && pwd)"
PYTHON="$(which python3)"
USER="$(whoami)"
SERVICE_NAME="binance-basis-monitor"

echo "======================================"
echo " 基差套利 Phase 1 数据采集服务安装"
echo "======================================"
echo " basis 目录：$BASIS_DIR"
echo " 项目根：    $PROJECT_DIR"

mkdir -p "${PROJECT_DIR}/logs"

cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=基差套利 Phase 1 数据采集（每 15 分钟拉 BTC/ETH 现货+季度合约价）
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${BASIS_DIR}
ExecStart=${PYTHON} ${BASIS_DIR}/monitor.py
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

echo ""
echo "常用命令："
echo " 查看状态：  systemctl status ${SERVICE_NAME}"
echo " 查看日志：  tail -f ${PROJECT_DIR}/logs/${SERVICE_NAME}.log"
echo " 重启服务：  systemctl restart ${SERVICE_NAME}"
echo " 停止服务：  systemctl stop ${SERVICE_NAME}"
echo " 查询数据：  sqlite3 ${BASIS_DIR}/basis.db 'SELECT * FROM basis_snapshot LIMIT 10'"
