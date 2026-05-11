import { useEffect, useState } from 'react'
import { Table, Card, Tag, Spin, Row, Col, Statistic, Tabs } from 'antd'
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

const groupColumns = [
  {
    title: '开仓时间',
    dataIndex: 'open_time',
    key: 'open_time',
    width: 130,
    render: v => v ? v.slice(5, 16) : '-',
    sorter: (a, b) => (a.open_time || '').localeCompare(b.open_time || ''),
    defaultSortOrder: 'descend',
  },
  {
    title: '笔数',
    dataIndex: 'n_orders',
    key: 'n_orders',
    width: 60,
  },
  {
    title: '触发',
    key: 'trigger_kind',
    width: 95,
    render: (_, r) => {
      if (r.n_hit > 0) return <Tag color="gold">+10u</Tag>
      if (r.n_timed > 0) return <Tag color="default">4h 定平</Tag>
      return <Tag>持仓中</Tag>
    },
    filters: [
      { text: '+10u 触发', value: 'hit' },
      { text: '4h 定平', value: 'timed' },
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
    title: '走完4h',
    dataIndex: 'sum_pnl_if_held',
    key: 'sum_pnl_if_held',
    width: 110,
    render: (v, r) => {
      if (r.n_hit === 0) return <span style={{ color: '#bbb' }}>同上</span>
      return <PnlCell value={v} />
    },
    sorter: (a, b) => parseFloat(a.sum_pnl_if_held || 0) - parseFloat(b.sum_pnl_if_held || 0),
  },
  {
    title: '差额',
    key: 'diff',
    width: 90,
    render: (_, r) => {
      if (r.n_hit === 0) return <span style={{ color: '#bbb' }}>-</span>
      const a = parseFloat(r.sum_pnl_actual || 0)
      const b = parseFloat(r.sum_pnl_if_held || 0)
      const d = a - b
      const color = d >= 0 ? '#3f8600' : '#cf1322'
      return <span style={{ color, fontWeight: 500 }}>{d >= 0 ? '+' : ''}{d.toFixed(2)}</span>
    },
  },
]

function SideTable({ side, label, color, rows }) {
  const pnl = rows.reduce((a, r) => a + parseFloat(r.sum_pnl_actual || 0), 0)
  return (
    <Card
      size="small"
      title={
        <span>
          <Tag color={color}>{label}</Tag>
          <span style={{ color: pnlColor(pnl), fontWeight: 500, marginLeft: 4 }}>
            {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} U
          </span>
          <span style={{ color: '#999', fontSize: 12, marginLeft: 8 }}>{rows.length} 组</span>
        </span>
      }
    >
      <Table
        columns={groupColumns}
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

export default function VirtualLog4h() {
  const [groups, setGroups] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get('/api/virtual_4h_groups')
      .then(res => setGroups(res.data.map((g, i) => ({ ...g, key: i }))))
      .finally(() => setLoading(false))
  }, [])

  const sumActualBy = side => groups
    .filter(g => g.side === side)
    .reduce((a, g) => a + parseFloat(g.sum_pnl_actual || 0), 0)

  const totalActual = groups.reduce((a, g) => a + parseFloat(g.sum_pnl_actual || 0), 0)
  const totalIfHeld = groups.reduce((a, g) => a + parseFloat(g.sum_pnl_if_held || 0), 0)
  const nHitGroups   = groups.filter(g => g.n_hit > 0).length
  const nTimedGroups = groups.filter(g => g.n_timed > 0 && g.n_hit === 0).length

  return (
    <div>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="总盈亏(实际)" value={Math.abs(totalActual).toFixed(2)} suffix="U"
              prefix={totalActual >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: totalActual >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="若都走完4h(对照)" value={Math.abs(totalIfHeld).toFixed(2)} suffix="U"
              prefix={totalIfHeld >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: totalIfHeld >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="+10u触发组" value={nHitGroups} suffix={`/ ${groups.length}`} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="4h定平组" value={nTimedGroups} suffix={`/ ${groups.length}`} />
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
              return {
                key: p.key,
                label: (
                  <span>
                    {p.label}{' '}
                    <span style={{ color: pnlColor(fPnl + uPnl), fontSize: 12 }}>
                      ({(fPnl + uPnl) >= 0 ? '+' : ''}{(fPnl + uPnl).toFixed(1)})
                    </span>
                  </span>
                ),
                children: (
                  <Row gutter={[12, 12]}>
                    <Col xs={24} lg={12}>
                      <SideTable side={p.filtered} label="有过滤" color={p.tagColor} rows={fRows} />
                    </Col>
                    <Col xs={24} lg={12}>
                      <SideTable side={p.unfiltered} label="无过滤" color="default" rows={uRows} />
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
