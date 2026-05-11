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

function groupColumns(tagColor) {
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
    {
      title: '方向',
      dataIndex: 'side',
      key: 'side',
      width: 80,
      render: v => {
        const isFiltered = v?.includes('有过滤')
        return <Tag color={isFiltered ? tagColor : 'default'}>{isFiltered ? '有过滤' : '无过滤'}</Tag>
      },
      filters: [
        { text: '有过滤', value: '有过滤' },
        { text: '无过滤', value: '无过滤' },
      ],
      onFilter: (value, r) => r.side?.includes(value),
    },
    {
      title: '笔数',
      dataIndex: 'n_orders',
      key: 'n_orders',
      width: 60,
    },
    {
      title: '触发类型',
      key: 'trigger_kind',
      width: 100,
      render: (_, r) => {
        if (r.n_hit > 0) return <Tag color="gold">+10u 触发</Tag>
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
      title: '实际平仓 PnL',
      dataIndex: 'sum_pnl_actual',
      key: 'sum_pnl_actual',
      width: 130,
      render: v => <PnlCell value={v} />,
      sorter: (a, b) => parseFloat(a.sum_pnl_actual || 0) - parseFloat(b.sum_pnl_actual || 0),
    },
    {
      title: '走完4h PnL',
      dataIndex: 'sum_pnl_if_held',
      key: 'sum_pnl_if_held',
      width: 130,
      render: (v, r) => {
        if (r.n_hit === 0) return <span style={{ color: '#bbb' }}>同上</span>
        return <PnlCell value={v} />
      },
      sorter: (a, b) => parseFloat(a.sum_pnl_if_held || 0) - parseFloat(b.sum_pnl_if_held || 0),
    },
    {
      title: '+10u vs 走完',
      key: 'diff',
      width: 120,
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

      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {SIDE_PAIRS.map(p => {
          const fPnl = sumActualBy(p.filtered)
          const uPnl = sumActualBy(p.unfiltered)
          return (
            <Col xs={24} sm={12} md={6} key={p.key}>
              <Card size="small" title={p.label}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ color: '#999', fontSize: 12 }}>有过滤</div>
                    <b style={{ color: pnlColor(fPnl), fontSize: 16 }}>{fPnl >= 0 ? '+' : ''}{fPnl.toFixed(1)} U</b>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ color: '#999', fontSize: 12 }}>无过滤</div>
                    <b style={{ color: pnlColor(uPnl), fontSize: 16 }}>{uPnl >= 0 ? '+' : ''}{uPnl.toFixed(1)} U</b>
                  </div>
                </div>
              </Card>
            </Col>
          )
        })}
      </Row>

      <Card size="small">
        <Spin spinning={loading}>
          <Tabs
            defaultActiveKey={SIDE_PAIRS[0].key}
            items={SIDE_PAIRS.map(p => {
              const rows = groups.filter(g => g.side === p.filtered || g.side === p.unfiltered)
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
                  <>
                    <div style={{ marginBottom: 8, color: '#666', fontSize: 13 }}>
                      <span style={{ marginRight: 16 }}>
                        <b>有过滤</b>: <span style={{ color: pnlColor(fPnl) }}>{fPnl >= 0 ? '+' : ''}{fPnl.toFixed(2)} U</span>
                      </span>
                      <span>
                        <b>无过滤</b>: <span style={{ color: pnlColor(uPnl) }}>{uPnl >= 0 ? '+' : ''}{uPnl.toFixed(2)} U</span>
                      </span>
                    </div>
                    <Table
                      columns={groupColumns(p.tagColor)}
                      dataSource={rows}
                      pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], showTotal: t => `共 ${t} 组` }}
                      scroll={{ x: 'max-content' }}
                      size="small"
                      rowClassName={r => {
                        const a = parseFloat(r.sum_pnl_actual || 0)
                        if (a > 0) return 'row-profit'
                        if (a < 0) return 'row-loss'
                        return ''
                      }}
                    />
                  </>
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
