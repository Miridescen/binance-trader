import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Table, Tag, Spin, Button } from 'antd'
import { ReloadOutlined, WalletOutlined, DollarOutlined } from '@ant-design/icons'
import axios from 'axios'

function pnlColor(n) {
  const v = parseFloat(n)
  if (v > 0) return '#3f8600'
  if (v < 0) return '#cf1322'
  return '#999'
}

function PnlCell({ value, digits = 2 }) {
  const n = parseFloat(value)
  if (isNaN(n)) return <span style={{ color: '#999' }}>-</span>
  return (
    <span style={{ color: pnlColor(n), fontWeight: 500 }}>
      {n >= 0 ? '+' : ''}{n.toFixed(digits)}
    </span>
  )
}

// ── 实盘 4h 按周期分组的列 ──
const batchColumns = [
  {
    title: '开仓时间',
    dataIndex: 'open_time_short',
    key: 'open_time',
    width: 110,
    sorter: (a, b) => (a.open_time_key || '').localeCompare(b.open_time_key || ''),
    defaultSortOrder: 'descend',
  },
  {
    title: '平仓',
    dataIndex: 'close_time_short',
    key: 'close_time',
    width: 75,
    render: v => v || <Tag color="blue">持仓中</Tag>,
  },
  { title: '笔', dataIndex: 'n', key: 'n', width: 40 },
  {
    title: '毛PnL',
    dataIndex: 'gross_pnl',
    key: 'gross_pnl',
    width: 80,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => (a.gross_pnl || 0) - (b.gross_pnl || 0),
  },
  {
    title: '手续费',
    dataIndex: 'commission',
    key: 'commission',
    width: 80,
    render: v => <PnlCell value={v} digits={3} />,
  },
  {
    title: '资金费',
    dataIndex: 'funding',
    key: 'funding',
    width: 75,
    render: v => <PnlCell value={v} digits={3} />,
  },
  {
    title: '净PnL',
    dataIndex: 'net_pnl',
    key: 'net_pnl',
    width: 80,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => (a.net_pnl || 0) - (b.net_pnl || 0),
  },
]

// ── 实时持仓表的列 ──
const positionColumns = [
  { title: '币种', dataIndex: 'symbol', key: 'symbol', width: 110 },
  {
    title: '方向',
    dataIndex: 'side',
    key: 'side',
    width: 130,
    render: v => {
      let color = 'default'
      if (v?.includes('涨幅') && v?.includes('空')) color = 'green'
      else if (v?.includes('跌幅') && v?.includes('空')) color = 'cyan'
      return <Tag color={color}>{v}</Tag>
    },
  },
  { title: '入场价', dataIndex: 'entry_price', key: 'entry_price', width: 95,
    render: v => v ? parseFloat(v).toFixed(4) : '-' },
  { title: '标记价', dataIndex: 'mark_price', key: 'mark_price', width: 95,
    render: v => v ? parseFloat(v).toFixed(4) : '-' },
  { title: '数量', dataIndex: 'position_amt', key: 'position_amt', width: 90 },
  {
    title: '盈亏', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 85,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0),
  },
  {
    title: 'ROE', dataIndex: 'roe_pct', key: 'roe_pct', width: 80,
    render: v => v == null ? '-' : <span style={{ color: pnlColor(v), fontWeight: 500 }}>{v >= 0 ? '+' : ''}{parseFloat(v).toFixed(2)}%</span>,
  },
]

// 把 open_log_4h 按 (open_time, side) 分组，聚合成 batch
function groupBatches(rows, sideFilter) {
  const filtered = rows.filter(r => r.side === sideFilter)
  const map = new Map()
  for (const r of filtered) {
    const k = r.open_time?.slice(0, 16) || ''
    if (!map.has(k)) map.set(k, [])
    map.get(k).push(r)
  }
  const batches = []
  for (const [open_time_key, items] of map) {
    const closedItems = items.filter(r => r.close_time)
    const gross = items.reduce((a, r) => a + (parseFloat(r.unrealized_pnl) || 0), 0)
    const comm = items.reduce((a, r) =>
      a + (parseFloat(r.open_commission) || 0) + (parseFloat(r.close_commission) || 0), 0)
    const fund = items.reduce((a, r) => a + (parseFloat(r.funding_fee) || 0), 0)
    const net = gross + comm + fund
    const closeTimes = items.map(r => r.close_time).filter(Boolean)
    const closeTime = closeTimes.length ? closeTimes.sort().slice(-1)[0] : null
    batches.push({
      key: open_time_key,
      open_time_key,
      open_time_short: open_time_key.slice(5),
      close_time_short: closeTime ? closeTime.slice(5, 16) : null,
      all_closed: closedItems.length === items.length,
      n: items.length,
      gross_pnl: gross,
      commission: comm,
      funding: fund,
      net_pnl: net,
    })
  }
  return batches
}

export default function Dashboard() {
  const [rt, setRt] = useState(null)
  const [logs, setLogs] = useState([])
  const [loadingRt, setLoadingRt] = useState(false)
  const [loadingLog, setLoadingLog] = useState(true)
  const [updatedRt, setUpdatedRt] = useState(null)

  // 实盘记录只在挂载时拉
  useEffect(() => {
    axios.get('/api/open_log_4h')
      .then(res => setLogs(res.data || []))
      .finally(() => setLoadingLog(false))
  }, [])

  // 实时数据手动刷新（首次也手动？不，首次自动一次，之后手动）
  const fetchRealtime = async () => {
    setLoadingRt(true)
    try {
      const res = await axios.get('/api/realtime')
      if (!res.data.error) {
        setRt(res.data)
        setUpdatedRt(new Date().toLocaleTimeString())
      }
    } catch (e) {}
    setLoadingRt(false)
  }
  useEffect(() => { fetchRealtime() }, [])

  const balance = rt?.balance ?? 0
  const marginUsed = rt?.margin_used ?? 0
  const positions = (rt?.positions || []).map((p, i) => ({ ...p, key: i }))

  const gainerBatches = groupBatches(logs, '涨幅榜-空（无过滤）')
  const loserBatches  = groupBatches(logs, '跌幅榜-空（无过滤）')

  const sum = arr => arr.reduce((a, b) => a + b, 0)
  const gNet = sum(gainerBatches.map(b => b.net_pnl))
  const lNet = sum(loserBatches.map(b => b.net_pnl))

  const batchTitle = (label, color, batches, netPnl) => {
    const n = batches.length
    return (
      <span>
        <Tag color={color}>{label}</Tag>
        <span style={{ color: '#999', fontSize: 12, marginLeft: 4 }}>
          {n} 周期  净 <PnlCell value={netPnl} />
        </span>
      </span>
    )
  }

  return (
    <div>
      {/* 顶部：账户卡 */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={12} md={12}>
          <Card size="small">
            <Statistic title="账户余额" value={balance} precision={2} suffix="U"
              prefix={<WalletOutlined />} valueStyle={{ color: '#1677ff' }} />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={12}>
          <Card size="small">
            <Statistic title="保证金占用" value={marginUsed} precision={2} suffix="U"
              prefix={<DollarOutlined />} valueStyle={{ color: '#fa8c16' }} />
          </Card>
        </Col>
      </Row>

      {/* 中间：4h 实盘按周期分组对照 */}
      <Spin spinning={loadingLog}>
        <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
          <Col xs={24} lg={12}>
            <Card size="small" title={batchTitle('涨幅榜-空', 'green', gainerBatches, gNet)}>
              <Table
                columns={batchColumns}
                dataSource={gainerBatches}
                pagination={{ pageSize: 30, showSizeChanger: true, pageSizeOptions: [20, 30, 50, 100] }}
                scroll={{ x: 'max-content' }}
                size="small"
                rowClassName={r => {
                  if (r.net_pnl > 0) return 'row-profit'
                  if (r.net_pnl < 0) return 'row-loss'
                  return ''
                }}
              />
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card size="small" title={batchTitle('跌幅榜-空', 'cyan', loserBatches, lNet)}>
              <Table
                columns={batchColumns}
                dataSource={loserBatches}
                pagination={{ pageSize: 30, showSizeChanger: true, pageSizeOptions: [20, 30, 50, 100] }}
                scroll={{ x: 'max-content' }}
                size="small"
                rowClassName={r => {
                  if (r.net_pnl > 0) return 'row-profit'
                  if (r.net_pnl < 0) return 'row-loss'
                  return ''
                }}
              />
            </Card>
          </Col>
        </Row>
      </Spin>

      {/* 底部：实时持仓 + 手动刷新 */}
      <Card
        size="small"
        title={
          <span>
            实时持仓
            <span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>
              {positions.length} 笔   {updatedRt ? `更新 ${updatedRt}` : '未刷新'}
            </span>
          </span>
        }
        extra={
          <Button
            size="small"
            type="primary"
            icon={<ReloadOutlined />}
            loading={loadingRt}
            onClick={fetchRealtime}
          >
            刷新
          </Button>
        }
      >
        <Table
          columns={positionColumns}
          dataSource={positions}
          pagination={false}
          scroll={{ x: 'max-content' }}
          size="small"
          rowClassName={r => {
            if (r.unrealized_pnl > 0) return 'row-profit'
            if (r.unrealized_pnl < 0) return 'row-loss'
            return ''
          }}
          locale={{ emptyText: '当前无持仓' }}
        />
      </Card>

      <style>{`
        .row-profit td { background: #f6ffed !important; }
        .row-loss td { background: #fff1f0 !important; }
        @media (max-width: 768px) {
          .ant-table-cell { white-space: normal !important; word-break: break-all; }
        }
      `}</style>
    </div>
  )
}
