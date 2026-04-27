import { useEffect, useState } from 'react'
import { Card, Table, Spin, Row, Col, Statistic } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons'
import axios from 'axios'

function pnlColor(n) {
  if (n > 0) return '#3f8600'
  if (n < 0) return '#cf1322'
  return '#999'
}

function PnlCell({ v, decimal = 1 }) {
  if (!v) return <span style={{ color: '#ccc' }}>-</span>
  return (
    <span style={{ color: pnlColor(v.pnl), fontWeight: 500 }}>
      {v.pnl >= 0 ? '+' : ''}{v.pnl.toFixed(decimal)}
      <br />
      <span style={{ color: '#999', fontWeight: 400, fontSize: 11 }}>{v.wins}/{v.count}</span>
    </span>
  )
}

const GROUPS = [
  { label: '涨幅榜-空', filtered: '涨幅榜-空（有过滤）', unfiltered: '涨幅榜-空（无过滤）' },
  { label: '涨幅榜-多', filtered: '涨幅榜-多（有过滤）', unfiltered: '涨幅榜-多（无过滤）' },
  { label: '跌幅榜-空', filtered: '跌幅榜-空（有过滤）', unfiltered: '跌幅榜-空（无过滤）' },
  { label: '跌幅榜-多', filtered: '跌幅榜-多（有过滤）', unfiltered: '跌幅榜-多（无过滤）' },
]

const REAL_SIDES = ['涨幅榜-空（有过滤）', '跌幅榜-空（有过滤）']

export default function DailySummary() {
  const [loading, setLoading] = useState(true)
  const [realSummary, setRealSummary] = useState({})
  const [virtSummary, setVirtSummary] = useState({})
  const [allDates, setAllDates] = useState([])

  useEffect(() => {
    axios.get('/api/daily_summary?days=10').then(({ data }) => {
      const real = {}, virt = {}
      const dateSet = new Set()
      for (const r of data) {
        const bucket = r.source === '实盘' ? real : r.source === '虚拟盘' ? virt : null
        if (!bucket) continue
        if (!bucket[r.date]) bucket[r.date] = {}
        bucket[r.date][r.side] = {
          pnl: r.total_pnl || 0,
          count: r.count || 0,
          wins: r.wins || 0,
        }
        dateSet.add(r.date)
      }
      setRealSummary(real)
      setVirtSummary(virt)
      setAllDates([...dateSet].sort().reverse())
    }).finally(() => setLoading(false))
  }, [])

  const realColumns = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 90, render: v => <b>{v?.slice(5)}</b> },
    ...REAL_SIDES.map(side => ({
      title: side.includes('涨幅') ? '涨幅空（有过滤）' : '跌幅空（有过滤）',
      dataIndex: side, key: side, width: 110,
      render: v => <PnlCell v={v} decimal={2} />,
    })),
    {
      title: '合计', dataIndex: 'total', key: 'total', width: 90,
      render: v => v == null ? '-' : <b style={{ color: pnlColor(v) }}>{v >= 0 ? '+' : ''}{v.toFixed(2)} U</b>,
    },
  ]
  const realRows = allDates.map(date => {
    const row = { key: date, date }
    let total = 0, hasData = false
    for (const s of REAL_SIDES) {
      const d = realSummary[date]?.[s]
      row[s] = d || null
      if (d) { total += d.pnl; hasData = true }
    }
    row.total = hasData ? total : null
    return row
  }).filter(r => REAL_SIDES.some(s => r[s]))

  const realTotals = {}
  for (const s of REAL_SIDES) realTotals[s] = realRows.reduce((acc, r) => acc + (r[s]?.pnl || 0), 0)

  const buildGroupRows = (group) => {
    const { filtered, unfiltered } = group
    return allDates.map(date => {
      const f = virtSummary[date]?.[filtered]
      const u = virtSummary[date]?.[unfiltered]
      if (!f && !u) return null
      const diff = (f?.pnl || 0) - (u?.pnl || 0)
      return { key: date, date, filtered: f, unfiltered: u, diff: (f || u) ? diff : null }
    }).filter(Boolean)
  }

  const groupColumns = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 90, render: v => <b>{v?.slice(5)}</b> },
    { title: '有过滤', dataIndex: 'filtered', key: 'filtered', width: 100, render: v => <PnlCell v={v} /> },
    { title: '无过滤', dataIndex: 'unfiltered', key: 'unfiltered', width: 100, render: v => <PnlCell v={v} /> },
    {
      title: '差值', dataIndex: 'diff', key: 'diff', width: 80,
      render: v => v == null ? '-' : <b style={{ color: pnlColor(v) }}>{v >= 0 ? '+' : ''}{v.toFixed(1)}</b>,
    },
  ]

  return (
    <Spin spinning={loading}>
      <Card size="small" title="实盘每日汇总（近10天）" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
          {REAL_SIDES.map(s => {
            const pnl = realTotals[s] || 0
            return (
              <Col xs={12} sm={8} md={6} key={s}>
                <Card size="small">
                  <Statistic title={s.includes('涨幅') ? '涨幅空（有过滤）' : '跌幅空（有过滤）'}
                    value={Math.abs(pnl).toFixed(2)} suffix="U"
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

      <Row gutter={[12, 12]}>
        {GROUPS.map(group => {
          const rows = buildGroupRows(group)
          const fTotal = rows.reduce((acc, r) => acc + (r.filtered?.pnl || 0), 0)
          const uTotal = rows.reduce((acc, r) => acc + (r.unfiltered?.pnl || 0), 0)
          const diff = fTotal - uTotal
          return (
            <Col xs={24} lg={12} key={group.label}>
              <Card size="small"
                title={group.label}
                extra={
                  <span style={{ fontSize: 13 }}>
                    有过滤 <b style={{ color: pnlColor(fTotal) }}>{fTotal >= 0 ? '+' : ''}{fTotal.toFixed(1)}</b>
                    {' / '}无过滤 <b style={{ color: pnlColor(uTotal) }}>{uTotal >= 0 ? '+' : ''}{uTotal.toFixed(1)}</b>
                    {' / '}差 <b style={{ color: pnlColor(diff) }}>{diff >= 0 ? '+' : ''}{diff.toFixed(1)}</b>
                  </span>
                }
                style={{ marginBottom: 12 }}>
                <Table columns={groupColumns} dataSource={rows}
                  pagination={false} scroll={{ x: 'max-content' }} size="small" />
              </Card>
            </Col>
          )
        })}
      </Row>
    </Spin>
  )
}
