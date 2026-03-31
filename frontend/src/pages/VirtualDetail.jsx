import { useEffect, useState, useMemo } from 'react'
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
  return (
    <span style={{ color: pnlColor(value), fontWeight: 500 }}>
      {n >= 0 ? '+' : ''}{n.toFixed(2)}
    </span>
  )
}

function RoeCell({ value }) {
  const n = parseFloat(value)
  if (isNaN(n)) return <span style={{ color: '#999' }}>-</span>
  return (
    <span style={{ color: pnlColor(value), fontWeight: 500 }}>
      {n >= 0 ? '+' : ''}{n.toFixed(2)}%
    </span>
  )
}

const sideColors = { '空': 'green', '多': 'red', '模拟空': 'cyan', '模拟多': 'orange' }

const columns = [
  {
    title: '时间',
    dataIndex: 'time',
    key: 'time',
    width: 100,
    render: v => v ? v.slice(5, 16) : '-',
  },
  {
    title: '币种',
    dataIndex: 'symbol',
    key: 'symbol',
    width: 110,
    filters: [],
    onFilter: (value, record) => record.symbol === value,
  },
  {
    title: '方向',
    dataIndex: 'side',
    key: 'side',
    width: 80,
    render: v => <Tag color={sideColors[v] || 'default'}>{v}</Tag>,
    filters: [
      { text: '空', value: '空' },
      { text: '多', value: '多' },
      { text: '模拟空', value: '模拟空' },
      { text: '模拟多', value: '模拟多' },
    ],
    onFilter: (value, record) => record.side === value,
  },
  {
    title: '开仓价',
    dataIndex: 'entry_price',
    key: 'entry_price',
    width: 110,
    render: v => v ? parseFloat(v).toFixed(4) : '-',
  },
  {
    title: '标记价',
    dataIndex: 'mark_price',
    key: 'mark_price',
    width: 110,
    render: v => v ? parseFloat(v).toFixed(4) : '-',
  },
  {
    title: '浮动盈亏',
    dataIndex: 'unrealized_pnl',
    key: 'unrealized_pnl',
    width: 110,
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => parseFloat(a.unrealized_pnl || 0) - parseFloat(b.unrealized_pnl || 0),
  },
  {
    title: 'ROE',
    dataIndex: 'roe_pct',
    key: 'roe_pct',
    width: 100,
    render: v => <RoeCell value={v} />,
    sorter: (a, b) => parseFloat(a.roe_pct || 0) - parseFloat(b.roe_pct || 0),
  },
]

export default function VirtualDetail() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)
  const [dates, setDates] = useState([])
  const [filterDate, setFilterDate] = useState(null)
  const [filterTime, setFilterTime] = useState(null)
  const [filterSide, setFilterSide] = useState(null)
  const [pagination, setPagination] = useState({ current: 1, pageSize: 50 })

  useEffect(() => {
    axios.get('/api/virtual_detail/dates').then(res => {
      setDates(res.data || [])
      if (res.data && res.data.length > 0) {
        setFilterDate(res.data[0])
      }
    })
  }, [])

  useEffect(() => {
    if (!filterDate) return
    setLoading(true)
    setFilterTime(null)
    axios.get(`/api/virtual_detail?date=${filterDate}`).then(res => {
      const rows = res.data.map((r, i) => ({ ...r, key: i })).reverse()
      columns.find(c => c.key === 'symbol').filters = [...new Set(rows.map(r => r.symbol))].map(s => ({ text: s, value: s }))
      setData(rows)
      setPagination(p => ({ ...p, current: 1 }))
    }).finally(() => setLoading(false))
  }, [filterDate])

  const timeOptions = useMemo(() => {
    if (!data.length) return []
    const times = [...new Set(data.map(r => r.time.slice(11)))].sort()
    return times.map(t => ({ label: t, value: t }))
  }, [data])

  const filtered = useMemo(() => {
    let result = data
    if (filterTime) result = result.filter(r => r.time.slice(11) === filterTime)
    if (filterSide) result = result.filter(r => r.side === filterSide)
    return result
  }, [data, filterTime, filterSide])

  return (
    <Card size="small">
      <Space style={{ marginBottom: 12 }}>
        <Select
          placeholder="选择日期"
          options={dates.map(d => ({ label: d, value: d }))}
          value={filterDate}
          onChange={val => setFilterDate(val)}
          style={{ width: 140 }}
        />
        <Select
          placeholder="选择时间快照"
          options={timeOptions}
          value={filterTime}
          onChange={val => { setFilterTime(val); setPagination(p => ({ ...p, current: 1 })) }}
          allowClear
          disabled={!filterDate}
          style={{ width: 130 }}
        />
        <Select
          placeholder="筛选方向"
          options={[
            { label: '空', value: '空' },
            { label: '多', value: '多' },
            { label: '模拟空', value: '模拟空' },
            { label: '模拟多', value: '模拟多' },
          ]}
          value={filterSide}
          onChange={val => { setFilterSide(val); setPagination(p => ({ ...p, current: 1 })) }}
          allowClear
          style={{ width: 110 }}
        />
      </Space>
      <Spin spinning={loading}>
        <Table
          columns={columns}
          dataSource={filtered}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            pageSizeOptions: [20, 50, 100, 200],
            showTotal: total => `共 ${total} 条`,
            onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
          }}
          scroll={{ x: 'max-content' }}
          size="small"
          rowClassName={record => {
            const pnl = parseFloat(record.unrealized_pnl)
            if (pnl > 0) return 'row-profit'
            if (pnl < 0) return 'row-loss'
            return ''
          }}
        />
      </Spin>
      <style>{`
        .row-profit td { background: #f6ffed !important; }
        .row-loss   td { background: #fff1f0 !important; }
        @media (max-width: 768px) {
          .ant-table-cell { white-space: normal !important; word-break: break-all; }
        }
      `}</style>
    </Card>
  )
}
