# Binance Trader

币安合约均值回归策略交易系统，每日定时做空涨幅榜、做多跌幅榜，3倍杠杆，持仓约24小时。

---

## 项目结构

```
binance-trader/
├── open_top_shorts.py      # 核心策略：08:50平仓 / 09:00开仓
├── monitor_positions.py    # 持仓监控：每小时统计，触发止损
├── virtual_trade.py        # 虚拟沙盘：不过滤市值，不下真实订单
├── binance_client.py       # 币安 API 封装
├── api.py                  # Flask API，为前端提供数据
├── start_service.sh        # 首次部署脚本
├── update.sh               # 日常更新脚本
├── requirements.txt        # Python 依赖
├── frontend/               # Vite + React + Ant Design 前端
├── open_log.csv            # 开仓记录
├── positions_log.csv       # 每小时持仓统计
├── positions_detail_log.csv# 每小时单仓盈亏明细
├── batch_summary_log.csv   # 每批次多空盈亏汇总
├── virtual_open_log.csv    # 虚拟盘开仓记录
└── events_log.csv          # 止损等事件记录
```

---

## 关键参数

| 参数 | 值 | 位置 |
|------|-----|------|
| 杠杆 | 3x | `open_top_shorts.py` `LEVERAGE` |
| 每单保证金 | 10 USDT | `MARGIN_PER_POS` |
| 开仓数量 | 多空各 20 个 | `TOP_N` |
| 候选池大小 | 120 个（TOP_N × 6） | `CANDIDATE_BUFFER` |
| 平仓时间 | 每天 08:50 | `CLOSE_HOUR/MINUTE` |
| 开仓时间 | 每天 09:00 | `OPEN_HOUR/MINUTE` |
| 止损阈值 | ROE ≤ -80% | `monitor_positions.py` `STOP_LOSS_ROE_PCT` |
| 止损检查间隔 | 60 秒 | `CHECK_INTERVAL` |

---

## 首次部署

### 1. 服务器环境要求

- Ubuntu 20.04+
- Python 3.8+
- Node.js 18+
- nginx

### 2. 安装 Node.js（如未安装）

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install nodejs -y
node -v  # 确认安装成功
```

### 3. 安装 nginx（如未安装）

```bash
apt install nginx -y
```

### 4. 克隆项目

```bash
git clone https://github.com/Miridescen/binance-trader.git
cd binance-trader
```

### 5. 配置环境变量

```bash
cp .env.example .env   # 如有模板
vim .env
```

填入币安 API Key 和 Secret：

```
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
```

### 6. 一键部署

```bash
sudo bash start_service.sh
```

脚本会自动完成：
- 安装 Python 依赖（flask、requests 等）
- 安装前端依赖并构建（npm install + build）
- 注册并启动 4 个 systemd 服务
- 配置 nginx，监听 **8080 端口**

### 7. 开放防火墙端口

如果是云服务器（阿里云/腾讯云），需要在**安全组**中开放 **TCP 8080** 入方向规则。

---

## 日常更新

本地改完代码 push 后，服务器执行：

```bash
sudo bash update.sh
```

脚本会自动：
1. `git pull` 拉取最新代码
2. `npm run build` 构建前端
3. 将构建产物复制到 `/var/www/binance-trader/`
4. 重启 `binance-api` 服务

---

## 服务管理

系统共有 4 个 systemd 服务：

| 服务名 | 脚本 | 说明 |
|--------|------|------|
| `binance-strategy` | `open_top_shorts.py` | 核心策略，定时开平仓 |
| `binance-monitor` | `monitor_positions.py` | 持仓监控，止损检查 |
| `binance-virtual` | `virtual_trade.py` | 虚拟沙盘对照组 |
| `binance-api` | `api.py` | 前端数据接口 |

```bash
# 查看状态
systemctl status binance-strategy
systemctl status binance-monitor
systemctl status binance-virtual
systemctl status binance-api

# 查看实时日志
tail -f logs/binance-strategy.log
tail -f logs/binance-monitor.log
tail -f logs/binance-virtual.log
tail -f logs/binance-api.log

# 重启服务
systemctl restart binance-strategy

# 停止服务
systemctl stop binance-virtual
```

---

## 前端监控页面

访问地址：`http://<服务器IP>:8080`

| 页面 | 说明 |
|------|------|
| 持仓监控 | 实时余额、浮盈亏统计，每分钟自动刷新 |
| 开仓记录 | 历史开平仓记录，含胜率、盈亏统计，支持筛选排序 |

---

## 常见问题

**页面打开 500 错误**

nginx 无法读取 `/root/` 目录，执行：
```bash
chmod o+x /root
```

或将文件复制到 `/var/www/`：
```bash
cp -r ~/binance-trader/frontend/dist/* /var/www/binance-trader/
```

**服务启动后 git pull 冲突**

程序运行时会持续写入 CSV 文件，pull 前需暂存本地修改：
```bash
git stash && git pull && git stash pop
```

**查看服务器公网 IP**

```bash
curl -s ifconfig.me
```
