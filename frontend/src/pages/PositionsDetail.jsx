import { useEffect, useState } from 'react'
import { Table, Spin, Select } from 'antd'
import axios from 'axios'
import { PnlCell, Num, SideChip, Panel, PageHeader } from '../components/ui'

const columns = [
  { title: '币种', dataIndex: 'symbol', key: 'symbol', width: 110, filters: [], onFilter: (v, r) => r.symbol === v,
    render: v => <span style={{ fontWeight: 600 }}>{v}</span> },
  { title: '方向', dataIndex: 'side', key: 'side', width: 150, render: v => <SideChip side={v} /> },
  { title: '开仓价', dataIndex: 'entry_price', key: 'entry_price', width: 90, align: 'right', render: v => <Num value={v} digits={4} /> },
  { title: '标记价', dataIndex: 'mark_price', key: 'mark_price', width: 90, align: 'right', render: v => <Num value={v} digits={4} /> },
  { title: '持仓量', dataIndex: 'position_amt', key: 'position_amt', width: 80, align: 'right', render: v => v ? <span className="num">{parseFloat(v)}</span> : '-' },
  { title: '盈亏', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 90, align: 'right', render: v => <PnlCell value={v} />, sorter: (a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0) },
  { title: 'ROE', dataIndex: 'roe_pct', key: 'roe_pct', width: 80, align: 'right', render: v => <PnlCell value={v} suffix="%" />, sorter: (a, b) => (a.roe_pct || 0) - (b.roe_pct || 0) },
]

export default function PositionsDetail() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)
  const [dates, setDates] = useState([])
  const [times, setTimes] = useState([])
  const [filterDate, setFilterDate] = useState(null)
  const [filterTime, setFilterTime] = useState(null)

  // 加载日期列表
  useEffect(() => {
    axios.get('/api/positions_detail/dates').then(res => {
      setDates(res.data || [])
      if (res.data?.length) setFilterDate(res.data[0])
    })
  }, [])

  // 选日期后加载时间点列表
  useEffect(() => {
    if (!filterDate) return
    setTimes([])
    setFilterTime(null)
    setData([])
    axios.get(`/api/positions_detail/times?date=${filterDate}`).then(res => {
      const t = res.data || []
      setTimes(t)
      if (t.length) setFilterTime(t[0]) // 默认最新时间点
    })
  }, [filterDate])

  // 选时间点后加载快照数据
  useEffect(() => {
    if (!filterTime) return
    setLoading(true)
    axios.get(`/api/positions_detail?time=${encodeURIComponent(filterTime)}`).then(res => {
      const rows = res.data.map((r, i) => ({ ...r, key: i }))
      columns.find(c => c.key === 'symbol').filters = [...new Set(rows.map(r => r.symbol))].map(s => ({ text: s, value: s }))
      setData(rows)
    }).finally(() => setLoading(false))
  }, [filterTime])

  return (
    <div className="panel-stack">
      <PageHeader
        title="持仓快照"
        subtitle="按日期与时间点回看每小时的单仓盈亏明细"
        extra={
          <div className="toolbar">
            <Select
              placeholder="选择日期"
              options={dates.map(d => ({ label: d, value: d }))}
              value={filterDate}
              onChange={v => setFilterDate(v)}
              style={{ width: 140 }}
            />
            <Select
              placeholder="选择时间"
              options={times.map(t => ({ label: t.slice(11, 19), value: t }))}
              value={filterTime}
              onChange={v => setFilterTime(v)}
              disabled={!times.length}
              style={{ width: 130 }}
              showSearch
            />
          </div>
        }
      />
      <Panel flush title="持仓明细" subtitle={`${data.length} 条`}>
        <Spin spinning={loading}>
          <Table columns={columns} dataSource={data} pagination={false}
            scroll={{ x: 'max-content' }} size="small"
            rowClassName={r => r.unrealized_pnl > 0 ? 'row-profit' : r.unrealized_pnl < 0 ? 'row-loss' : ''} />
        </Spin>
      </Panel>
    </div>
  )
}
