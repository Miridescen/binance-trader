import { useEffect, useState } from 'react'
import { Table, Card, Statistic, Row, Col, Typography, Tag, Spin } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined, ReloadOutlined } from '@ant-design/icons'
import axios from 'axios'
import 'antd/dist/reset.css'

const { Title } = Typography

function pnlColor(val) {
  const n = parseFloat(val)
  if (n > 0) return '#3f8600'
  if (n < 0) return '#cf1322'
  return '#999'
}

function PnlCell({ value }) {
  const n = parseFloat(value)
  return (
    <span style={{ color: pnlColor(value), fontWeight: 500 }}>
      {n >= 0 ? '+' : ''}{n.toFixed(2)}
    </span>
  )
}

const columns = [
  {
    title: '时间',
    dataIndex: 'time',
    key: 'time',
    width: 160,
    fixed: 'left',
  },
  {
    title: '账户余额',
    dataIndex: 'balance_usdt',
    key: 'balance_usdt',
    width: 110,
    render: v => <span style={{ fontWeight: 500 }}>{parseFloat(v).toFixed(2)}</span>,
    sorter: (a, b) => parseFloat(a.balance_usdt) - parseFloat(b.balance_usdt),
  },
  {
    title: '多单数',
    dataIndex: 'long_count',
    key: 'long_count',
    width: 80,
    render: v => <Tag color="red">{v}</Tag>,
  },
  {
    title: '多单盈亏',
    dataIndex: 'long_pnl',
    key: 'long_pnl',
    width: 110,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => parseFloat(a.long_pnl) - parseFloat(b.long_pnl),
  },
  {
    title: '空单数',
    dataIndex: 'short_count',
    key: 'short_count',
    width: 80,
    render: v => <Tag color="green">{v}</Tag>,
  },
  {
    title: '空单盈亏',
    dataIndex: 'short_pnl',
    key: 'short_pnl',
    width: 110,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => parseFloat(a.short_pnl) - parseFloat(b.short_pnl),
  },
  {
    title: '总盈亏',
    dataIndex: 'total_pnl',
    key: 'total_pnl',
    width: 110,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => parseFloat(a.total_pnl) - parseFloat(b.total_pnl),
  },
  {
    title: '资金费率',
    dataIndex: 'funding_fee',
    key: 'funding_fee',
    width: 100,
    render: v => {
      const n = parseFloat(v)
      return <span style={{ color: pnlColor(v) }}>{n >= 0 ? '+' : ''}{n.toFixed(4)}</span>
    },
  },
]

export default function App() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await axios.get('/api/positions')
      const rows = res.data.map((r, i) => ({ ...r, key: i }))
      setData(rows.reverse()) // 最新在前
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const timer = setInterval(fetchData, 60_000) // 每分钟刷新
    return () => clearInterval(timer)
  }, [])

  // 最新一条数据用于顶部统计卡片
  const latest = data[0] || {}
  const balance = parseFloat(latest.balance_usdt || 0)
  const totalPnl = parseFloat(latest.total_pnl || 0)
  const longPnl = parseFloat(latest.long_pnl || 0)
  const shortPnl = parseFloat(latest.short_pnl || 0)

  return (
    <div style={{ padding: 24, minHeight: '100vh' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>📊 持仓监控</Title>
        <span style={{ color: '#999', fontSize: 13 }}>
          <ReloadOutlined
            style={{ cursor: 'pointer', marginRight: 6 }}
            onClick={fetchData}
          />
          最后更新：{lastUpdated || '-'}
        </span>
      </div>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="账户余额"
              value={balance.toFixed(2)}
              suffix="USDT"
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="当前总浮盈亏"
              value={Math.abs(totalPnl).toFixed(2)}
              prefix={totalPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              suffix="USDT"
              valueStyle={{ color: totalPnl >= 0 ? '#3f8600' : '#cf1322' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="多单浮盈亏"
              value={Math.abs(longPnl).toFixed(2)}
              prefix={longPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              suffix="USDT"
              valueStyle={{ color: longPnl >= 0 ? '#3f8600' : '#cf1322' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="空单浮盈亏"
              value={Math.abs(shortPnl).toFixed(2)}
              prefix={shortPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              suffix="USDT"
              valueStyle={{ color: shortPnl >= 0 ? '#3f8600' : '#cf1322' }}
            />
          </Card>
        </Col>
      </Row>

      <Card size="small">
        <Spin spinning={loading}>
          <Table
            columns={columns}
            dataSource={data}
            pagination={{ pageSize: 24, showSizeChanger: true }}
            scroll={{ x: 900 }}
            size="small"
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
