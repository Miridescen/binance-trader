import { useEffect, useState } from 'react'
import { Table, Card, Tag, Spin, Select, Space } from 'antd'
import axios from 'axios'

function pnlColor(val) {
  const n = parseFloat(val)
  if (n > 0) return '#3f8600'
  if (n < 0) return '#cf1322'
  return '#999'
}

function PnlCell({ value, digits = 4 }) {
  const n = parseFloat(value)
  if (isNaN(n)) return <span style={{ color: '#999' }}>-</span>
  return (
    <span style={{ color: pnlColor(n), fontWeight: 500 }}>
      {n >= 0 ? '+' : ''}{n.toFixed(digits)}
    </span>
  )
}

function RoeCell({ value }) {
  const n = parseFloat(value)
  if (isNaN(n)) return <span style={{ color: '#999' }}>-</span>
  return (
    <span style={{ color: pnlColor(n), fontWeight: 500 }}>
      {n >= 0 ? '+' : ''}{n.toFixed(2)}%
    </span>
  )
}

const columns = [
  { title: '开仓时间', dataIndex: 'open_time', key: 'open_time', width: 110,
    render: v => v ? v.slice(5, 16) : '-' },
  { title: '平仓时间', dataIndex: 'close_time', key: 'close_time', width: 110,
    render: v => v ? v.slice(5, 16) : <Tag color="blue">持仓中</Tag> },
  { title: '币种', dataIndex: 'symbol', key: 'symbol', width: 110 },
  { title: '方向', dataIndex: 'side', key: 'side', width: 130,
    render: v => {
      let color = 'default'
      if (v?.includes('涨幅') && v?.includes('空')) color = 'green'
      else if (v?.includes('跌幅') && v?.includes('空')) color = 'cyan'
      return <Tag color={color}>{v}</Tag>
    },
    filters: [
      { text: '涨幅榜-空（无过滤）', value: '涨幅榜-空（无过滤）' },
      { text: '跌幅榜-空（无过滤）', value: '跌幅榜-空（无过滤）' },
    ],
    onFilter: (value, record) => record.side === value,
  },
  { title: '开仓价', dataIndex: 'entry_price', key: 'entry_price', width: 100,
    render: v => v ? parseFloat(v).toFixed(6) : '-' },
  { title: '平仓价', dataIndex: 'close_price', key: 'close_price', width: 100,
    render: v => v ? parseFloat(v).toFixed(6) : '-' },
  { title: '数量', dataIndex: 'position_amt', key: 'position_amt', width: 90,
    render: v => v ? parseFloat(v).toFixed(4) : '-' },
  { title: '杠杆', dataIndex: 'leverage', key: 'leverage', width: 60,
    render: v => v ? `${v}x` : '-' },
  { title: '盈亏(USDT)', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 110,
    render: v => <PnlCell value={v} digits={4} />,
    sorter: (a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0),
  },
  { title: 'ROE', dataIndex: 'roe_pct', key: 'roe_pct', width: 90,
    render: v => <RoeCell value={v} />,
    sorter: (a, b) => (a.roe_pct || 0) - (b.roe_pct || 0),
  },
  { title: '开仓手续费', dataIndex: 'open_commission', key: 'open_commission', width: 100,
    render: v => v != null ? parseFloat(v).toFixed(4) : '-' },
  { title: '平仓手续费', dataIndex: 'close_commission', key: 'close_commission', width: 100,
    render: v => v != null ? parseFloat(v).toFixed(4) : '-' },
  { title: '资金费', dataIndex: 'funding_fee', key: 'funding_fee', width: 90,
    render: v => v != null ? <PnlCell value={v} digits={4} /> : '-' },
  { title: '平仓原因', dataIndex: 'close_reason', key: 'close_reason', width: 95,
    render: v => v ? <Tag>{v}</Tag> : '-' },
]

export default function OpenLog() {
  const [anchors, setAnchors] = useState([])
  const [selected, setSelected] = useState(null)
  const [rows, setRows] = useState([])
  const [loadingAnchors, setLoadingAnchors] = useState(true)
  const [loadingRows, setLoadingRows] = useState(false)

  // 拉周期下拉
  useEffect(() => {
    axios.get('/api/open_log_8h/anchors')
      .then(res => {
        setAnchors(res.data || [])
        if (res.data && res.data.length > 0) {
          setSelected(res.data[0].anchor)  // 默认选最新一个周期
        }
      })
      .finally(() => setLoadingAnchors(false))
  }, [])

  // 选周期后拉该周期数据
  useEffect(() => {
    if (!selected) {
      setRows([])
      return
    }
    setLoadingRows(true)
    axios.get(`/api/open_log_8h?anchor=${encodeURIComponent(selected)}`)
      .then(res => setRows((res.data || []).map((r, i) => ({ ...r, key: i }))))
      .finally(() => setLoadingRows(false))
  }, [selected])

  // 该周期合计
  const sum = arr => arr.reduce((a, b) => a + b, 0)
  const grossPnl = sum(rows.map(r => parseFloat(r.unrealized_pnl) || 0))
  const totalComm = sum(rows.map(r =>
    (parseFloat(r.open_commission) || 0) + (parseFloat(r.close_commission) || 0)))
  const totalFunding = sum(rows.map(r => parseFloat(r.funding_fee) || 0))
  const netPnl = grossPnl + totalComm + totalFunding

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <span>选择周期：</span>
          <Select
            style={{ minWidth: 240 }}
            placeholder={loadingAnchors ? '加载中...' : '请选择'}
            loading={loadingAnchors}
            value={selected}
            onChange={setSelected}
            options={anchors.map(a => ({
              label: `${a.anchor}  (${a.n} 笔)`,
              value: a.anchor,
            }))}
            disabled={anchors.length === 0}
          />
          {rows.length > 0 && (
            <span style={{ color: '#666', fontSize: 13, marginLeft: 16 }}>
              本周期合计：
              毛 <PnlCell value={grossPnl} digits={2} />
              {' '}手续费 <PnlCell value={totalComm} digits={2} />
              {' '}资金费 <PnlCell value={totalFunding} digits={2} />
              {' '}净 <PnlCell value={netPnl} digits={2} />
            </span>
          )}
        </Space>
      </Card>

      <Card size="small">
        <Spin spinning={loadingRows}>
          <Table
            columns={columns}
            dataSource={rows}
            pagination={{
              pageSize: 50,
              showSizeChanger: true,
              pageSizeOptions: [20, 50, 100],
              showTotal: total => `共 ${total} 条`,
            }}
            scroll={{ x: 'max-content' }}
            size="small"
            rowClassName={record => {
              if (!record.close_time) return 'row-open'
              const pnl = parseFloat(record.unrealized_pnl)
              if (pnl > 0) return 'row-profit'
              if (pnl < 0) return 'row-loss'
              return ''
            }}
            locale={{ emptyText: anchors.length === 0 ? '暂无任何 8h 周期开仓数据' : '该周期暂无数据' }}
          />
        </Spin>
      </Card>

      <style>{`
        .row-profit td { background: #f6ffed !important; }
        .row-loss   td { background: #fff1f0 !important; }
        .row-open   td { background: #e6f4ff !important; }
        @media (max-width: 768px) {
          .ant-table-cell { white-space: normal !important; word-break: break-all; }
        }
      `}</style>
    </div>
  )
}
