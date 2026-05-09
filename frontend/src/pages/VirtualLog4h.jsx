import { useEffect, useState } from 'react'
import { Table, Card, Tag, Spin, Row, Col, Statistic, Tabs } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons'
import axios from 'axios'

function pnlColor(val) {
  const n = parseFloat(val)
  if (n > 0) return '#3f8600'
  if (n < 0) return '#cf1322'
  return '#999'
}

function PnlCell({ value }) {
  const n = parseFloat(value)
  if (isNaN(n)) return <span style={{ color: '#999' }}>-</span>
  return (
    <span style={{ color: pnlColor(value), fontWeight: 500 }}>
      {n >= 0 ? '+' : ''}{n.toFixed(2)}
    </span>
  )
}

function RoeCell({ value }) {
  const n = parseFloat(value)
  if (isNaN(n)) return <span style={{ color: '#999' }}>-</span>
  return (
    <span style={{ color: pnlColor(value), fontWeight: 500 }}>
      {n >= 0 ? '+' : ''}{n.toFixed(2)}%
    </span>
  )
}

function CloseReasonTag({ reason }) {
  if (!reason) return <Tag color="blue">持仓中</Tag>
  if (reason === '组内+10u') return <Tag color="gold">组内+10u</Tag>
  if (reason === '4h_timed') return <Tag color="default">4h定平</Tag>
  return <Tag>{reason}</Tag>
}

const orderColumns = [
  {
    title: '开仓时间',
    dataIndex: 'open_time',
    key: 'open_time',
    width: 110,
    render: v => v ? v.slice(5, 16) : '-',
    sorter: (a, b) => (a.open_time || '').localeCompare(b.open_time || ''),
    defaultSortOrder: 'descend',
  },
  {
    title: '平仓时间',
    dataIndex: 'close_time',
    key: 'close_time',
    width: 110,
    render: v => v ? v.slice(5, 16) : <span style={{ color: '#bbb' }}>持仓中</span>,
  },
  {
    title: '平仓原因',
    dataIndex: 'close_reason',
    key: 'close_reason',
    width: 110,
    render: v => <CloseReasonTag reason={v} />,
    filters: [
      { text: '组内+10u', value: '组内+10u' },
      { text: '4h_timed', value: '4h_timed' },
      { text: '持仓中', value: null },
    ],
    onFilter: (value, record) => (value === null ? !record.close_reason : record.close_reason === value),
  },
  {
    title: '币种',
    dataIndex: 'symbol',
    key: 'symbol',
    width: 110,
    filters: [],
    onFilter: (value, record) => record.symbol === value,
  },
  {
    title: '方向',
    dataIndex: 'side',
    key: 'side',
    width: 160,
    render: v => {
      let color = 'default'
      if (v?.includes('涨幅') && v?.includes('空')) color = 'green'
      else if (v?.includes('涨幅') && v?.includes('多')) color = 'red'
      else if (v?.includes('跌幅') && v?.includes('空')) color = 'cyan'
      else if (v?.includes('跌幅') && v?.includes('多')) color = 'orange'
      return <Tag color={color}>{v}</Tag>
    },
    filters: [
      { text: '涨幅榜-空（有过滤）', value: '涨幅榜-空（有过滤）' },
      { text: '涨幅榜-空（无过滤）', value: '涨幅榜-空（无过滤）' },
      { text: '涨幅榜-多（有过滤）', value: '涨幅榜-多（有过滤）' },
      { text: '涨幅榜-多（无过滤）', value: '涨幅榜-多（无过滤）' },
      { text: '跌幅榜-空（有过滤）', value: '跌幅榜-空（有过滤）' },
      { text: '跌幅榜-空（无过滤）', value: '跌幅榜-空（无过滤）' },
      { text: '跌幅榜-多（有过滤）', value: '跌幅榜-多（有过滤）' },
      { text: '跌幅榜-多（无过滤）', value: '跌幅榜-多（无过滤）' },
    ],
    onFilter: (value, record) => record.side === value,
  },
  {
    title: '信号涨跌幅',
    dataIndex: 'change_pct',
    key: 'change_pct',
    width: 100,
    render: v => {
      const n = parseFloat(v)
      if (isNaN(n)) return '-'
      return <span style={{ color: n > 0 ? '#cf1322' : '#3f8600' }}>{n > 0 ? '+' : ''}{n.toFixed(2)}%</span>
    },
    sorter: (a, b) => parseFloat(a.change_pct) - parseFloat(b.change_pct),
  },
  {
    title: '开仓价',
    dataIndex: 'entry_price',
    key: 'entry_price',
    width: 100,
    render: v => v ? parseFloat(v).toFixed(4) : '-',
  },
  {
    title: '平仓价',
    dataIndex: 'close_price',
    key: 'close_price',
    width: 100,
    render: v => v ? parseFloat(v).toFixed(4) : '-',
  },
  {
    title: '盈亏(USDT)',
    dataIndex: 'unrealized_pnl',
    key: 'unrealized_pnl',
    width: 110,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => parseFloat(a.unrealized_pnl || 0) - parseFloat(b.unrealized_pnl || 0),
  },
  {
    title: 'ROE',
    dataIndex: 'roe_pct',
    key: 'roe_pct',
    width: 100,
    render: v => <RoeCell value={v} />,
    sorter: (a, b) => parseFloat(a.roe_pct || 0) - parseFloat(b.roe_pct || 0),
  },
]

const groupColumns = [
  {
    title: '开仓时间',
    dataIndex: 'open_time',
    key: 'open_time',
    width: 130,
    render: v => v ? v.slice(5, 16) : '-',
    sorter: (a, b) => (a.open_time || '').localeCompare(b.open_time || ''),
    defaultSortOrder: 'descend',
  },
  {
    title: '方向',
    dataIndex: 'side',
    key: 'side',
    width: 160,
    render: v => {
      let color = 'default'
      if (v?.includes('涨幅') && v?.includes('空')) color = 'green'
      else if (v?.includes('涨幅') && v?.includes('多')) color = 'red'
      else if (v?.includes('跌幅') && v?.includes('空')) color = 'cyan'
      else if (v?.includes('跌幅') && v?.includes('多')) color = 'orange'
      return <Tag color={color}>{v}</Tag>
    },
    filters: [
      { text: '涨幅榜-空（有过滤）', value: '涨幅榜-空（有过滤）' },
      { text: '涨幅榜-空（无过滤）', value: '涨幅榜-空（无过滤）' },
      { text: '涨幅榜-多（有过滤）', value: '涨幅榜-多（有过滤）' },
      { text: '涨幅榜-多（无过滤）', value: '涨幅榜-多（无过滤）' },
      { text: '跌幅榜-空（有过滤）', value: '跌幅榜-空（有过滤）' },
      { text: '跌幅榜-空（无过滤）', value: '跌幅榜-空（无过滤）' },
      { text: '跌幅榜-多（有过滤）', value: '跌幅榜-多（有过滤）' },
      { text: '跌幅榜-多（无过滤）', value: '跌幅榜-多（无过滤）' },
    ],
    onFilter: (value, record) => record.side === value,
  },
  {
    title: '笔数',
    dataIndex: 'n_orders',
    key: 'n_orders',
    width: 70,
  },
  {
    title: '触发类型',
    key: 'trigger_kind',
    width: 100,
    render: (_, r) => {
      if (r.n_hit > 0) return <Tag color="gold">+10u 触发</Tag>
      if (r.n_timed > 0) return <Tag color="default">4h 定平</Tag>
      return <Tag>持仓中</Tag>
    },
    filters: [
      { text: '+10u 触发', value: 'hit' },
      { text: '4h 定平', value: 'timed' },
    ],
    onFilter: (value, r) => value === 'hit' ? r.n_hit > 0 : r.n_timed > 0,
  },
  {
    title: '实际平仓 PnL',
    dataIndex: 'sum_pnl_actual',
    key: 'sum_pnl_actual',
    width: 130,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => parseFloat(a.sum_pnl_actual || 0) - parseFloat(b.sum_pnl_actual || 0),
  },
  {
    title: '走完4h PnL',
    dataIndex: 'sum_pnl_if_held',
    key: 'sum_pnl_if_held',
    width: 130,
    render: (v, r) => {
      if (r.n_hit === 0) return <span style={{ color: '#bbb' }}>同上</span>
      return <PnlCell value={v} />
    },
    sorter: (a, b) => parseFloat(a.sum_pnl_if_held || 0) - parseFloat(b.sum_pnl_if_held || 0),
  },
  {
    title: '+10u vs 走完',
    key: 'diff',
    width: 120,
    render: (_, r) => {
      if (r.n_hit === 0) return <span style={{ color: '#bbb' }}>-</span>
      const a = parseFloat(r.sum_pnl_actual || 0)
      const b = parseFloat(r.sum_pnl_if_held || 0)
      const d = a - b
      const color = d >= 0 ? '#3f8600' : '#cf1322'
      return <span style={{ color, fontWeight: 500 }}>{d >= 0 ? '+' : ''}{d.toFixed(2)}</span>
    },
  },
]

const SIDE_GROUPS = [
  { label: '涨幅榜-空', filtered: '涨幅榜-空（有过滤）', unfiltered: '涨幅榜-空（无过滤）' },
  { label: '涨幅榜-多', filtered: '涨幅榜-多（有过滤）', unfiltered: '涨幅榜-多（无过滤）' },
  { label: '跌幅榜-空', filtered: '跌幅榜-空（有过滤）', unfiltered: '跌幅榜-空（无过滤）' },
  { label: '跌幅榜-多', filtered: '跌幅榜-多（有过滤）', unfiltered: '跌幅榜-多（无过滤）' },
]

export default function VirtualLog4h() {
  const [orders, setOrders] = useState([])
  const [groups, setGroups] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      axios.get('/api/virtual_log_4h'),
      axios.get('/api/virtual_4h_groups'),
    ]).then(([res1, res2]) => {
      const rows = res1.data.map((r, i) => ({ ...r, key: i })).reverse()
      orderColumns.find(c => c.key === 'symbol').filters =
        [...new Set(rows.map(r => r.symbol))].map(s => ({ text: s, value: s }))
      setOrders(rows)
      setGroups(res2.data.map((g, i) => ({ ...g, key: i })))
    }).finally(() => setLoading(false))
  }, [])

  const closed = orders.filter(r => r.close_time)
  const sumPnl = arr => arr.reduce((acc, r) => acc + parseFloat(r.unrealized_pnl || 0), 0)

  const totalPnl = sumPnl(closed)
  const nHit = closed.filter(r => r.close_reason === '组内+10u').length
  const nTimed = closed.filter(r => r.close_reason === '4h_timed').length

  // 组级别对照统计
  const closedGroups = groups.filter(g => g.n_hit > 0 || g.n_timed > 0)
  const sumActual = closedGroups.reduce((a, g) => a + parseFloat(g.sum_pnl_actual || 0), 0)
  const sumIfHeld = closedGroups.reduce((a, g) => a + parseFloat(g.sum_pnl_if_held || 0), 0)
  const nHitGroups = closedGroups.filter(g => g.n_hit > 0).length
  const nTimedGroups = closedGroups.filter(g => g.n_timed > 0 && g.n_hit === 0).length

  return (
    <div>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="总盈亏(实际)" value={Math.abs(totalPnl).toFixed(2)} suffix="U"
              prefix={totalPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: totalPnl >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="若都走完4h(对照)" value={Math.abs(sumIfHeld).toFixed(2)} suffix="U"
              prefix={sumIfHeld >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: sumIfHeld >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="+10u触发组" value={nHitGroups} suffix={`/ ${closedGroups.length}`} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="4h定平组" value={nTimedGroups} suffix={`/ ${closedGroups.length}`} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {SIDE_GROUPS.map(g => {
          const fPnl = sumPnl(closed.filter(r => r.side === g.filtered))
          const uPnl = sumPnl(closed.filter(r => r.side === g.unfiltered))
          return (
            <Col xs={24} sm={12} md={6} key={g.label}>
              <Card size="small" title={g.label}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ color: '#999', fontSize: 12 }}>有过滤</div>
                    <b style={{ color: pnlColor(fPnl), fontSize: 16 }}>{fPnl >= 0 ? '+' : ''}{fPnl.toFixed(1)} U</b>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ color: '#999', fontSize: 12 }}>无过滤</div>
                    <b style={{ color: pnlColor(uPnl), fontSize: 16 }}>{uPnl >= 0 ? '+' : ''}{uPnl.toFixed(1)} U</b>
                  </div>
                </div>
              </Card>
            </Col>
          )
        })}
      </Row>

      <Card size="small">
        <Spin spinning={loading}>
          <Tabs
            defaultActiveKey="groups"
            items={[
              {
                key: 'groups',
                label: '按组对照（+10u vs 走完4h）',
                children: (
                  <Table
                    columns={groupColumns}
                    dataSource={groups}
                    pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200] }}
                    scroll={{ x: 'max-content' }}
                    size="small"
                    rowClassName={r => {
                      const a = parseFloat(r.sum_pnl_actual || 0)
                      if (a > 0) return 'row-profit'
                      if (a < 0) return 'row-loss'
                      return ''
                    }}
                  />
                ),
              },
              {
                key: 'orders',
                label: `逐笔明细 (${orders.length})`,
                children: (
                  <Table
                    columns={orderColumns}
                    dataSource={orders}
                    pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], showTotal: t => `共 ${t} 条` }}
                    scroll={{ x: 'max-content' }}
                    size="small"
                    rowClassName={record => {
                      if (!record.close_time) return 'row-open'
                      const pnl = parseFloat(record.unrealized_pnl)
                      if (pnl > 0) return 'row-profit'
                      if (pnl < 0) return 'row-loss'
                      return ''
                    }}
                  />
                ),
              },
            ]}
          />
        </Spin>
      </Card>

      <style>{`
        .row-profit td { background: #f6ffed !important; }
        .row-loss   td { background: #fff1f0 !important; }
        .row-open   td { background: #e6f4ff !important; }
        @media (max-width: 768px) {
          .ant-table-cell { white-space: normal !important; word-break: break-all; }
        }
      `}</style>
    </div>
  )
}
