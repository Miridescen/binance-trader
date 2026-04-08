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
    width: 100,
    render: v => v ? v.slice(5, 16) : '-',
  },
  {
    title: '平仓时间',
    dataIndex: 'close_time',
    key: 'close_time',
    width: 100,
    render: v => v ? v.slice(5, 16) : <span style={{ color: '#bbb' }}>持仓中</span>,
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
    width: 140,
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
    title: '有市值',
    dataIndex: 'has_mcap',
    key: 'has_mcap',
    width: 70,
    render: v => v === '1' ? <Tag color="blue">是</Tag> : <Tag color="default">否</Tag>,
    filters: [
      { text: '有', value: '1' },
      { text: '无', value: '0' },
    ],
    onFilter: (value, record) => record.has_mcap === value,
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
    title: '资金费率',
    dataIndex: 'symbol_funding_rate',
    key: 'symbol_funding_rate',
    width: 90,
    render: v => {
      const n = parseFloat(v)
      if (isNaN(n)) return '-'
      const pct = (n * 100).toFixed(4)
      return <span style={{ color: n >= 0 ? '#cf1322' : '#3f8600' }}>{n >= 0 ? '+' : ''}{pct}%</span>
    },
    sorter: (a, b) => parseFloat(a.symbol_funding_rate || 0) - parseFloat(b.symbol_funding_rate || 0),
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

export default function VirtualLog() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [pagination, setPagination] = useState({ current: 1, pageSize: 50 })

  useEffect(() => {
    axios.get('/api/virtual_log').then(res => {
      const rows = res.data
        .map((r, i) => ({ ...r, key: i }))
        .reverse()
      columns.find(c => c.key === 'symbol').filters = [...new Set(rows.map(r => r.symbol))].map(s => ({ text: s, value: s }))
      setData(rows)
    }).finally(() => setLoading(false))
  }, [])

  const closed = data.filter(r => r.close_time)
  const sumPnl = arr => arr.reduce((acc, r) => acc + parseFloat(r.unrealized_pnl || 0), 0)

  const groups = [
    { label: '涨幅榜-空', filtered: '涨幅榜-空（有过滤）', unfiltered: '涨幅榜-空（无过滤）' },
    { label: '涨幅榜-多', filtered: '涨幅榜-多（有过滤）', unfiltered: '涨幅榜-多（无过滤）' },
    { label: '跌幅榜-空', filtered: '跌幅榜-空（有过滤）', unfiltered: '跌幅榜-空（无过滤）' },
    { label: '跌幅榜-多', filtered: '跌幅榜-多（有过滤）', unfiltered: '跌幅榜-多（无过滤）' },
  ]
  const totalPnl = sumPnl(closed)

  return (
    <div>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic title="总盈亏(虚拟)" value={Math.abs(totalPnl).toFixed(2)} suffix="U"
              prefix={totalPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: totalPnl >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic title="总交易笔数" value={closed.length} suffix="笔" />
          </Card>
        </Col>
      </Row>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {groups.map(g => {
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
          <Table
            columns={columns}
            dataSource={data}
            pagination={{
              ...pagination,
              showSizeChanger: true,
              pageSizeOptions: [20, 50, 100, 200],
              showTotal: total => `共 ${total} 条`,
              onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
            }}
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
