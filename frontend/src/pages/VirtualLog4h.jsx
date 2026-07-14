import { useEffect, useMemo, useState } from 'react'
import { Table, Card, Tag, Spin, Row, Col, Statistic, Tabs, Select, Space } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons'
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

const SIDE_PAIRS = [
  { key: 'gainer_short', label: '涨幅榜-空', filtered: '涨幅榜-空（有过滤）', unfiltered: '涨幅榜-空（无过滤）', tagColor: 'green' },
  { key: 'gainer_long',  label: '涨幅榜-多', filtered: '涨幅榜-多（有过滤）', unfiltered: '涨幅榜-多（无过滤）', tagColor: 'red' },
  { key: 'loser_short',  label: '跌幅榜-空', filtered: '跌幅榜-空（有过滤）', unfiltered: '跌幅榜-空（无过滤）', tagColor: 'cyan' },
  { key: 'loser_long',   label: '跌幅榜-多', filtered: '跌幅榜-多（有过滤）', unfiltered: '跌幅榜-多（无过滤）', tagColor: 'orange' },
]

function buildGroupColumns(windowLabel) {
  return [
    {
      title: '开仓时间',
      dataIndex: 'open_time',
      key: 'open_time',
      width: 130,
      render: v => v ? v.slice(5, 16) : '-',
      sorter: (a, b) => (a.open_time || '').localeCompare(b.open_time || ''),
      defaultSortOrder: 'descend',
    },
    { title: '笔数', dataIndex: 'n_orders', key: 'n_orders', width: 60 },
    {
      title: '触发',
      key: 'trigger_kind',
      width: 100,
      render: (_, r) => {
        if (r.n_hit > 0) return <Tag color="gold">+10u</Tag>
        if (r.n_timed > 0) return <Tag color="default">{windowLabel} 定平</Tag>
        return <Tag>持仓中</Tag>
      },
      filters: [
        { text: '+10u 触发', value: 'hit' },
        { text: `${windowLabel} 定平`, value: 'timed' },
      ],
      onFilter: (value, r) => value === 'hit' ? r.n_hit > 0 : r.n_timed > 0,
    },
    {
      title: '实际 PnL',
      dataIndex: 'sum_pnl_actual',
      key: 'sum_pnl_actual',
      width: 110,
      render: v => <PnlCell value={v} />,
      sorter: (a, b) => parseFloat(a.sum_pnl_actual || 0) - parseFloat(b.sum_pnl_actual || 0),
    },
    {
      title: `走完${windowLabel}`,
      dataIndex: 'sum_pnl_if_held',
      key: 'sum_pnl_if_held',
      width: 110,
      render: v => <PnlCell value={v} />,
      sorter: (a, b) => parseFloat(a.sum_pnl_if_held || 0) - parseFloat(b.sum_pnl_if_held || 0),
    },
    {
      title: '差额',
      key: 'diff',
      width: 90,
      render: (_, r) => {
        const a = parseFloat(r.sum_pnl_actual || 0)
        const b = parseFloat(r.sum_pnl_if_held || 0)
        const d = a - b
        const color = d > 0 ? '#3f8600' : (d < 0 ? '#cf1322' : '#999')
        return <span style={{ color, fontWeight: 500 }}>{d >= 0 ? '+' : ''}{d.toFixed(2)}</span>
      },
    },
  ]
}

function SideTable({ label, color, rows, columns, windowLabel }) {
  const pnl = rows.reduce((a, r) => a + parseFloat(r.sum_pnl_actual || 0), 0)
  const pnlIfHeld = rows.reduce((a, r) => a + parseFloat(r.sum_pnl_if_held || 0), 0)
  return (
    <Card
      size="small"
      title={
        <span>
          <Tag color={color}>{label}</Tag>
          <span style={{ color: '#999', fontSize: 12, marginLeft: 4 }}>
            实际 <span style={{ color: pnlColor(pnl), fontWeight: 500 }}>
              {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}
            </span>
          </span>
          <span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>
            走完{windowLabel} <span style={{ color: pnlColor(pnlIfHeld), fontWeight: 500 }}>
              {pnlIfHeld >= 0 ? '+' : ''}{pnlIfHeld.toFixed(2)}
            </span>
          </span>
          <span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>{rows.length} 组</span>
        </span>
      }
    >
      <Table
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 30, showSizeChanger: true, pageSizeOptions: [20, 30, 50, 100] }}
        scroll={{ x: 'max-content' }}
        size="small"
        rowClassName={r => {
          const a = parseFloat(r.sum_pnl_actual || 0)
          if (a > 0) return 'row-profit'
          if (a < 0) return 'row-loss'
          return ''
        }}
      />
    </Card>
  )
}

export default function VirtualLogWindow({ window = '4h' }) {
  const [allGroups, setAllGroups] = useState([])
  const [loading, setLoading] = useState(true)
  const [timeFilter, setTimeFilter] = useState('all')
  const columns = buildGroupColumns(window)

  useEffect(() => {
    setLoading(true)
    setTimeFilter('all')
    axios.get(`/api/virtual_groups?window=${window}`)
      .then(res => setAllGroups(res.data.map((g, i) => ({ ...g, key: i }))))
      .finally(() => setLoading(false))
  }, [window])

  // 所有出现过的开仓时段（HH:MM）
  const allTimeOptions = useMemo(() => {
    const set = new Set()
    for (const g of allGroups) {
      if (g.open_time) set.add(g.open_time.slice(11, 16))
    }
    return [...set].sort()
  }, [allGroups])

  // 按时段过滤
  const groups = useMemo(() => {
    if (timeFilter === 'all') return allGroups
    return allGroups.filter(g => g.open_time?.slice(11, 16) === timeFilter)
  }, [allGroups, timeFilter])

  const sumActualBy = side => groups
    .filter(g => g.side === side)
    .reduce((a, g) => a + parseFloat(g.sum_pnl_actual || 0), 0)

  const nHitGroups   = groups.filter(g => g.n_hit > 0).length
  const nTimedGroups = groups.filter(g => g.n_timed > 0 && g.n_hit === 0).length

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Space wrap>
          <span style={{ color: '#666' }}>按时段筛选：</span>
          <Select
            size="small"
            style={{ minWidth: 140 }}
            value={timeFilter}
            onChange={setTimeFilter}
            options={[
              { label: '全部时段', value: 'all' },
              ...allTimeOptions.map(t => ({ label: t, value: t })),
            ]}
          />
          {timeFilter !== 'all' && (
            <Tag color="blue">仅看 {timeFilter} 周期</Tag>
          )}
        </Space>
      </div>

      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={12} md={12}>
          <Card size="small">
            <Statistic title="+10u触发组" value={nHitGroups} suffix={`/ ${groups.length}`} />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={12}>
          <Card size="small">
            <Statistic title={`${window}定平组`} value={nTimedGroups} suffix={`/ ${groups.length}`} />
          </Card>
        </Col>
      </Row>

      <Card size="small">
        <Spin spinning={loading}>
          <Tabs
            defaultActiveKey={SIDE_PAIRS[0].key}
            items={SIDE_PAIRS.map(p => {
              const fRows = groups.filter(g => g.side === p.filtered)
              const uRows = groups.filter(g => g.side === p.unfiltered)
              const fPnl = sumActualBy(p.filtered)
              const uPnl = sumActualBy(p.unfiltered)
              const fmtPnl = v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}`
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
                      <SideTable label="有过滤" color={p.tagColor} rows={fRows} columns={columns} windowLabel={window} />
                    </Col>
                    <Col xs={24} lg={12}>
                      <SideTable label="无过滤" color="default" rows={uRows} columns={columns} windowLabel={window} />
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
