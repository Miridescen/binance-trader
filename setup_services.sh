#!/bin/bash
# 一键注册 binance-trader 的两个 systemd 服务
# 用法：bash setup_services.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3)"
USER="$(whoami)"

echo "======================================"
echo " Binance Trader 服务安装脚本"
echo "======================================"
echo " 项目目录：$PROJECT_DIR"
echo " Python：  $PYTHON"
echo " 用户：    $USER"
echo ""

# ── 生成 service 文件 ──────────────────────────────────

write_service() {
    local name=$1
    local script=$2
    local desc=$3

    cat > /etc/systemd/system/${name}.service <<EOF
[Unit]
Description=${desc}
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON} ${PROJECT_DIR}/${script}
Restart=always
RestartSec=10
StartLimitIntervalSec=0

# 崩溃日志
StandardOutput=append:${PROJECT_DIR}/logs/${name}.log
StandardError=append:${PROJECT_DIR}/logs/${name}.log

[Install]
WantedBy=multi-user.target
EOF

    echo "✅ 已写入 /etc/systemd/system/${name}.service"
}

# ── 创建日志目录 ───────────────────────────────────────

mkdir -p "${PROJECT_DIR}/logs"
echo "✅ 日志目录：${PROJECT_DIR}/logs/"

# ── 写入两个服务 ───────────────────────────────────────

write_service "binance-monitor"   "monitor_positions.py"  "Binance 持仓监控（每小时统计）"
write_service "binance-strategy"  "open_top_shorts.py"    "Binance 涨跌幅策略（定时开平仓）"

# ── 重载并启用 ─────────────────────────────────────────

systemctl daemon-reload

for svc in binance-monitor binance-strategy; do
    systemctl enable  $svc
    systemctl restart $svc
    sleep 1
    status=$(systemctl is-active $svc)
    if [ "$status" = "active" ]; then
        echo "✅ $svc 启动成功（$status）"
    else
        echo "❌ $svc 启动异常（$status），请运行：journalctl -u $svc -n 30"
    fi
done

echo ""
echo "======================================"
echo " 安装完成！常用命令："
echo "======================================"
echo " 查看状态：  systemctl status binance-monitor"
echo "             systemctl status binance-strategy"
echo " 查看日志：  tail -f ${PROJECT_DIR}/logs/binance-monitor.log"
echo "             tail -f ${PROJECT_DIR}/logs/binance-strategy.log"
echo " 停止服务：  systemctl stop binance-monitor"
echo " 重启服务：  systemctl restart binance-strategy"
echo "======================================"
=======
#!/bin/bash
# 一键注册 binance-trader 的两个 systemd 服务
# 用法：bash setup_services.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3)"
USER="$(whoami)"

echo "======================================"
echo " Binance Trader 服务安装脚本"
echo "======================================"
echo " 项目目录：$PROJECT_DIR"
echo " Python：  $PYTHON"
echo " 用户：    $USER"
echo ""

# ── 生成 service 文件 ──────────────────────────────────

write_service() {
    local name=$1
    local script=$2
    local desc=$3

    cat > /etc/systemd/system/${name}.service <<EOF
[Unit]
Description=${desc}
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON} ${PROJECT_DIR}/${script}
Restart=always
RestartSec=10
StartLimitIntervalSec=0

# 崩溃日志
StandardOutput=append:${PROJECT_DIR}/logs/${name}.log
StandardError=append:${PROJECT_DIR}/logs/${name}.log

[Install]
WantedBy=multi-user.target
EOF

    echo "✅ 已写入 /etc/systemd/system/${name}.service"
}

# ── 创建日志目录 ───────────────────────────────────────

mkdir -p "${PROJECT_DIR}/logs"
echo "✅ 日志目录：${PROJECT_DIR}/logs/"

# ── 写入两个服务 ───────────────────────────────────────

write_service "binance-monitor"   "monitor_positions.py"  "Binance 持仓监控（每小时统计）"
write_service "binance-strategy"  "open_top_shorts.py"    "Binance 涨跌幅策略（定时开平仓）"

# ── 拉取最新代码 ───────────────────────────────────────

echo "正在从 Git 拉取最新代码..."
cd "${PROJECT_DIR}"
if git pull; then
    echo "✅ 代码已更新"
else
    echo "⚠️  git pull 失败，继续使用当前代码"
fi
echo ""

# ── 重载并启用 ─────────────────────────────────────────

systemctl daemon-reload

for svc in binance-monitor binance-strategy; do
    systemctl enable  $svc
    systemctl restart $svc
    sleep 1
    status=$(systemctl is-active $svc)
    if [ "$status" = "active" ]; then
        echo "✅ $svc 启动成功（$status）"
    else
        echo "❌ $svc 启动异常（$status），请运行：journalctl -u $svc -n 30"
    fi
done

echo ""
echo "======================================"
echo " 安装完成！常用命令："
echo "======================================"
echo " 查看状态：  systemctl status binance-monitor"
echo "             systemctl status binance-strategy"
echo " 查看日志：  tail -f ${PROJECT_DIR}/logs/binance-monitor.log"
echo "             tail -f ${PROJECT_DIR}/logs/binance-strategy.log"
echo " 停止服务：  systemctl stop binance-monitor"
echo " 重启服务：  systemctl restart binance-strategy"
echo "======================================"
