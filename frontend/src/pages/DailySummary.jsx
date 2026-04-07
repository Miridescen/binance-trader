import { useEffect, useState } from 'react'
import { Card, Table, Spin, Tag, Row, Col, Statistic } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons'
import axios from 'axios'

function pnlColor(n) {
  if (n > 0) return '#3f8600'
  if (n < 0) return '#cf1322'
  return '#999'
}

const SIDES = [
  '涨幅榜-空（有过滤）', '涨幅榜-空（无过滤）',
  '涨幅榜-多（有过滤）', '涨幅榜-多（无过滤）',
  '跌幅榜-空（有过滤）', '跌幅榜-空（无过滤）',
  '跌幅榜-多（有过滤）', '跌幅榜-多（无过滤）',
]

const SHORT_LABELS = {
  '涨幅榜-空（有过滤）': '涨幅空（有过滤）',
  '涨幅榜-空（无过滤）': '涨幅空（无过滤）',
  '涨幅榜-多（有过滤）': '涨幅多（有过滤）',
  '涨幅榜-多（无过滤）': '涨幅多（无过滤）',
  '跌幅榜-空（有过滤）': '跌幅空（有过滤）',
  '跌幅榜-空（无过滤）': '跌幅空（无过滤）',
  '跌幅榜-多（有过滤）': '跌幅多（有过滤）',
  '跌幅榜-多（无过滤）': '跌幅多（无过滤）',
}

export default function DailySummary() {
  const [loading, setLoading] = useState(true)
  const [realData, setRealData] = useState([])
  const [virtData, setVirtData] = useState([])

  useEffect(() => {
    Promise.all([
      axios.get('/api/open_log'),
      axios.get('/api/virtual_log'),
    ]).then(([r1, r2]) => {
      setRealData(r1.data)
      setVirtData(r2.data)
    }).finally(() => setLoading(false))
  }, [])

  // Build daily summary from closed records
  const buildSummary = (data, sides) => {
    const closed = data.filter(r => r.close_time)
    const dateMap = {}
    for (const r of closed) {
      const date = (r.close_time || '').slice(0, 10)
      const side = r.side
      if (!date || !sides.includes(side)) continue
      if (!dateMap[date]) dateMap[date] = {}
      if (!dateMap[date][side]) dateMap[date][side] = { pnl: 0, count: 0, wins: 0 }
      const pnl = parseFloat(r.unrealized_pnl || 0)
      dateMap[date][side].pnl += pnl
      dateMap[date][side].count += 1
      if (pnl > 0) dateMap[date][side].wins += 1
    }
    return dateMap
  }

  // Real: only 2 sides
  const realSides = ['涨幅榜-空（有过滤）', '跌幅榜-空（有过滤）']
  const realSummary = buildSummary(realData, realSides)
  const virtSummary = buildSummary(virtData, SIDES)

  const allDates = [...new Set([...Object.keys(realSummary), ...Object.keys(virtSummary)])].sort().reverse()

  // Virtual table columns
  const virtColumns = [
    {
      title: '日期', dataIndex: 'date', key: 'date', width: 100, fixed: 'left',
      render: v => <b>{v?.slice(5)}</b>,
    },
    ...SIDES.map(side => ({
      title: SHORT_LABELS[side],
      dataIndex: side,
      key: side,
      width: 110,
      render: v => {
        if (!v) return <span style={{ color: '#ccc' }}>-</span>
        return (
          <span style={{ color: pnlColor(v.pnl), fontWeight: 500 }}>
            {v.pnl >= 0 ? '+' : ''}{v.pnl.toFixed(1)}
            <br />
            <span style={{ color: '#999', fontWeight: 400, fontSize: 11 }}>{v.wins}/{v.count}</span>
          </span>
        )
      },
    })),
    {
      title: '合计', dataIndex: 'total', key: 'total', width: 80,
      render: v => {
        if (v == null) return '-'
        return <b style={{ color: pnlColor(v) }}>{v >= 0 ? '+' : ''}{v.toFixed(1)}</b>
      },
    },
  ]

  const virtRows = allDates.map(date => {
    const row = { key: date, date }
    let total = 0
    let hasData = false
    for (const side of SIDES) {
      const d = virtSummary[date]?.[side]
      row[side] = d || null
      if (d) { total += d.pnl; hasData = true }
    }
    row.total = hasData ? total : null
    return row
  }).filter(r => SIDES.some(s => r[s]))

  // Real table columns
  const realColumns = [
    {
      title: '日期', dataIndex: 'date', key: 'date', width: 100, fixed: 'left',
      render: v => <b>{v?.slice(5)}</b>,
    },
    ...realSides.map(side => ({
      title: SHORT_LABELS[side],
      dataIndex: side,
      key: side,
      width: 100,
      render: v => {
        if (!v) return <span style={{ color: '#ccc' }}>-</span>
        return (
          <span style={{ color: pnlColor(v.pnl), fontWeight: 500 }}>
            {v.pnl >= 0 ? '+' : ''}{v.pnl.toFixed(2)} U
            <br />
            <span style={{ color: '#999', fontWeight: 400, fontSize: 11 }}>{v.wins}/{v.count}</span>
          </span>
        )
      },
    })),
    {
      title: '合计', dataIndex: 'total', key: 'total', width: 90,
      render: v => {
        if (v == null) return '-'
        return <b style={{ color: pnlColor(v) }}>{v >= 0 ? '+' : ''}{v.toFixed(2)} U</b>
      },
    },
  ]

  const realRows = allDates.map(date => {
    const row = { key: date, date }
    let total = 0
    let hasData = false
    for (const side of realSides) {
      const d = realSummary[date]?.[side]
      row[side] = d || null
      if (d) { total += d.pnl; hasData = true }
    }
    row.total = hasData ? total : null
    return row
  }).filter(r => realSides.some(s => r[s]))

  // Totals for stats cards
  const virtTotals = {}
  for (const side of SIDES) {
    virtTotals[side] = virtRows.reduce((acc, r) => acc + (r[side]?.pnl || 0), 0)
  }
  const realTotals = {}
  for (const side of realSides) {
    realTotals[side] = realRows.reduce((acc, r) => acc + (r[side]?.pnl || 0), 0)
  }

  return (
    <Spin spinning={loading}>
      <Card size="small" title="实盘每日汇总" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
          {realSides.map(s => {
            const pnl = realTotals[s] || 0
            return (
              <Col xs={12} sm={8} md={6} key={s}>
                <Card size="small">
                  <Statistic title={SHORT_LABELS[s]} value={Math.abs(pnl).toFixed(2)} suffix="U"
                    prefix={pnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                    valueStyle={{ color: pnlColor(pnl), fontSize: 16 }} />
                </Card>
              </Col>
            )
          })}
        </Row>
        <Table columns={realColumns} dataSource={realRows}
          pagination={false} scroll={{ x: 'max-content' }} size="small" />
      </Card>

      <Card size="small" title="虚拟盘每日汇总">
        <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
          {SIDES.map(s => {
            const pnl = virtTotals[s] || 0
            return (
              <Col xs={12} sm={8} md={6} lg={3} key={s}>
                <Card size="small">
                  <Statistic title={SHORT_LABELS[s]} value={Math.abs(pnl).toFixed(1)} suffix="U"
                    prefix={pnl >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                    valueStyle={{ color: pnlColor(pnl), fontSize: 14 }} />
                </Card>
              </Col>
            )
          })}
        </Row>
        <Table columns={virtColumns} dataSource={virtRows}
          pagination={false} scroll={{ x: 'max-content' }} size="small" />
      </Card>
    </Spin>
  )
}
