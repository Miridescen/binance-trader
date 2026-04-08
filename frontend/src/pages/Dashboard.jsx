import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Table, Tag, Spin, Divider } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined, ReloadOutlined, WalletOutlined, DollarOutlined, FundOutlined } from '@ant-design/icons'
import axios from 'axios'

function pnlColor(n) {
  if (n > 0) return '#3f8600'
  if (n < 0) return '#cf1322'
  return '#999'
}

function PnlCell({ value }) {
  const n = parseFloat(value)
  if (isNaN(n)) return <span style={{ color: '#999' }}>-</span>
  return <span style={{ color: pnlColor(n), fontWeight: 500 }}>{n >= 0 ? '+' : ''}{n.toFixed(2)}</span>
}

function RoeCell({ value }) {
  const n = parseFloat(value)
  if (isNaN(n)) return <span style={{ color: '#999' }}>-</span>
  return <span style={{ color: pnlColor(n), fontWeight: 500 }}>{n >= 0 ? '+' : ''}{n.toFixed(2)}%</span>
}

const realColumns = [
  { title: '币种', dataIndex: 'symbol', key: 'symbol', width: 110 },
  { title: '方向', dataIndex: 'side', key: 'side', width: 140, render: v => {
    let color = 'default'
    if (v?.includes('涨幅') && v?.includes('空')) color = 'green'
    else if (v?.includes('跌幅') && v?.includes('空')) color = 'cyan'
    return <Tag color={color}>{v}</Tag>
  }},
  { title: '入场价', dataIndex: 'entry_price', key: 'entry_price', width: 90, render: v => v ? parseFloat(v).toFixed(4) : '-' },
  { title: '标记价', dataIndex: 'mark_price', key: 'mark_price', width: 90, render: v => v ? parseFloat(v).toFixed(4) : '-' },
  { title: '盈亏', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 90, render: v => <PnlCell value={v} />, sorter: (a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0) },
  { title: 'ROE', dataIndex: 'roe_pct', key: 'roe_pct', width: 80, render: v => <RoeCell value={v} />, sorter: (a, b) => (a.roe_pct || 0) - (b.roe_pct || 0) },
]

const virtColumns = [
  { title: '币种', dataIndex: 'symbol', key: 'symbol', width: 110 },
  { title: '入场价', dataIndex: 'entry_price', key: 'entry_price', width: 90, render: v => v ? parseFloat(v).toFixed(4) : '-' },
  { title: '标记价', dataIndex: 'mark_price', key: 'mark_price', width: 90, render: v => v ? parseFloat(v).toFixed(4) : '-' },
  { title: '盈亏', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 80, render: v => <PnlCell value={v} />, sorter: (a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0) },
  { title: 'ROE', dataIndex: 'roe_pct', key: 'roe_pct', width: 80, render: v => <RoeCell value={v} />, sorter: (a, b) => (a.roe_pct || 0) - (b.roe_pct || 0) },
]

export default function Dashboard() {
  const [rt, setRt] = useState(null)
  const [board, setBoard] = useState(null)
  const [loading, setLoading] = useState(true)
  const [updated, setUpdated] = useState(null)

  const fetchAll = async () => {
    setLoading(true)
    try {
      const [r1, r2] = await Promise.all([
        axios.get('/api/realtime'),
        axios.get('/api/dashboard'),
      ])
      if (!r1.data.error) setRt(r1.data)
      if (!r2.data.error) setBoard(r2.data)
      setUpdated(new Date().toLocaleTimeString())
    } catch (e) {}
    setLoading(false)
  }

  useEffect(() => {
    fetchAll()
    const t = setInterval(fetchAll, 60_000)
    return () => clearInterval(t)
  }, [])

  const balance = rt?.balance || 0
  const marginUsed = rt?.margin_used || 0
  const totalPnl = rt?.total_pnl || 0
  const positions = rt?.positions || []
  const gainerShorts = positions.filter(r => r.side === '涨幅榜-空（有过滤）')
  const loserShorts = positions.filter(r => r.side === '跌幅榜-空（有过滤）')
  const gainerShortPnl = gainerShorts.reduce((acc, r) => acc + (r.unrealized_pnl || 0), 0)
  const loserShortPnl = loserShorts.reduce((acc, r) => acc + (r.unrealized_pnl || 0), 0)

  const monitor = board?.monitor
  const realDetail = board?.real_detail || []
  const realTime = board?.real_detail_time || ''
  const virtDetail = board?.virtual_detail || []
  const virtTime = board?.virtual_detail_time || ''

  const sumPnl = arr => arr.reduce((acc, r) => acc + (r.unrealized_pnl || 0), 0)
  // 虚拟盘无过滤组（与实盘对照用）
  const virtGainerShort = virtDetail.filter(r => r.side === '涨幅榜-空（无过滤）')
  const virtLoserShort  = virtDetail.filter(r => r.side === '跌幅榜-空（无过滤）')
  const virtGainerShortPnl = sumPnl(virtGainerShort)
  const virtLoserShortPnl  = sumPnl(virtLoserShort)

  return (
    <Spin spinning={loading}>
      <div style={{ textAlign: 'right', marginBottom: 8, color: '#999', fontSize: 13 }}>
        <ReloadOutlined style={{ cursor: 'pointer', marginRight: 6 }} onClick={fetchAll} />
        更新：{updated || '-'}
      </div>

      {/* 账户卡片 */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="账户余额" value={balance} precision={2} suffix="U"
              prefix={<WalletOutlined />} valueStyle={{ color: '#1677ff' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="保证金占用" value={marginUsed} precision={2} suffix="U"
              prefix={<DollarOutlined />} valueStyle={{ color: '#fa8c16' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="实时浮盈亏" value={Math.abs(totalPnl)} precision={2} suffix="U"
              prefix={totalPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: pnlColor(totalPnl) }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title={`涨幅榜空 (${gainerShorts.length}笔)`} value={Math.abs(gainerShortPnl)} precision={2} suffix="U"
              prefix={gainerShortPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: pnlColor(gainerShortPnl) }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title={`跌幅榜空 (${loserShorts.length}笔)`} value={Math.abs(loserShortPnl)} precision={2} suffix="U"
              prefix={loserShortPnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: pnlColor(loserShortPnl) }} />
          </Card>
        </Col>
      </Row>

      {/* 最新持仓监控 */}
      {monitor && (
        <Card size="small" title={`持仓监控 ${(monitor.time || '').slice(5, 16)}`} style={{ marginBottom: 16 }}>
          <Row gutter={[12, 8]}>
            <Col xs={8} sm={6}><span style={{ color: '#999' }}>余额</span> <b>{parseFloat(monitor.balance_usdt).toFixed(2)}</b></Col>
            <Col xs={8} sm={6}><span style={{ color: '#999' }}>空单</span> <b>{monitor.short_count}</b>笔 <span style={{ color: pnlColor(parseFloat(monitor.short_pnl)) }}>{parseFloat(monitor.short_pnl) >= 0 ? '+' : ''}{parseFloat(monitor.short_pnl).toFixed(2)}</span></Col>
            <Col xs={8} sm={6}><span style={{ color: '#999' }}>总盈亏</span> <span style={{ color: pnlColor(parseFloat(monitor.total_pnl)), fontWeight: 500 }}>{parseFloat(monitor.total_pnl) >= 0 ? '+' : ''}{parseFloat(monitor.total_pnl).toFixed(2)}</span></Col>
            <Col xs={8} sm={6}><span style={{ color: '#999' }}>资金费</span> <span style={{ color: pnlColor(parseFloat(monitor.funding_fee)) }}>{parseFloat(monitor.funding_fee).toFixed(4)}</span></Col>
          </Row>
        </Card>
      )}

      {/* 第一行：涨幅榜空（实盘 vs 虚拟） */}
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col xs={24} lg={12}>
          <Card size="small" title={<span>实盘·涨幅榜空 ({gainerShorts.length}笔) <span style={{ color: pnlColor(gainerShortPnl), fontWeight: 500 }}>{gainerShortPnl >= 0 ? '+' : ''}{gainerShortPnl.toFixed(2)} U</span></span>}>
            <Table columns={realColumns} dataSource={gainerShorts.map((r, i) => ({ ...r, key: i }))}
              pagination={false} scroll={{ x: 'max-content' }} size="small"
              rowClassName={r => r.unrealized_pnl > 0 ? 'row-profit' : r.unrealized_pnl < 0 ? 'row-loss' : ''} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title={<span>虚拟·涨幅空（无过滤） ({virtGainerShort.length}笔) <span style={{ color: pnlColor(virtGainerShortPnl), fontWeight: 500 }}>{virtGainerShortPnl >= 0 ? '+' : ''}{virtGainerShortPnl.toFixed(2)} U</span> <span style={{ color: '#999', fontWeight: 400 }}>{(virtTime || '').slice(5, 16)}</span></span>}>
            <Table columns={virtColumns} dataSource={virtGainerShort.map((r, i) => ({ ...r, key: i }))}
              pagination={false} scroll={{ x: 'max-content' }} size="small"
              rowClassName={r => r.unrealized_pnl > 0 ? 'row-profit' : r.unrealized_pnl < 0 ? 'row-loss' : ''} />
          </Card>
        </Col>
      </Row>

      {/* 第二行：跌幅榜空（实盘 vs 虚拟） */}
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={12}>
          <Card size="small" title={<span>实盘·跌幅榜空 ({loserShorts.length}笔) <span style={{ color: pnlColor(loserShortPnl), fontWeight: 500 }}>{loserShortPnl >= 0 ? '+' : ''}{loserShortPnl.toFixed(2)} U</span></span>}>
            <Table columns={realColumns} dataSource={loserShorts.map((r, i) => ({ ...r, key: i }))}
              pagination={false} scroll={{ x: 'max-content' }} size="small"
              rowClassName={r => r.unrealized_pnl > 0 ? 'row-profit' : r.unrealized_pnl < 0 ? 'row-loss' : ''} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title={<span>虚拟·跌幅空（无过滤） ({virtLoserShort.length}笔) <span style={{ color: pnlColor(virtLoserShortPnl), fontWeight: 500 }}>{virtLoserShortPnl >= 0 ? '+' : ''}{virtLoserShortPnl.toFixed(2)} U</span> <span style={{ color: '#999', fontWeight: 400 }}>{(virtTime || '').slice(5, 16)}</span></span>}>
            <Table columns={virtColumns} dataSource={virtLoserShort.map((r, i) => ({ ...r, key: i }))}
              pagination={false} scroll={{ x: 'max-content' }} size="small"
              rowClassName={r => r.unrealized_pnl > 0 ? 'row-profit' : r.unrealized_pnl < 0 ? 'row-loss' : ''} />
          </Card>
        </Col>
      </Row>

      <style>{`
        .row-profit td { background: #f6ffed !important; }
        .row-loss td { background: #fff1f0 !important; }
        @media (max-width: 768px) {
          .ant-table-cell { white-space: normal !important; word-break: break-all; }
        }
      `}</style>
    </Spin>
  )
}
