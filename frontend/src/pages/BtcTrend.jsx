import { useEffect, useState } from 'react'
import { Card, Table, Spin, Tag, Row, Col, Statistic, Divider } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined, ReloadOutlined } from '@ant-design/icons'
import axios from 'axios'

function pnlColor(n) {
  if (n > 0) return '#3f8600'
  if (n < 0) return '#cf1322'
  return '#999'
}

const signalColor = { '多': 'red', '空': 'green', '观望': 'default' }

const indicatorColumns = [
  { title: '时间', dataIndex: 'time', key: 'time', width: 130, render: v => v?.slice(5, 16) },
  { title: 'BTC价格', dataIndex: 'price', key: 'price', width: 100, render: v => v ? parseFloat(v).toFixed(2) : '-' },
  { title: 'SMA200', dataIndex: 'sma200', key: 'sma200', width: 100, render: v => v ? parseFloat(v).toFixed(2) : '-' },
  {
    title: '价格/SMA200', key: 'price_vs_sma', width: 90,
    render: (_, r) => {
      if (!r.price || !r.sma200) return '-'
      const above = parseFloat(r.price) > parseFloat(r.sma200)
      return <Tag color={above ? 'red' : 'green'}>{above ? '上方' : '下方'}</Tag>
    },
  },
  { title: 'RSI周', dataIndex: 'rsi_weekly', key: 'rsi_weekly', width: 80, render: v => v ? parseFloat(v).toFixed(1) : '-' },
  {
    title: '资金费率', dataIndex: 'funding_rate', key: 'funding_rate', width: 100,
    render: v => {
      if (v == null) return '-'
      const n = parseFloat(v)
      return <span style={{ color: pnlColor(n) }}>{(n * 100).toFixed(4)}%</span>
    },
  },
  {
    title: '恐惧贪婪', key: 'fng', width: 100,
    render: (_, r) => {
      const v = r.fear_greed
      if (v == null) return '-'
      const color = v <= 25 ? '#cf1322' : v <= 45 ? '#fa8c16' : v <= 55 ? '#999' : v <= 75 ? '#52c41a' : '#3f8600'
      return <span style={{ color, fontWeight: 500 }}>{v} {r.fear_greed_label}</span>
    },
  },
  {
    title: '信号', dataIndex: 'signal', key: 'signal', width: 70,
    render: v => <Tag color={signalColor[v] || 'default'}>{v}</Tag>,
  },
]

const signalColumns = [
  { title: '开仓时间', dataIndex: 'open_time', key: 'open_time', width: 130, render: v => v?.slice(5, 16) },
  { title: '平仓时间', dataIndex: 'close_time', key: 'close_time', width: 130,
    render: v => v ? v.slice(5, 16) : <Tag color="blue">持仓中</Tag> },
  { title: '方向', dataIndex: 'side', key: 'side', width: 60, render: v => <Tag color={signalColor[v]}>{v}</Tag> },
  { title: '入场价', dataIndex: 'entry_price', key: 'entry_price', width: 100, render: v => v ? parseFloat(v).toFixed(2) : '-' },
  { title: '平仓价', dataIndex: 'close_price', key: 'close_price', width: 100, render: v => v ? parseFloat(v).toFixed(2) : '-' },
  { title: '信号原因', dataIndex: 'signal_reason', key: 'signal_reason', width: 180 },
  {
    title: '盈亏', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 90,
    render: v => {
      if (v == null) return '-'
      const n = parseFloat(v)
      return <span style={{ color: pnlColor(n), fontWeight: 500 }}>{n >= 0 ? '+' : ''}{n.toFixed(2)} U</span>
    },
    sorter: (a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0),
  },
  {
    title: 'ROE', dataIndex: 'roe_pct', key: 'roe_pct', width: 80,
    render: v => {
      if (v == null) return '-'
      const n = parseFloat(v)
      return <span style={{ color: pnlColor(n), fontWeight: 500 }}>{n >= 0 ? '+' : ''}{n.toFixed(1)}%</span>
    },
  },
]

export default function BtcTrend() {
  const [loading, setLoading] = useState(true)
  const [indicators, setIndicators] = useState([])
  const [signals, setSignals] = useState([])

  const fetchAll = () => {
    setLoading(true)
    Promise.all([
      axios.get('/api/btc_indicators'),
      axios.get('/api/btc_signals'),
    ]).then(([r1, r2]) => {
      setIndicators(r1.data.map((r, i) => ({ ...r, key: i })))
      setSignals(r2.data.map((r, i) => ({ ...r, key: i })))
    }).finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchAll()
    const t = setInterval(fetchAll, 60_000)
    return () => clearInterval(t)
  }, [])

  const latest = indicators[0] || {}
  const openPosition = signals.find(r => !r.close_time)
  const closedSignals = signals.filter(r => r.close_time)
  const totalPnl = closedSignals.reduce((acc, r) => acc + (r.unrealized_pnl || 0), 0)
  const wins = closedSignals.filter(r => (r.unrealized_pnl || 0) > 0).length

  return (
    <Spin spinning={loading}>
      <div style={{ textAlign: 'right', marginBottom: 8, color: '#999', fontSize: 13 }}>
        <ReloadOutlined style={{ cursor: 'pointer', marginRight: 6 }} onClick={fetchAll} />
      </div>

      {/* 当前状态卡片 */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="BTC 价格" value={latest.price ? parseFloat(latest.price).toFixed(2) : '-'} suffix="U" />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="当前信号" value={latest.signal || '-'}
              valueStyle={{ color: latest.signal === '多' ? '#cf1322' : latest.signal === '空' ? '#3f8600' : '#999' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="RSI 周线" value={latest.rsi_weekly ? parseFloat(latest.rsi_weekly).toFixed(1) : '-'}
              valueStyle={{ color: parseFloat(latest.rsi_weekly) > 50 ? '#cf1322' : '#3f8600' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="恐惧贪婪" value={latest.fear_greed ?? '-'} suffix={latest.fear_greed_label || ''} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="累计盈亏" value={Math.abs(totalPnl).toFixed(2)} suffix="U"
              prefix={totalPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: pnlColor(totalPnl) }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="胜率" value={closedSignals.length ? `${wins}/${closedSignals.length}` : '-'} />
          </Card>
        </Col>
        {openPosition && (
          <Col xs={24} sm={16} md={12}>
            <Card size="small" title={<span>当前持仓 <Tag color={signalColor[openPosition.side]}>{openPosition.side}</Tag></span>}>
              <span>入场 {parseFloat(openPosition.entry_price).toFixed(2)}</span>
              <span style={{ marginLeft: 16 }}>开仓时间 {openPosition.open_time?.slice(5, 16)}</span>
            </Card>
          </Col>
        )}
      </Row>

      {/* 交易记录 */}
      <Card size="small" title="信号交易记录" style={{ marginBottom: 16 }}>
        <Table columns={signalColumns} dataSource={signals}
          pagination={false} scroll={{ x: 'max-content' }} size="small"
          rowClassName={r => !r.close_time ? 'row-open' : (r.unrealized_pnl || 0) > 0 ? 'row-profit' : 'row-loss'} />
      </Card>

      {/* 指标历史 */}
      <Card size="small" title="指标历史">
        <Table columns={indicatorColumns} dataSource={indicators}
          pagination={{ pageSize: 50 }} scroll={{ x: 'max-content' }} size="small" />
      </Card>

      <style>{`
        .row-profit td { background: #f6ffed !important; }
        .row-loss td { background: #fff1f0 !important; }
        .row-open td { background: #e6f4ff !important; }
      `}</style>
    </Spin>
  )
}
