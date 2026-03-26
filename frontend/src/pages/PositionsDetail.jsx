import { useEffect, useState, useMemo } from 'react'
import { Table, Card, Tag, Spin, DatePicker, Select, Space } from 'antd'
import dayjs from 'dayjs'
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

const columns = [
  {
    title: '时间',
    dataIndex: 'time',
    key: 'time',
    width: 160,
    fixed: 'left',
  },
  {
    title: '币种',
    dataIndex: 'symbol',
    key: 'symbol',
    width: 140,
    fixed: 'left',
    filters: [],
    onFilter: (value, record) => record.symbol === value,
  },
  {
    title: '方向',
    dataIndex: 'side',
    key: 'side',
    width: 70,
    render: v => <Tag color={v === 'SHORT' || v === '空' ? 'green' : 'red'}>{v}</Tag>,
    filters: [
      { text: 'LONG', value: 'LONG' },
      { text: 'SHORT', value: 'SHORT' },
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
    title: '持仓量',
    dataIndex: 'position_amt',
    key: 'position_amt',
    width: 100,
    render: v => v ? parseFloat(v) : '-',
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

export default function PositionsDetail() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 })
  const [filterDate, setFilterDate] = useState(null)   // dayjs 对象
  const [filterTime, setFilterTime] = useState(null)   // 具体时间字符串，如 "11:34:50"

  useEffect(() => {
    axios.get('/api/positions_detail').then(res => {
      const rows = res.data
        .map((r, i) => ({ ...r, key: i }))
        .reverse()
      columns.find(c => c.key === 'symbol').filters = [...new Set(rows.map(r => r.symbol))].map(s => ({ text: s, value: s }))
      setData(rows)
    }).finally(() => setLoading(false))
  }, [])

  // 选中日期对应的所有时间快照点
  const timeOptions = useMemo(() => {
    if (!filterDate) return []
    const dateStr = filterDate.format('YYYY-MM-DD')
    const times = [...new Set(
      data.filter(r => r.time.startsWith(dateStr)).map(r => r.time.slice(11))
    )].sort()
    return times.map(t => ({ label: t, value: t }))
  }, [filterDate, data])

  // 筛选后的数据
  const filtered = useMemo(() => {
    if (!filterDate) return data
    const dateStr = filterDate.format('YYYY-MM-DD')
    return data.filter(r => {
      if (!r.time.startsWith(dateStr)) return false
      if (filterTime && r.time.slice(11) !== filterTime) return false
      return true
    })
  }, [data, filterDate, filterTime])

  const handleDateChange = (val) => {
    setFilterDate(val)
    setFilterTime(null)
    setPagination(p => ({ ...p, current: 1 }))
  }

  const handleTimeChange = (val) => {
    setFilterTime(val)
    setPagination(p => ({ ...p, current: 1 }))
  }

  return (
    <Card size="small">
      <Space style={{ marginBottom: 12 }}>
        <DatePicker
          placeholder="选择日期"
          onChange={handleDateChange}
          allowClear
        />
        <Select
          placeholder="选择时间快照"
          options={timeOptions}
          value={filterTime}
          onChange={handleTimeChange}
          allowClear
          disabled={!filterDate}
          style={{ width: 160 }}
        />
      </Space>
      <Spin spinning={loading}>
        <Table
          columns={columns}
          dataSource={filtered}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            showTotal: total => `共 ${total} 条`,
            onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
          }}
          scroll={{ x: 900 }}
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
      `}</style>
    </Card>
  )
}
