import { useEffect, useState } from 'react'
import { Table, Spin, Row, Col } from 'antd'
import axios from 'axios'
import { Panel, PageHeader, Stat } from '../components/ui'
import { pnlColor, pnlTone, fmtSigned } from '../lib/fmt'

function PnlCell({ v, decimal = 1 }) {
  if (!v) return <span className="muted">-</span>
  return (
    <span className="pnl" style={{ color: pnlColor(v.pnl) }}>
      {fmtSigned(v.pnl, decimal)}
      <br />
      <span className="muted" style={{ fontWeight: 400, fontSize: 11 }}>{v.wins}/{v.count}</span>
    </span>
  )
}

const Signed = ({ v, digits = 1 }) => <b className={`pnl ${pnlTone(v)}`}>{fmtSigned(v, digits)}</b>

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
    { title: '日期', dataIndex: 'date', key: 'date', width: 90, render: v => <b className="num">{v?.slice(5)}</b> },
    ...REAL_SIDES.map(side => ({
      title: side.includes('涨幅') ? '涨幅空（有过滤）' : '跌幅空（有过滤）',
      dataIndex: side, key: side, width: 110, align: 'right',
      render: v => <PnlCell v={v} decimal={2} />,
    })),
    {
      title: '合计', dataIndex: 'total', key: 'total', width: 100, align: 'right',
      render: v => v == null ? '-' : <b className={`pnl ${pnlTone(v)}`}>{fmtSigned(v, 2)} U</b>,
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
    { title: '日期', dataIndex: 'date', key: 'date', width: 90, render: v => <b className="num">{v?.slice(5)}</b> },
    { title: '有过滤', dataIndex: 'filtered', key: 'filtered', width: 100, align: 'right', render: v => <PnlCell v={v} /> },
    { title: '无过滤', dataIndex: 'unfiltered', key: 'unfiltered', width: 100, align: 'right', render: v => <PnlCell v={v} /> },
    {
      title: '差值', dataIndex: 'diff', key: 'diff', width: 80, align: 'right',
      render: v => v == null ? '-' : <Signed v={v} />,
    },
  ]

  return (
    <Spin spinning={loading}>
      <div className="panel-stack">
        <PageHeader title="每日汇总" subtitle="近 10 天实盘与模拟盘按日盈亏（数字下方为 胜/总 笔数）" />

        <Panel flush title="实盘每日汇总" subtitle="近 10 天">
          <div className="stat-strip" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', borderBottom: '1px solid var(--border)' }}>
            {REAL_SIDES.map(s => {
              const pnl = realTotals[s] || 0
              return (
                <Stat key={s} size="sm" label={s.includes('涨幅') ? '涨幅空（有过滤）' : '跌幅空（有过滤）'}
                  unit="U" tone={pnlTone(pnl)} value={fmtSigned(pnl, 2)} />
              )
            })}
          </div>
          <Table columns={realColumns} dataSource={realRows}
            pagination={false} scroll={{ x: 'max-content' }} size="small" />
        </Panel>

        <Row gutter={[16, 16]}>
          {GROUPS.map(group => {
            const rows = buildGroupRows(group)
            const fTotal = rows.reduce((acc, r) => acc + (r.filtered?.pnl || 0), 0)
            const uTotal = rows.reduce((acc, r) => acc + (r.unfiltered?.pnl || 0), 0)
            const diff = fTotal - uTotal
            return (
              <Col xs={24} lg={12} key={group.label}>
                <Panel
                  flush
                  title={group.label}
                  extra={
                    <div className="kv-row" style={{ gap: 14 }}>
                      <span className="kv-inline">有过滤 <Signed v={fTotal} /></span>
                      <span className="kv-inline">无过滤 <Signed v={uTotal} /></span>
                      <span className="kv-inline">差 <Signed v={diff} /></span>
                    </div>
                  }>
                  <Table columns={groupColumns} dataSource={rows}
                    pagination={false} scroll={{ x: 'max-content' }} size="small" />
                </Panel>
              </Col>
            )
          })}
        </Row>
      </div>
    </Spin>
  )
}
