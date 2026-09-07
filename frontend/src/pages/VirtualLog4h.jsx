import { useEffect, useMemo, useState } from 'react'
import { Table, Spin, Row, Col, Tabs, Select } from 'antd'
import axios from 'axios'
import { PnlCell, Chip, Panel, PageHeader, Stat } from '../components/ui'
import { pnlColor, fmtSigned } from '../lib/fmt'

const fmtPnl = v => fmtSigned(v || 0, 2)

// 当前本地时间字符串（与 window_end 同格式，用于判断窗口是否已结束）
function nowStr() {
  const d = new Date()
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

const SIDE_PAIRS = [
  { key: 'gainer_short', label: '涨幅榜-空', filtered: '涨幅榜-空（有过滤）', unfiltered: '涨幅榜-空（无过滤）', tagColor: 'green' },
  { key: 'gainer_long',  label: '涨幅榜-多', filtered: '涨幅榜-多（有过滤）', unfiltered: '涨幅榜-多（无过滤）', tagColor: 'red' },
  { key: 'loser_short',  label: '跌幅榜-空', filtered: '跌幅榜-空（有过滤）', unfiltered: '跌幅榜-空（无过滤）', tagColor: 'cyan' },
  { key: 'loser_long',   label: '跌幅榜-多', filtered: '跌幅榜-多（有过滤）', unfiltered: '跌幅榜-多（无过滤）', tagColor: 'orange' },
]

// 服务端排序：列上标 sorter:true，由 Table onChange 触发后端排序
function buildGroupColumns(windowLabel) {
  return [
    {
      title: '开仓时间', dataIndex: 'open_time', key: 'open_time', width: 120,
      render: v => v ? <span className="num" style={{ fontWeight: 500 }}>{v.slice(5, 16)}</span> : '-',
      sorter: true, defaultSortOrder: 'descend',
    },
    { title: '笔数', dataIndex: 'n_orders', key: 'n_orders', width: 56, align: 'right' },
    {
      title: '触发', key: 'trigger_kind', width: 90,
      render: (_, r) => {
        if (r.n_hit > 0) return <Chip tone="gold">+10u</Chip>
        if (r.n_timed > 0) return <Chip tone="grey">{windowLabel} 定平</Chip>
        return <Chip tone="blue">持仓中</Chip>
      },
    },
    {
      title: '实际 PnL', dataIndex: 'sum_pnl_actual', key: 'sum_pnl_actual', width: 100, align: 'right',
      render: v => <PnlCell value={v} />, sorter: true,
    },
    {
      title: `走完${windowLabel}`, dataIndex: 'sum_pnl_if_held', key: 'sum_pnl_if_held', width: 130, align: 'right',
      render: (v, r) => {
        const pending = r.window_end && r.window_end > nowStr()
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <PnlCell value={v} />
            {pending && <Chip tone="blue" style={{ height: 18, fontSize: 11, padding: '0 6px' }}>进行中</Chip>}
          </span>
        )
      },
      sorter: true,
    },
    {
      title: '差额', key: 'diff', width: 84, align: 'right',
      render: (_, r) => {
        const d = parseFloat(r.sum_pnl_actual || 0) - parseFloat(r.sum_pnl_if_held || 0)
        return <PnlCell value={d} />
      },
    },
  ]
}

// 单个方向的服务端分页表：自管 page/pageSize/sort，进行中的组置顶（仅第一页+默认排序时）
function SideTable({ windowName, side, time, label, color, totals, inprogress, columns, windowLabel }) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(30)
  const [sort, setSort] = useState({ field: 'open_time', order: 'desc' })
  const [data, setData] = useState({ rows: [], total: 0 })
  const [loading, setLoading] = useState(false)

  // 切方向/时段回到第一页
  useEffect(() => { setPage(1); setSort({ field: 'open_time', order: 'desc' }) }, [side, time, windowName])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    axios.get('/api/virtual_groups', {
      params: {
        window: windowName, side, time: time === 'all' ? undefined : time,
        sort: sort.field, order: sort.order, page, page_size: pageSize,
      },
    }).then(res => { if (!cancelled) setData(res.data || { rows: [], total: 0 }) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [windowName, side, time, sort, page, pageSize])

  const isDefaultView = page === 1 && sort.field === 'open_time' && sort.order === 'desc'
  const ipRows = isDefaultView ? inprogress : []
  const rows = [...ipRows, ...(data.rows || [])].map((r, i) => ({ ...r, key: `${r.open_time}|${r.side}|${i}` }))

  const t = totals || {}
  const onChange = (pag, _filters, sorter) => {
    if (pag.pageSize !== pageSize) { setPageSize(pag.pageSize); setPage(1) }
    else if (pag.current !== page) { setPage(pag.current) }
    const s = Array.isArray(sorter) ? sorter[0] : sorter
    if (s && s.field && s.order) {
      const field = s.field
      const order = s.order === 'ascend' ? 'asc' : 'desc'
      if (field !== sort.field || order !== sort.order) { setSort({ field, order }); setPage(1) }
    } else if (s && !s.order) {
      if (sort.field !== 'open_time' || sort.order !== 'desc') { setSort({ field: 'open_time', order: 'desc' }); setPage(1) }
    }
  }

  return (
    <Panel
      flush
      title={<Chip tone={color}>{label}</Chip>}
      subtitle={`${t.n_groups || 0} 组`}
      extra={
        <div className="kv-row" style={{ gap: 14 }}>
          <span className="kv-inline">实际 <PnlCell value={t.sum_actual || 0} /></span>
          <span className="kv-inline">走完{windowLabel} <PnlCell value={t.sum_held || 0} /></span>
        </div>
      }
    >
      <Table
        columns={columns}
        dataSource={rows}
        loading={loading}
        onChange={onChange}
        pagination={{
          current: page, pageSize, total: data.total || 0,
          showSizeChanger: true, pageSizeOptions: [20, 30, 50, 100],
          showTotal: tot => `共 ${tot} 组`,
          size: 'small',
        }}
        scroll={{ x: 'max-content' }}
        size="small"
        rowClassName={r => {
          const a = parseFloat(r.sum_pnl_actual || 0)
          if (a > 0) return 'row-profit'
          if (a < 0) return 'row-loss'
          return ''
        }}
        locale={{ emptyText: '暂无已收尾的组' }}
      />
    </Panel>
  )
}

export default function VirtualLogWindow({ window = '4h' }) {
  const [totals, setTotals] = useState([])       // 各方向累计（读汇总表）
  const [inprogress, setInprogress] = useState([]) // 进行中的组
  const [timeOptions, setTimeOptions] = useState([])
  const [timeFilter, setTimeFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const columns = buildGroupColumns(window)

  useEffect(() => { setTimeFilter('all') }, [window])

  // 时段下拉：按窗口拉一次
  useEffect(() => {
    axios.get('/api/virtual_times', { params: { window } })
      .then(res => setTimeOptions(res.data || []))
      .catch(() => setTimeOptions([]))
  }, [window])

  // 求和 + 进行中：按 窗口/时段 拉
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      axios.get('/api/virtual_totals', { params: { window, time: timeFilter === 'all' ? undefined : timeFilter } }),
      axios.get('/api/virtual_inprogress', { params: { window } }),
    ]).then(([t, ip]) => {
      if (cancelled) return
      setTotals(t.data || [])
      setInprogress(ip.data || [])
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [window, timeFilter])

  const totalsMap = useMemo(() => Object.fromEntries(totals.map(t => [t.side, t])), [totals])

  // 进行中按时段过滤 + 按方向分组
  const ipFiltered = useMemo(
    () => inprogress.filter(g => timeFilter === 'all' || g.open_time?.slice(11, 16) === timeFilter),
    [inprogress, timeFilter]
  )
  const ipBySide = useMemo(() => {
    const m = {}
    for (const g of ipFiltered) (m[g.side] = m[g.side] || []).push(g)
    return m
  }, [ipFiltered])

  const nGroups = totals.reduce((a, t) => a + (t.n_groups || 0), 0) + ipFiltered.length
  const nHit = totals.reduce((a, t) => a + (t.n_hit_groups || 0), 0) + ipFiltered.length // 进行中均为 +10u 提前平
  const nTimed = totals.reduce((a, t) => a + (t.n_timed_groups || 0), 0)

  const sumActualBy = side => (totalsMap[side]?.sum_actual || 0)
  const pct = n => nGroups ? `${((n / nGroups) * 100).toFixed(1)}%` : '—'

  return (
    <div className="panel-stack">
      <PageHeader
        title={`${window} 模拟盘`}
        subtitle="四个方向 × 有/无过滤，对比「+10u 提前平」与「走完窗口」两种收尾的盈亏"
        extra={
          <div className="toolbar">
            <span className="toolbar-label">时段</span>
            <Select
              style={{ minWidth: 130 }} value={timeFilter} onChange={setTimeFilter}
              options={[{ label: '全部时段', value: 'all' }, ...timeOptions.map(t => ({ label: `${t} 周期`, value: t }))]}
            />
          </div>
        }
      />

      <div className="stat-grid" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
        <Stat card label="+10u 触发组" value={nHit} unit={`/ ${nGroups}`} hint={`占比 ${pct(nHit)}`} tone="brand" />
        <Stat card label={`${window} 定平组`} value={nTimed} unit={`/ ${nGroups}`} hint={`占比 ${pct(nTimed)}`} />
      </div>

      <Panel className="panel-tabs" flush>
        <Spin spinning={loading}>
          <Tabs
            defaultActiveKey={SIDE_PAIRS[0].key}
            items={SIDE_PAIRS.map(p => {
              const fPnl = sumActualBy(p.filtered)
              const uPnl = sumActualBy(p.unfiltered)
              return {
                key: p.key,
                label: (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600 }}>{p.label}</span>
                    <span className="muted" style={{ fontSize: 12 }}>
                      <span style={{ color: pnlColor(fPnl) }}>{fmtPnl(fPnl)}</span>
                      {' / '}
                      <span style={{ color: pnlColor(uPnl) }}>{fmtPnl(uPnl)}</span>
                    </span>
                  </span>
                ),
                children: (
                  <Row gutter={[16, 16]}>
                    <Col xs={24} lg={12}>
                      <SideTable windowName={window} side={p.filtered} time={timeFilter}
                        label="有过滤" color={p.tagColor} totals={totalsMap[p.filtered]}
                        inprogress={ipBySide[p.filtered] || []} columns={columns} windowLabel={window} />
                    </Col>
                    <Col xs={24} lg={12}>
                      <SideTable windowName={window} side={p.unfiltered} time={timeFilter}
                        label="无过滤" color="grey" totals={totalsMap[p.unfiltered]}
                        inprogress={ipBySide[p.unfiltered] || []} columns={columns} windowLabel={window} />
                    </Col>
                  </Row>
                ),
              }
            })}
          />
        </Spin>
      </Panel>
    </div>
  )
}
