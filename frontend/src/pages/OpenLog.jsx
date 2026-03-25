import { useEffect, useState } from 'react'
import { Table, Card, Tag, Spin, Row, Col, Statistic } from 'antd'
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

const columns = [
  {
    title: '开仓时间',
    dataIndex: 'open_time',
    key: 'open_time',
    width: 160,
    fixed: 'left',
  },
  {
    title: '平仓时间',
    dataIndex: 'close_time',
    key: 'close_time',
    width: 160,
    render: v => v || <span style={{ color: '#bbb' }}>持仓中</span>,
  },
  {
    title: '币种',
    dataIndex: 'symbol',
    key: 'symbol',
    width: 140,
    fixed: 'left',
    filters: [],
    onFilter: (value, record) => record.symbol === value,
  },
  {
    title: '方向',
    dataIndex: 'side',
    key: 'side',
    width: 70,
    render: v => <Tag color={v === '空' ? 'green' : 'red'}>{v}</Tag>,
    filters: [
      { text: '多', value: '多' },
      { text: '空', value: '空' },
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
    title: 'BTC涨跌',
    dataIndex: 'btc_change_pct',
    key: 'btc_change_pct',
    width: 90,
    render: v => {
      const n = parseFloat(v)
      if (isNaN(n)) return '-'
      return <span style={{ color: pnlColor(v) }}>{n >= 0 ? '+' : ''}{n.toFixed(2)}%</span>
    },
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
  {
    title: '杠杆',
    dataIndex: 'leverage',
    key: 'leverage',
    width: 70,
    render: v => v ? `${v}x` : '-',
  },
]

export default function OpenLog() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get('/api/open_log').then(res => {
      const rows = res.data
        .map((r, i) => ({ ...r, key: i }))
        .reverse()
      // 动态生成币种筛选项
      const symbols = [...new Set(rows.map(r => r.symbol))]
      columns.find(c => c.key === 'symbol').filters = symbols.map(s => ({ text: s, value: s }))
      setData(rows)
    }).finally(() => setLoading(false))
  }, [])

  // 统计
  const closed = data.filter(r => r.close_time)
  const longClosed  = closed.filter(r => r.side === '多')
  const shortClosed = closed.filter(r => r.side === '空')
  const sum = arr => arr.reduce((acc, r) => acc + parseFloat(r.unrealized_pnl || 0), 0)
  const winRate = arr => arr.length ? (arr.filter(r => parseFloat(r.unrealized_pnl) > 0).length / arr.length * 100).toFixed(0) : 0

  const totalPnl  = sum(closed)
  const longPnl   = sum(longClosed)
  const shortPnl  = sum(shortClosed)

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Card size="small">
            <Statistic title="总盈亏" value={Math.abs(totalPnl).toFixed(2)} suffix="U"
              prefix={totalPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: totalPnl >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="多单盈亏" value={Math.abs(longPnl).toFixed(2)} suffix="U"
              prefix={longPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: longPnl >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="空单盈亏" value={Math.abs(shortPnl).toFixed(2)} suffix="U"
              prefix={shortPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: shortPnl >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="多单胜率" value={winRate(longClosed)} suffix="%" />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="空单胜率" value={winRate(shortClosed)} suffix="%" />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="总交易笔数" value={closed.length} suffix="笔" />
          </Card>
        </Col>
      </Row>

      <Card size="small">
        <Spin spinning={loading}>
          <Table
            columns={columns}
            dataSource={data}
            pagination={{ pageSize: 20, showSizeChanger: true }}
            scroll={{ x: 1200 }}
            size="small"
            rowClassName={record => {
              if (!record.close_time) return 'row-open'
              const pnl = parseFloat(record.unrealized_pnl)
              if (pnl > 0) return 'row-profit'
              if (pnl < 0) return 'row-loss'
              return ''
            }}
          />
        </Spin>
      </Card>

      <style>{`
        .row-profit td { background: #f6ffed !important; }
        .row-loss   td { background: #fff1f0 !important; }
        .row-open   td { background: #e6f4ff !important; }
      `}</style>
    </div>
  )
}
