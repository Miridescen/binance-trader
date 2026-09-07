import { useEffect, useState } from 'react'
import { Table, Spin, Select, Segmented } from 'antd'
import axios from 'axios'
import { PnlCell, Num, Chip, SideChip, Panel, PageHeader } from '../components/ui'

// 账户 → 周期/记录接口前缀
const ACCT_OPTIONS = [
  { label: '子账号1 · 8h', value: '8h' },
  { label: '子账号2 · 24h', value: '24h' },
]

const columns = [
  { title: '开仓时间', dataIndex: 'open_time', key: 'open_time', width: 110,
    render: v => v ? <span className="num" style={{ fontWeight: 500 }}>{v.slice(5, 16)}</span> : '-' },
  { title: '平仓时间', dataIndex: 'close_time', key: 'close_time', width: 110,
    render: v => v ? <span className="num muted">{v.slice(5, 16)}</span> : <Chip tone="blue">持仓中</Chip> },
  { title: '币种', dataIndex: 'symbol', key: 'symbol', width: 120,
    render: v => <span style={{ fontWeight: 600 }}>{v}</span> },
  { title: '方向', dataIndex: 'side', key: 'side', width: 150,
    render: v => <SideChip side={v} />,
    filters: [
      { text: '涨幅榜-空（无过滤）', value: '涨幅榜-空（无过滤）' },
      { text: '跌幅榜-空（无过滤）', value: '跌幅榜-空（无过滤）' },
    ],
    onFilter: (value, record) => record.side === value,
  },
  { title: '开仓价', dataIndex: 'entry_price', key: 'entry_price', width: 100, align: 'right',
    render: v => <Num value={v} digits={6} /> },
  { title: '平仓价', dataIndex: 'close_price', key: 'close_price', width: 100, align: 'right',
    render: v => <Num value={v} digits={6} /> },
  { title: '数量', dataIndex: 'position_amt', key: 'position_amt', width: 90, align: 'right',
    render: v => <Num value={v} digits={4} /> },
  { title: '杠杆', dataIndex: 'leverage', key: 'leverage', width: 60, align: 'right',
    render: v => v ? <span className="num">{v}x</span> : '-' },
  { title: '盈亏(USDT)', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 110, align: 'right',
    render: v => <PnlCell value={v} digits={4} />,
    sorter: (a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0),
  },
  { title: 'ROE', dataIndex: 'roe_pct', key: 'roe_pct', width: 90, align: 'right',
    render: v => <PnlCell value={v} digits={2} suffix="%" />,
    sorter: (a, b) => (a.roe_pct || 0) - (b.roe_pct || 0),
  },
  { title: '开仓手续费', dataIndex: 'open_commission', key: 'open_commission', width: 100, align: 'right',
    render: v => v != null ? <span className="num muted">{parseFloat(v).toFixed(4)}</span> : '-' },
  { title: '平仓手续费', dataIndex: 'close_commission', key: 'close_commission', width: 100, align: 'right',
    render: v => v != null ? <span className="num muted">{parseFloat(v).toFixed(4)}</span> : '-' },
  { title: '资金费', dataIndex: 'funding_fee', key: 'funding_fee', width: 90, align: 'right',
    render: v => v != null ? <PnlCell value={v} digits={4} /> : '-' },
  { title: '平仓原因', dataIndex: 'close_reason', key: 'close_reason', width: 100,
    render: v => v ? <Chip tone="grey">{v}</Chip> : '-' },
]

export default function OpenLog() {
  const [acct, setAcct] = useState('8h')     // '8h'（子账号1）| '24h'（子账号2）
  const [anchors, setAnchors] = useState([])
  const [selected, setSelected] = useState(null)
  const [rows, setRows] = useState([])
  const [loadingAnchors, setLoadingAnchors] = useState(true)
  const [loadingRows, setLoadingRows] = useState(false)

  // 切账户 → 重拉周期下拉
  useEffect(() => {
    setLoadingAnchors(true)
    setSelected(null)
    setRows([])
    axios.get(`/api/open_log_${acct}/anchors`)
      .then(res => {
        setAnchors(res.data || [])
        if (res.data && res.data.length > 0) {
          setSelected(res.data[0].anchor)  // 默认选最新一个周期
        }
      })
      .finally(() => setLoadingAnchors(false))
  }, [acct])

  // 选周期后拉该周期数据
  useEffect(() => {
    if (!selected) {
      setRows([])
      return
    }
    setLoadingRows(true)
    axios.get(`/api/open_log_${acct}?anchor=${encodeURIComponent(selected)}`)
      .then(res => setRows((res.data || []).map((r, i) => ({ ...r, key: i }))))
      .finally(() => setLoadingRows(false))
  }, [acct, selected])

  // 该周期合计
  const sum = arr => arr.reduce((a, b) => a + b, 0)
  const grossPnl = sum(rows.map(r => parseFloat(r.unrealized_pnl) || 0))
  const totalComm = sum(rows.map(r =>
    (parseFloat(r.open_commission) || 0) + (parseFloat(r.close_commission) || 0)))
  const totalFunding = sum(rows.map(r => parseFloat(r.funding_fee) || 0))
  const netPnl = grossPnl + totalComm + totalFunding

  return (
    <div className="panel-stack">
      <PageHeader
        title="开仓记录"
        subtitle="按账户与周期查看每一笔实盘开仓的成交、费用与盈亏"
        extra={
          <div className="toolbar">
            <Segmented options={ACCT_OPTIONS} value={acct} onChange={setAcct} />
            <span className="toolbar-label">周期</span>
            <Select
              style={{ minWidth: 220 }}
              placeholder={loadingAnchors ? '加载中...' : (anchors.length === 0 ? '暂无周期' : '请选择')}
              loading={loadingAnchors}
              value={selected}
              onChange={setSelected}
              options={anchors.map(a => ({
                label: `${a.anchor}  (${a.n} 笔)`,
                value: a.anchor,
              }))}
              disabled={anchors.length === 0}
            />
          </div>
        }
      />

      <Panel
        flush
        title="周期明细"
        subtitle={selected ? `${selected} · ${rows.length} 笔` : ''}
        extra={rows.length > 0 && (
          <div className="kv-row">
            <div className="kv"><span className="kv-k">毛 PnL</span><span className="kv-v"><PnlCell value={grossPnl} /></span></div>
            <div className="kv"><span className="kv-k">手续费</span><span className="kv-v"><PnlCell value={totalComm} /></span></div>
            <div className="kv"><span className="kv-k">资金费</span><span className="kv-v"><PnlCell value={totalFunding} /></span></div>
            <div className="kv"><span className="kv-k">净 PnL</span><span className="kv-v" style={{ fontSize: 16 }}><PnlCell value={netPnl} /></span></div>
          </div>
        )}
      >
        <Spin spinning={loadingRows}>
          <Table
            columns={columns}
            dataSource={rows}
            pagination={{
              pageSize: 10,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50, 100],
              showTotal: total => `共 ${total} 条`,
              size: 'small',
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
            locale={{ emptyText: anchors.length === 0 ? `暂无任何 ${acct} 周期开仓数据` : '该周期暂无数据' }}
          />
        </Spin>
      </Panel>
    </div>
  )
}
