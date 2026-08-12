import { useEffect, useMemo, useState } from 'react'
import { Card, Row, Col, Statistic, Table, Tag, Spin, Button, Select, Space } from 'antd'
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

// ── 按周期分组的列（实盘 batch）──
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
  { title: '币种', dataIndex: 'symbol', key: 'symbol', width: 100 },
  { title: '入场价', dataIndex: 'entry_price', key: 'entry_price', width: 90,
    render: v => v ? parseFloat(v).toFixed(4) : '-' },
  { title: '标记价', dataIndex: 'mark_price', key: 'mark_price', width: 90,
    render: v => v ? parseFloat(v).toFixed(4) : '-' },
  { title: '数量', dataIndex: 'position_amt', key: 'position_amt', width: 80 },
  {
    title: '盈亏', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 80,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0),
  },
  {
    title: 'ROE', dataIndex: 'roe_pct', key: 'roe_pct', width: 75,
    render: v => v == null ? '-' : <span style={{ color: pnlColor(v), fontWeight: 500 }}>{v >= 0 ? '+' : ''}{parseFloat(v).toFixed(2)}%</span>,
  },
]

// 按 (open_anchor, side) 分组聚合成 batch（open_anchor 是周期 :30 整点，稳定）
function groupBatches(rows, sideFilter) {
  const filtered = rows.filter(r => r.side === sideFilter)
  const map = new Map()
  for (const r of filtered) {
    const k = (r.open_anchor || r.open_time || '').slice(0, 16)
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

const sumPnl = arr => arr.reduce((a, p) => a + (parseFloat(p.unrealized_pnl) || 0), 0)

// ── 一个账户的余额卡（余额 + 保证金两块）──
function AccountCard({ tag, tagColor, subtitle, rt }) {
  const configured = rt?.configured !== false
  const hasError = configured && rt?.error
  return (
    <Card size="small" title={
      <span>
        <Tag color={tagColor}>{tag}</Tag>
        <span style={{ color: '#999', fontSize: 12 }}>{subtitle}</span>
      </span>
    }>
      {!configured ? (
        <span style={{ color: '#999' }}>未配置子账号密钥（.env.sub24h）</span>
      ) : hasError ? (
        <span style={{ color: '#cf1322' }}>查询失败：{String(rt.error).slice(0, 60)}</span>
      ) : (
        <Row gutter={12}>
          <Col span={12}>
            <Statistic title="账户余额" value={rt?.balance ?? 0} precision={2} suffix="U"
              prefix={<WalletOutlined />} valueStyle={{ color: '#13c2c2', fontSize: 22 }} />
          </Col>
          <Col span={12}>
            <Statistic title="保证金占用" value={rt?.margin_used ?? 0} precision={2} suffix="U"
              prefix={<DollarOutlined />} valueStyle={{ color: '#fa8c16', fontSize: 22 }} />
          </Col>
        </Row>
      )}
    </Card>
  )
}

// ── 一个账户的实时持仓块（跌幅榜-空）──
function PositionsBlock({ rt }) {
  const positions = (rt?.positions || []).map((p, i) => ({ ...p, key: i }))
  const losers = positions.filter(p => p.side?.includes('跌幅'))
  const others = positions.filter(p => !p.side?.includes('跌幅') && !p.side?.includes('涨幅'))
  return (
    <Card size="small" style={{ marginBottom: 12 }} title={
      <span>实时持仓<span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>{positions.length} 笔</span></span>
    }>
      <Card size="small" type="inner" title={
        <span>
          <Tag color="cyan">跌幅榜-空</Tag>
          <span style={{ color: '#999', fontSize: 12, marginLeft: 4 }}>
            {losers.length} 笔  浮盈 <PnlCell value={sumPnl(losers)} />
          </span>
        </span>
      }>
        <Table
          columns={positionColumns}
          dataSource={losers}
          pagination={false}
          scroll={{ x: 'max-content' }}
          size="small"
          rowClassName={r => (r.unrealized_pnl > 0 ? 'row-profit' : r.unrealized_pnl < 0 ? 'row-loss' : '')}
          locale={{ emptyText: '无持仓' }}
        />
      </Card>
      {others.length > 0 && (
        <Card size="small" type="inner" title="其他" style={{ marginTop: 12 }}>
          <Table columns={positionColumns} dataSource={others} pagination={false}
            scroll={{ x: 'max-content' }} size="small" />
        </Card>
      )}
    </Card>
  )
}

// ── 一个账户的按周期分组表 ──
function BatchBlock({ batches, netPnl, loading }) {
  const title = (
    <span>
      <Tag color="cyan">跌幅榜-空</Tag>
      <span style={{ color: '#999', fontSize: 12, marginLeft: 4 }}>
        {batches.length} 周期  净 <PnlCell value={netPnl} />
      </span>
    </span>
  )
  return (
    <Spin spinning={loading}>
      <Card size="small" title={title} style={{ marginBottom: 16 }}>
        <Table
          columns={batchColumns}
          dataSource={batches}
          pagination={{ pageSize: 30, showSizeChanger: true, pageSizeOptions: [20, 30, 50, 100] }}
          scroll={{ x: 'max-content' }}
          size="small"
          rowClassName={r => (r.net_pnl > 0 ? 'row-profit' : r.net_pnl < 0 ? 'row-loss' : '')}
          locale={{ emptyText: '暂无记录' }}
        />
      </Card>
    </Spin>
  )
}

export default function Dashboard() {
  const [rt, setRt] = useState(null)        // 主账号 8h
  const [rt24, setRt24] = useState(null)     // 子账号 24h
  const [logs, setLogs] = useState([])       // 8h open_log
  const [logs24, setLogs24] = useState([])   // 24h open_log
  const [loadingRt, setLoadingRt] = useState(false)
  const [loadingLog, setLoadingLog] = useState(true)
  const [updatedRt, setUpdatedRt] = useState(null)
  const [timeFilter, setTimeFilter] = useState('all') // 8h 按时段筛选

  const fetchAll = async () => {
    setLoadingRt(true)
    setLoadingLog(true)
    try {
      const [r1, r2, r3, r4] = await Promise.all([
        axios.get('/api/realtime'),
        axios.get('/api/open_log_8h'),
        axios.get('/api/realtime_24h'),
        axios.get('/api/open_log_24h'),
      ])
      if (!r1.data.error) setRt(r1.data)
      setLogs(r2.data || [])
      setRt24(r3.data || null)
      setLogs24(r4.data || [])
      setUpdatedRt(new Date().toLocaleTimeString())
    } catch (e) {}
    setLoadingRt(false)
    setLoadingLog(false)
  }
  useEffect(() => { fetchAll() }, [])

  // 8h：按周期分组 + 时段筛选
  const allLoserBatches8 = useMemo(() => groupBatches(logs, '跌幅榜-空（无过滤）'), [logs])
  const timeOptions = useMemo(() => {
    const set = new Set()
    for (const b of allLoserBatches8) set.add(b.open_time_key.slice(11, 16))
    return [...set].sort()
  }, [allLoserBatches8])
  const matchTime = b => timeFilter === 'all' || b.open_time_key.slice(11, 16) === timeFilter
  const loserBatches8 = allLoserBatches8.filter(matchTime)
  const net8 = loserBatches8.reduce((a, b) => a + b.net_pnl, 0)

  // 24h：单窗口 00:30，无需时段筛选
  const loserBatches24 = useMemo(() => groupBatches(logs24, '跌幅榜-空（无过滤）'), [logs24])
  const net24 = loserBatches24.reduce((a, b) => a + b.net_pnl, 0)

  const sectionTitle = (text, sub) => (
    <div style={{ margin: '4px 0 12px', fontWeight: 600, fontSize: 15 }}>
      {text} <span style={{ color: '#999', fontSize: 12, fontWeight: 400 }}>{sub}</span>
    </div>
  )

  return (
    <div>
      {/* 顶部刷新栏 */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 10,
        background: '#f5f7fa', padding: '8px 0', marginBottom: 8,
        display: 'flex', justifyContent: 'flex-end', alignItems: 'center',
        gap: 8, flexWrap: 'wrap',
      }}>
        <span style={{ color: '#666', fontSize: 13 }}>
          {updatedRt ? `更新于 ${updatedRt}` : '未刷新'}
        </span>
        <Button type="primary" icon={<ReloadOutlined />}
          loading={loadingRt || loadingLog} onClick={fetchAll} style={{ flexShrink: 0 }}>
          刷新全部
        </Button>
      </div>

      {/* 顶部：两个账户余额卡 */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={12}>
          <AccountCard tag="主账号" tagColor="blue" subtitle="8h 实盘" rt={rt} />
        </Col>
        <Col xs={24} sm={12}>
          <AccountCard tag="子账号" tagColor="purple" subtitle="24h 实盘" rt={rt24} />
        </Col>
      </Row>

      {/* ── 8h（主账号）与 24h（子账号）左右并排；窄屏自动上下堆叠 ── */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          {sectionTitle('主账号 · 8h 实盘', '跌幅榜-空（无过滤）· 组内 +16U 提前平，否则跑满 8h')}
          <PositionsBlock rt={rt} />
          <div style={{ marginBottom: 12 }}>
            <Space wrap>
              <span style={{ color: '#666' }}>按时段筛选：</span>
              <Select size="small" style={{ minWidth: 140 }} value={timeFilter} onChange={setTimeFilter}
                options={[{ label: '全部时段', value: 'all' }, ...timeOptions.map(t => ({ label: t, value: t }))]} />
              {timeFilter !== 'all' && <Tag color="blue">仅看 {timeFilter} 周期</Tag>}
            </Space>
          </div>
          <BatchBlock batches={loserBatches8} netPnl={net8} loading={loadingLog} />
        </Col>
        <Col xs={24} lg={12}>
          {sectionTitle('子账号 · 24h 实盘', '跌幅榜-空（无过滤）· 组内 +10U 提前平，否则跑满 24h')}
          <PositionsBlock rt={rt24} />
          <BatchBlock batches={loserBatches24} netPnl={net24} loading={loadingLog} />
        </Col>
      </Row>

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
