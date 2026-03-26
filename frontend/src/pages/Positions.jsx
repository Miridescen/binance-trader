import { useEffect, useState } from 'react'
import { Table, Card, Statistic, Row, Col, Spin } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined, ReloadOutlined } from '@ant-design/icons'
import { Tag } from 'antd'
import axios from 'axios'

function pnlColor(val) {
  const n = parseFloat(val)
  if (n > 0) return '#3f8600'
  if (n < 0) return '#cf1322'
  return '#999'
}

function PnlCell({ value }) {
  const n = parseFloat(value)
  return <span style={{ color: pnlColor(value), fontWeight: 500 }}>{n >= 0 ? '+' : ''}{n.toFixed(2)}</span>
}

const columns = [
  { title: '时间', dataIndex: 'time', key: 'time', width: 160, fixed: 'left' },
  {
    title: '账户余额', dataIndex: 'balance_usdt', key: 'balance_usdt', width: 110,
    render: v => <span style={{ fontWeight: 500 }}>{parseFloat(v).toFixed(2)}</span>,
    sorter: (a, b) => parseFloat(a.balance_usdt) - parseFloat(b.balance_usdt),
  },
  { title: '多单数', dataIndex: 'long_count', key: 'long_count', width: 80, render: v => <Tag color="red">{v}</Tag> },
  {
    title: '多单盈亏', dataIndex: 'long_pnl', key: 'long_pnl', width: 110,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => parseFloat(a.long_pnl) - parseFloat(b.long_pnl),
  },
  { title: '空单数', dataIndex: 'short_count', key: 'short_count', width: 80, render: v => <Tag color="green">{v}</Tag> },
  {
    title: '空单盈亏', dataIndex: 'short_pnl', key: 'short_pnl', width: 110,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => parseFloat(a.short_pnl) - parseFloat(b.short_pnl),
  },
  {
    title: '总盈亏', dataIndex: 'total_pnl', key: 'total_pnl', width: 110,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => parseFloat(a.total_pnl) - parseFloat(b.total_pnl),
  },
  {
    title: '资金费率', dataIndex: 'funding_fee', key: 'funding_fee', width: 100,
    render: v => {
      const n = parseFloat(v)
      return <span style={{ color: pnlColor(v) }}>{n >= 0 ? '+' : ''}{n.toFixed(4)}</span>
    },
  },
]

export default function Positions() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [rt, setRt] = useState(null)           // 实时数据
  const [rtUpdated, setRtUpdated] = useState(null)
  const [pagination, setPagination] = useState({ current: 1, pageSize: 24 })

  // 历史表格数据（每分钟刷新）
  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await axios.get('/api/positions')
      setData(res.data.map((r, i) => ({ ...r, key: i })).reverse())
    } finally {
      setLoading(false)
    }
  }

  // 实时统计卡片（每5分钟刷新）
  const fetchRealtime = async () => {
    try {
      const res = await axios.get('/api/realtime')
      if (!res.data.error) {
        setRt(res.data)
        setRtUpdated(new Date().toLocaleTimeString())
      }
    } catch (_) {}
  }

  useEffect(() => {
    fetchData()
    fetchRealtime()
    const t1 = setInterval(fetchData, 60_000)
    const t2 = setInterval(fetchRealtime, 300_000)
    return () => { clearInterval(t1); clearInterval(t2) }
  }, [])

  const balance   = rt ? rt.balance   : 0
  const totalPnl  = rt ? rt.total_pnl : 0
  const longPnl   = rt ? rt.long_pnl  : 0
  const shortPnl  = rt ? rt.short_pnl : 0

  return (
    <div>
      <div style={{ textAlign: 'right', marginBottom: 8, color: '#999', fontSize: 13 }}>
        <ReloadOutlined style={{ cursor: 'pointer', marginRight: 6 }} onClick={fetchRealtime} />
        实时数据更新：{rtUpdated || '-'}
      </div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="账户余额（实时）" value={balance.toFixed(2)} suffix="USDT"
              valueStyle={{ color: '#1677ff' }}
              formatter={v => rt ? v : <span style={{ color: '#bbb' }}>-</span>} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="总浮盈亏（实时）" value={Math.abs(totalPnl).toFixed(2)}
              prefix={totalPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />} suffix="USDT"
              valueStyle={{ color: totalPnl >= 0 ? '#3f8600' : '#cf1322' }}
              formatter={v => rt ? v : <span style={{ color: '#bbb' }}>-</span>} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="多单浮盈亏（实时）" value={Math.abs(longPnl).toFixed(2)}
              prefix={longPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />} suffix="USDT"
              valueStyle={{ color: longPnl >= 0 ? '#3f8600' : '#cf1322' }}
              formatter={v => rt ? v : <span style={{ color: '#bbb' }}>-</span>} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="空单浮盈亏（实时）" value={Math.abs(shortPnl).toFixed(2)}
              prefix={shortPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />} suffix="USDT"
              valueStyle={{ color: shortPnl >= 0 ? '#3f8600' : '#cf1322' }}
              formatter={v => rt ? v : <span style={{ color: '#bbb' }}>-</span>} />
          </Card>
        </Col>
      </Row>
      <Card size="small">
        <Spin spinning={loading}>
          <Table columns={columns} dataSource={data}
            pagination={{
              ...pagination,
              showSizeChanger: true,
              pageSizeOptions: [10, 24, 50, 100],
              showTotal: total => `共 ${total} 条`,
              onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
            }}
            scroll={{ x: 900 }} size="small"
            rowClassName={record => {
              const pnl = parseFloat(record.total_pnl)
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
      `}</style>
    </div>
  )
}
