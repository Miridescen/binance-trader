import { useEffect, useMemo, useState } from 'react'
import { Table, Card, Tag, Spin, Row, Col, Statistic, Tabs, Select, Space } from 'antd'
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

const fmtPnl = v => `${v >= 0 ? '+' : ''}${(v || 0).toFixed(2)}`

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
      title: '开仓时间', dataIndex: 'open_time', key: 'open_time', width: 130,
      render: v => v ? v.slice(5, 16) : '-',
      sorter: true, defaultSortOrder: 'descend',
    },
    { title: '笔数', dataIndex: 'n_orders', key: 'n_orders', width: 60 },
    {
      title: '触发', key: 'trigger_kind', width: 90,
      render: (_, r) => {
        if (r.n_hit > 0) return <Tag color="gold">+10u</Tag>
        if (r.n_timed > 0) return <Tag color="default">{windowLabel} 定平</Tag>
        return <Tag>持仓中</Tag>
      },
    },
    {
      title: '实际 PnL', dataIndex: 'sum_pnl_actual', key: 'sum_pnl_actual', width: 110,
      render: v => <PnlCell value={v} />, sorter: true,
    },
    {
      title: `走完${windowLabel}`, dataIndex: 'sum_pnl_if_held', key: 'sum_pnl_if_held', width: 130,
      render: (v, r) => {
        const pending = r.window_end && r.window_end > nowStr()
        return (
          <span>
            <PnlCell value={v} />
            {pending && <Tag color="processing" style={{ marginLeft: 6, fontSize: 11, lineHeight: '16px' }}>进行中</Tag>}
          </span>
        )
      },
      sorter: true,
    },
    {
      title: '差额', key: 'diff', width: 90,
      render: (_, r) => {
        const d = parseFloat(r.sum_pnl_actual || 0) - parseFloat(r.sum_pnl_if_held || 0)
        const color = d > 0 ? '#3f8600' : (d < 0 ? '#cf1322' : '#999')
        return <span style={{ color, fontWeight: 500 }}>{d >= 0 ? '+' : ''}{d.toFixed(2)}</span>
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
    <Card
      size="small"
      title={
        <span>
          <Tag color={color}>{label}</Tag>
          <span style={{ color: '#999', fontSize: 12, marginLeft: 4 }}>
            实际 <span style={{ color: pnlColor(t.sum_actual), fontWeight: 500 }}>{fmtPnl(t.sum_actual)}</span>
          </span>
          <span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>
            走完{windowLabel} <span style={{ color: pnlColor(t.sum_held), fontWeight: 500 }}>{fmtPnl(t.sum_held)}</span>
          </span>
          <span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>{t.n_groups || 0} 组</span>
        </span>
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
    </Card>
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

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Space wrap>
          <span style={{ color: '#666' }}>按时段筛选：</span>
          <Select
            size="small" style={{ minWidth: 140 }} value={timeFilter} onChange={setTimeFilter}
            options={[{ label: '全部时段', value: 'all' }, ...timeOptions.map(t => ({ label: t, value: t }))]}
          />
          {timeFilter !== 'all' && <Tag color="blue">仅看 {timeFilter} 周期</Tag>}
        </Space>
      </div>

      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={12} md={12}>
          <Card size="small">
            <Statistic title="+10u触发组" value={nHit} suffix={`/ ${nGroups}`} />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={12}>
          <Card size="small">
            <Statistic title={`${window}定平组`} value={nTimed} suffix={`/ ${nGroups}`} />
          </Card>
        </Col>
      </Row>

      <Card size="small">
        <Spin spinning={loading}>
          <Tabs
            defaultActiveKey={SIDE_PAIRS[0].key}
            items={SIDE_PAIRS.map(p => {
              const fPnl = sumActualBy(p.filtered)
              const uPnl = sumActualBy(p.unfiltered)
              return {
                key: p.key,
                label: (
                  <span>
                    {p.label}{' '}
                    <span style={{ fontSize: 12, color: '#666' }}>
                      (有过滤 <span style={{ color: pnlColor(fPnl) }}>{fmtPnl(fPnl)}</span>
                      , 无过滤 <span style={{ color: pnlColor(uPnl) }}>{fmtPnl(uPnl)}</span>)
                    </span>
                  </span>
                ),
                children: (
                  <Row gutter={[12, 12]}>
                    <Col xs={24} lg={12}>
                      <SideTable windowName={window} side={p.filtered} time={timeFilter}
                        label="有过滤" color={p.tagColor} totals={totalsMap[p.filtered]}
                        inprogress={ipBySide[p.filtered] || []} columns={columns} windowLabel={window} />
                    </Col>
                    <Col xs={24} lg={12}>
                      <SideTable windowName={window} side={p.unfiltered} time={timeFilter}
                        label="无过滤" color="default" totals={totalsMap[p.unfiltered]}
                        inprogress={ipBySide[p.unfiltered] || []} columns={columns} windowLabel={window} />
                    </Col>
                  </Row>
                ),
              }
            })}
          />
        </Spin>
      </Card>

      <style>{`
        .row-profit td { background: #f6ffed !important; }
        .row-loss   td { background: #fff1f0 !important; }
        @media (max-width: 768px) {
          .ant-table-cell { white-space: normal !important; word-break: break-all; }
        }
      `}</style>
    </div>
  )
}
