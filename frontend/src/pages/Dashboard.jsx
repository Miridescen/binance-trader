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

// ── 实时持仓表的列（不带方向列，按 side 已拆分到左右两栏）──
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
    // 优先 open_anchor，fallback open_time（兼容回填前的老数据）
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

export default function Dashboard() {
  const [rt, setRt] = useState(null)
  const [logs, setLogs] = useState([])
  const [loadingRt, setLoadingRt] = useState(false)
  const [loadingLog, setLoadingLog] = useState(true)
  const [updatedRt, setUpdatedRt] = useState(null)
  const [timeFilter, setTimeFilter] = useState('all') // 'all' | 'HH:MM'

  // 一键刷新所有数据：账户/持仓 + 8h 实盘记录
  const fetchAll = async () => {
    setLoadingRt(true)
    setLoadingLog(true)
    try {
      const [r1, r2] = await Promise.all([
        axios.get('/api/realtime'),
        axios.get('/api/open_log_8h'),
      ])
      if (!r1.data.error) setRt(r1.data)
      setLogs(r2.data || [])
      setUpdatedRt(new Date().toLocaleTimeString())
    } catch (e) {}
    setLoadingRt(false)
    setLoadingLog(false)
  }
  useEffect(() => { fetchAll() }, [])

  const balance = rt?.balance ?? 0
  const marginUsed = rt?.margin_used ?? 0
  const positions = (rt?.positions || []).map((p, i) => ({ ...p, key: i }))
  const gainerPositions = positions.filter(p => p.side?.includes('涨幅'))
  const loserPositions  = positions.filter(p => p.side?.includes('跌幅'))
  const otherPositions  = positions.filter(p => !p.side?.includes('涨幅') && !p.side?.includes('跌幅'))

  const sumPnl = arr => arr.reduce((a, p) => a + (parseFloat(p.unrealized_pnl) || 0), 0)
  const gainerPnl = sumPnl(gainerPositions)
  const loserPnl  = sumPnl(loserPositions)

  const allGainerBatches = useMemo(() => groupBatches(logs, '涨幅榜-空（无过滤）'), [logs])
  const allLoserBatches  = useMemo(() => groupBatches(logs, '跌幅榜-空（无过滤）'), [logs])

  // 该方向出现过的所有时段，按字典序排序
  const allTimeOptions = useMemo(() => {
    const set = new Set()
    for (const b of allGainerBatches) set.add(b.open_time_key.slice(11, 16))
    for (const b of allLoserBatches)  set.add(b.open_time_key.slice(11, 16))
    return [...set].sort()
  }, [allGainerBatches, allLoserBatches])

  const matchTime = b => timeFilter === 'all' || b.open_time_key.slice(11, 16) === timeFilter
  const gainerBatches = allGainerBatches.filter(matchTime)
  const loserBatches  = allLoserBatches.filter(matchTime)

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
      {/* 顶部刷新栏（粘性，滚到哪都能点） */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 10,
        background: '#f0f2f5', padding: '8px 0', marginBottom: 8,
        display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 12,
      }}>
        <span style={{ color: '#666', fontSize: 13 }}>
          {updatedRt ? `更新于 ${updatedRt}` : '未刷新'}
        </span>
        <Button
          type="primary"
          size="large"
          icon={<ReloadOutlined />}
          loading={loadingRt || loadingLog}
          onClick={fetchAll}
        >
          刷新全部
        </Button>
      </div>

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

      {/* 第二行：实时持仓（左右拆分） */}
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={
          <span>
            实时持仓
            <span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>
              {positions.length} 笔
            </span>
          </span>
        }
      >
        <Row gutter={[12, 12]}>
          <Col xs={24} lg={12}>
            <Card size="small" type="inner" title={
              <span>
                <Tag color="green">涨幅榜-空</Tag>
                <span style={{ color: '#999', fontSize: 12, marginLeft: 4 }}>
                  {gainerPositions.length} 笔  浮盈 <PnlCell value={gainerPnl} />
                </span>
              </span>
            }>
              <Table
                columns={positionColumns}
                dataSource={gainerPositions}
                pagination={false}
                scroll={{ x: 'max-content' }}
                size="small"
                rowClassName={r => {
                  if (r.unrealized_pnl > 0) return 'row-profit'
                  if (r.unrealized_pnl < 0) return 'row-loss'
                  return ''
                }}
                locale={{ emptyText: '无' }}
              />
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card size="small" type="inner" title={
              <span>
                <Tag color="cyan">跌幅榜-空</Tag>
                <span style={{ color: '#999', fontSize: 12, marginLeft: 4 }}>
                  {loserPositions.length} 笔  浮盈 <PnlCell value={loserPnl} />
                </span>
              </span>
            }>
              <Table
                columns={positionColumns}
                dataSource={loserPositions}
                pagination={false}
                scroll={{ x: 'max-content' }}
                size="small"
                rowClassName={r => {
                  if (r.unrealized_pnl > 0) return 'row-profit'
                  if (r.unrealized_pnl < 0) return 'row-loss'
                  return ''
                }}
                locale={{ emptyText: '无' }}
              />
            </Card>
          </Col>
        </Row>
        {otherPositions.length > 0 && (
          <Card size="small" type="inner" title="其他" style={{ marginTop: 12 }}>
            <Table
              columns={positionColumns}
              dataSource={otherPositions}
              pagination={false}
              scroll={{ x: 'max-content' }}
              size="small"
            />
          </Card>
        )}
      </Card>

      {/* 第三行：8h 实盘按周期分组（跌幅榜-空 无过滤，+10U 提前平 / 否则跑满 8h） */}
      <Spin spinning={loadingLog}>
        <div style={{ marginBottom: 8, fontWeight: 600, fontSize: 15 }}>
          8h 实盘 <span style={{ color: '#999', fontSize: 12, fontWeight: 400 }}>跌幅榜-空（无过滤）· 组内 +10U 提前平，否则跑满 8h</span>
        </div>
        <div style={{ marginBottom: 12 }}>
          <Space wrap>
            <span style={{ color: '#666' }}>按时段筛选：</span>
            <Select
              size="small"
              style={{ minWidth: 140 }}
              value={timeFilter}
              onChange={setTimeFilter}
              options={[
                { label: '全部时段', value: 'all' },
                ...allTimeOptions.map(t => ({ label: t, value: t })),
              ]}
            />
            {timeFilter !== 'all' && (
              <Tag color="blue">仅看 {timeFilter} 周期</Tag>
            )}
          </Space>
        </div>
        <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
          <Col xs={24}>
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
