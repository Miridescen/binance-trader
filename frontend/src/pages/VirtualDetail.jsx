import { useEffect, useState } from 'react'
import { Table, Card, Tag, Spin, Select, Space } from 'antd'
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
  return <span style={{ color: pnlColor(n), fontWeight: 500 }}>{n >= 0 ? '+' : ''}{n.toFixed(2)}</span>
}

function RoeCell({ value }) {
  const n = parseFloat(value)
  if (isNaN(n)) return <span style={{ color: '#999' }}>-</span>
  return <span style={{ color: pnlColor(n), fontWeight: 500 }}>{n >= 0 ? '+' : ''}{n.toFixed(2)}%</span>
}

const sideColors = { '空': 'green', '多': 'red', '模拟空': 'cyan', '模拟多': 'orange' }

const columns = [
  { title: '币种', dataIndex: 'symbol', key: 'symbol', width: 110, filters: [], onFilter: (v, r) => r.symbol === v },
  { title: '方向', dataIndex: 'side', key: 'side', width: 70, render: v => <Tag color={sideColors[v] || 'default'}>{v}</Tag>,
    filters: [{ text: '空', value: '空' }, { text: '多', value: '多' }, { text: '模拟空', value: '模拟空' }, { text: '模拟多', value: '模拟多' }],
    onFilter: (v, r) => r.side === v },
  { title: '入场价', dataIndex: 'entry_price', key: 'entry_price', width: 90, render: v => v ? parseFloat(v).toFixed(4) : '-' },
  { title: '标记价', dataIndex: 'mark_price', key: 'mark_price', width: 90, render: v => v ? parseFloat(v).toFixed(4) : '-' },
  { title: '盈亏', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 80, render: v => <PnlCell value={v} />, sorter: (a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0) },
  { title: 'ROE', dataIndex: 'roe_pct', key: 'roe_pct', width: 80, render: v => <RoeCell value={v} />, sorter: (a, b) => (a.roe_pct || 0) - (b.roe_pct || 0) },
]

export default function VirtualDetail() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)
  const [dates, setDates] = useState([])
  const [times, setTimes] = useState([])
  const [filterDate, setFilterDate] = useState(null)
  const [filterTime, setFilterTime] = useState(null)
  const [filterSide, setFilterSide] = useState(null)

  useEffect(() => {
    axios.get('/api/virtual_detail/dates').then(res => {
      setDates(res.data || [])
      if (res.data?.length) setFilterDate(res.data[0])
    })
  }, [])

  useEffect(() => {
    if (!filterDate) return
    setTimes([])
    setFilterTime(null)
    setData([])
    axios.get(`/api/virtual_detail/times?date=${filterDate}`).then(res => {
      const t = res.data || []
      setTimes(t)
      if (t.length) setFilterTime(t[0])
    })
  }, [filterDate])

  useEffect(() => {
    if (!filterTime) return
    setLoading(true)
    axios.get(`/api/virtual_detail?time=${encodeURIComponent(filterTime)}`).then(res => {
      const rows = res.data.map((r, i) => ({ ...r, key: i }))
      columns.find(c => c.key === 'symbol').filters = [...new Set(rows.map(r => r.symbol))].map(s => ({ text: s, value: s }))
      setData(rows)
    }).finally(() => setLoading(false))
  }, [filterTime])

  const filtered = filterSide ? data.filter(r => r.side === filterSide) : data

  return (
    <Card size="small">
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          placeholder="选择日期"
          options={dates.map(d => ({ label: d, value: d }))}
          value={filterDate}
          onChange={v => setFilterDate(v)}
          style={{ width: 130 }}
        />
        <Select
          placeholder="选择时间"
          options={times.map(t => ({ label: t.slice(11, 19), value: t }))}
          value={filterTime}
          onChange={v => setFilterTime(v)}
          disabled={!times.length}
          style={{ width: 120 }}
          showSearch
        />
        <Select
          placeholder="方向"
          options={[{ label: '空', value: '空' }, { label: '多', value: '多' }, { label: '模拟空', value: '模拟空' }, { label: '模拟多', value: '模拟多' }]}
          value={filterSide}
          onChange={v => setFilterSide(v)}
          allowClear
          style={{ width: 100 }}
        />
        <span style={{ color: '#999', fontSize: 12 }}>{filtered.length} 条</span>
      </Space>
      <Spin spinning={loading}>
        <Table columns={columns} dataSource={filtered} pagination={false}
          scroll={{ x: 'max-content' }} size="small"
          rowClassName={r => r.unrealized_pnl > 0 ? 'row-profit' : r.unrealized_pnl < 0 ? 'row-loss' : ''} />
      </Spin>
      <style>{`
        .row-profit td { background: #f6ffed !important; }
        .row-loss td { background: #fff1f0 !important; }
        @media (max-width: 768px) { .ant-table-cell { white-space: normal !important; word-break: break-all; } }
      `}</style>
    </Card>
  )
}
