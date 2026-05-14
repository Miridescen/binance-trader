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
}

function SideTable({ label, color, rows, columns }) {
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
  const [groups, setGroups] = useState([])
  const [loading, setLoading] = useState(true)
  const columns = buildGroupColumns(window)

  useEffect(() => {
    setLoading(true)
    axios.get(`/api/virtual_groups?window=${window}`)
      .then(res => setGroups(res.data.map((g, i) => ({ ...g, key: i }))))
      .finally(() => setLoading(false))
  }, [window])

  const sumActualBy = side => groups
    .filter(g => g.side === side)
    .reduce((a, g) => a + parseFloat(g.sum_pnl_actual || 0), 0)
  const sumIfHeldBy = side => groups
    .filter(g => g.side === side)
    .reduce((a, g) => a + parseFloat(g.sum_pnl_if_held || 0), 0)
  const isFilteredSide = s => s?.includes('有过滤')
  const isUnfilteredSide = s => s?.includes('无过滤')

  // 有过滤 / 无过滤 各自的实际 PnL 和"若都走完 Nh"对照
  const totalActualFiltered   = groups.filter(g => isFilteredSide(g.side))
    .reduce((a, g) => a + parseFloat(g.sum_pnl_actual || 0), 0)
  const totalActualUnfiltered = groups.filter(g => isUnfilteredSide(g.side))
    .reduce((a, g) => a + parseFloat(g.sum_pnl_actual || 0), 0)
  const totalIfHeldFiltered   = groups.filter(g => isFilteredSide(g.side))
    .reduce((a, g) => a + parseFloat(g.sum_pnl_if_held || 0), 0)
  const totalIfHeldUnfiltered = groups.filter(g => isUnfilteredSide(g.side))
    .reduce((a, g) => a + parseFloat(g.sum_pnl_if_held || 0), 0)
  const nHitGroups   = groups.filter(g => g.n_hit > 0).length
  const nTimedGroups = groups.filter(g => g.n_timed > 0 && g.n_hit === 0).length

  return (
    <div>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="总盈亏 · 有过滤" value={Math.abs(totalActualFiltered).toFixed(2)} suffix="U"
              prefix={totalActualFiltered >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: totalActualFiltered >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="总盈亏 · 无过滤" value={Math.abs(totalActualUnfiltered).toFixed(2)} suffix="U"
              prefix={totalActualUnfiltered >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: totalActualUnfiltered >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title={`走完${window} · 有过滤`} value={Math.abs(totalIfHeldFiltered).toFixed(2)} suffix="U"
              prefix={totalIfHeldFiltered >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: totalIfHeldFiltered >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title={`走完${window} · 无过滤`} value={Math.abs(totalIfHeldUnfiltered).toFixed(2)} suffix="U"
              prefix={totalIfHeldUnfiltered >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              valueStyle={{ color: totalIfHeldUnfiltered >= 0 ? '#3f8600' : '#cf1322' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="+10u触发组" value={nHitGroups} suffix={`/ ${groups.length}`} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
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
                      <SideTable label="有过滤" color={p.tagColor} rows={fRows} columns={columns} />
                    </Col>
                    <Col xs={24} lg={12}>
                      <SideTable label="无过滤" color="default" rows={uRows} columns={columns} />
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
