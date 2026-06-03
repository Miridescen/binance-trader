import { useEffect, useMemo, useState } from 'react'
import { Card, Row, Col, Statistic, Spin, Tag, Select, Button, Empty, Table } from 'antd'
import { ReloadOutlined, LineChartOutlined } from '@ant-design/icons'
import axios from 'axios'

function pnlColor(v) {
  const n = parseFloat(v)
  if (n > 0) return '#3f8600'
  if (n < 0) return '#cf1322'
  return '#999'
}

function pct(v, digits = 2) {
  const n = parseFloat(v)
  if (isNaN(n)) return '-'
  return <span style={{ color: pnlColor(n), fontWeight: 500 }}>{n >= 0 ? '+' : ''}{n.toFixed(digits)}%</span>
}

const contractTypeLabel = t => t === 'CURRENT_QUARTER' ? '当季' : (t === 'NEXT_QUARTER' ? '次季' : t)

// ── 简易 SVG 折线图 ──
function MiniLineChart({ data, valueKey, height = 240, color = '#1677ff', yLabel = '' }) {
  if (!data || data.length < 2) {
    return <Empty description="数据点不足，等数据累积后再看" style={{ padding: 30 }} />
  }
  const values = data.map(d => parseFloat(d[valueKey]) || 0)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const padding = range * 0.1
  const yMin = min - padding
  const yMax = max + padding

  const width = 800
  const padX = 50
  const padY = 30
  const innerW = width - 2 * padX
  const innerH = height - 2 * padY

  const xOf = i => padX + (i / (data.length - 1)) * innerW
  const yOf = v => padY + innerH - ((v - yMin) / (yMax - yMin)) * innerH

  const pathD = values.map((v, i) => `${i === 0 ? 'M' : 'L'} ${xOf(i)} ${yOf(v)}`).join(' ')

  // Y 轴刻度（5 档）
  const yTicks = []
  for (let i = 0; i <= 4; i++) {
    const v = yMin + (yMax - yMin) * (i / 4)
    yTicks.push({ y: yOf(v), v })
  }
  // X 轴刻度（5 档）
  const xTicks = []
  for (let i = 0; i <= 4; i++) {
    const idx = Math.round((i / 4) * (data.length - 1))
    xTicks.push({ x: xOf(idx), label: data[idx].time?.slice(5, 16) || '' })
  }

  // 零线
  const zeroY = yMin <= 0 && yMax >= 0 ? yOf(0) : null

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height }}>
      {/* 网格 + Y 轴标签 */}
      {yTicks.map((t, i) => (
        <g key={i}>
          <line x1={padX} y1={t.y} x2={width - padX} y2={t.y} stroke="#eee" />
          <text x={padX - 6} y={t.y + 4} textAnchor="end" fontSize={11} fill="#888">
            {t.v.toFixed(2)}{yLabel}
          </text>
        </g>
      ))}
      {/* 零线 */}
      {zeroY != null && <line x1={padX} y1={zeroY} x2={width - padX} y2={zeroY} stroke="#bbb" strokeDasharray="3,3" />}
      {/* X 轴标签 */}
      {xTicks.map((t, i) => (
        <text key={i} x={t.x} y={height - padY + 16} textAnchor="middle" fontSize={11} fill="#888">{t.label}</text>
      ))}
      {/* 数据线 */}
      <path d={pathD} fill="none" stroke={color} strokeWidth={2} />
      {/* 端点 */}
      <circle cx={xOf(values.length - 1)} cy={yOf(values[values.length - 1])} r={4} fill={color} />
    </svg>
  )
}

const historyColumns = [
  { title: '时间', dataIndex: 'time', key: 'time', width: 140,
    render: v => v?.slice(5, 16) || '-' },
  { title: '现货价', dataIndex: 'spot_price', key: 'spot', width: 100,
    render: v => parseFloat(v).toFixed(2) },
  { title: '合约价', dataIndex: 'futures_price', key: 'fut', width: 100,
    render: v => parseFloat(v).toFixed(2) },
  { title: '基差', dataIndex: 'basis', key: 'basis', width: 100,
    render: v => {
      const n = parseFloat(v)
      return <span style={{ color: pnlColor(n) }}>{n >= 0 ? '+' : ''}{n.toFixed(2)}</span>
    },
  },
  { title: '基差 %', dataIndex: 'basis_pct', key: 'pct', width: 90,
    render: v => pct(v, 3) },
  { title: '年化', dataIndex: 'annualized_pct', key: 'ann', width: 100,
    render: v => pct(v, 2) },
]

export default function BasisDashboard() {
  const [latest, setLatest] = useState([])
  const [stats, setStats] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedSymbol, setSelectedSymbol] = useState(null)
  const [history, setHistory] = useState([])
  const [historyHours, setHistoryHours] = useState(72)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [updated, setUpdated] = useState(null)

  const fetchAll = async () => {
    setLoading(true)
    try {
      const [r1, r2] = await Promise.all([
        axios.get('/api/basis/latest'),
        axios.get('/api/basis/stats?days=7'),
      ])
      const data = r1.data || []
      setLatest(data)
      setStats(r2.data || [])
      if (data.length > 0 && !selectedSymbol) {
        setSelectedSymbol(data[0].contract_symbol)
      }
      setUpdated(new Date().toLocaleTimeString())
    } catch (e) {}
    setLoading(false)
  }
  useEffect(() => { fetchAll() }, [])

  // 拉历史曲线
  useEffect(() => {
    if (!selectedSymbol) return
    setLoadingHistory(true)
    axios.get(`/api/basis/history?symbol=${selectedSymbol}&hours=${historyHours}`)
      .then(res => setHistory(res.data || []))
      .finally(() => setLoadingHistory(false))
  }, [selectedSymbol, historyHours])

  const statsMap = useMemo(() => {
    const m = {}
    for (const s of stats) m[s.contract_symbol] = s
    return m
  }, [stats])

  return (
    <div>
      {/* 顶部刷新栏 */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 10,
        background: '#f0f2f5', padding: '8px 0', marginBottom: 8,
        display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 12,
      }}>
        <span style={{ color: '#666', fontSize: 13 }}>
          {updated ? `更新于 ${updated}` : '未刷新'}
        </span>
        <Button type="primary" size="large" icon={<ReloadOutlined />}
          loading={loading} onClick={fetchAll}>
          刷新
        </Button>
      </div>

      {/* 4 张卡：每个合约的最新快照 */}
      <Spin spinning={loading}>
        {latest.length === 0 ? (
          <Empty description="basis_snapshot 表暂无数据（服务可能刚启动）" style={{ padding: 60 }} />
        ) : (
          <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
            {latest.map(r => {
              const stat = statsMap[r.contract_symbol]
              const color = r.pair === 'BTCUSDT' ? 'gold' : 'blue'
              return (
                <Col xs={24} sm={12} md={12} lg={6} key={r.contract_symbol}>
                  <Card
                    size="small"
                    title={
                      <span>
                        <Tag color={color}>{r.pair}</Tag>
                        <Tag>{contractTypeLabel(r.contract_type)}</Tag>
                        <span style={{ color: '#999', fontSize: 12, marginLeft: 4 }}>
                          剩 {r.days_to_expiry?.toFixed(1)}d → {r.expiry_date}
                        </span>
                      </span>
                    }
                    hoverable
                    onClick={() => setSelectedSymbol(r.contract_symbol)}
                    style={selectedSymbol === r.contract_symbol ? {
                      borderColor: '#1677ff', boxShadow: '0 0 0 2px rgba(22,119,255,0.2)'
                    } : {}}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: 12, color: '#666' }}>
                      <span>现货 <b style={{ color: '#000' }}>{r.spot_price?.toFixed(2)}</b></span>
                      <span>合约 <b style={{ color: '#000' }}>{r.futures_price?.toFixed(2)}</b></span>
                    </div>
                    <Statistic
                      title={<span style={{ fontSize: 12 }}>年化基差</span>}
                      value={Math.abs(r.annualized_pct)}
                      precision={2}
                      suffix="%"
                      valueStyle={{ color: pnlColor(r.annualized_pct), fontSize: 28 }}
                      prefix={(r.annualized_pct ?? 0) >= 0 ? '+' : '-'}
                    />
                    <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
                      绝对基差 <span style={{ color: pnlColor(r.basis), fontWeight: 500 }}>
                        {(r.basis ?? 0) >= 0 ? '+' : ''}{r.basis?.toFixed(2)}
                      </span>
                      （{pct(r.basis_pct, 3)}）
                    </div>
                    {stat && (
                      <div style={{ marginTop: 8, fontSize: 11, color: '#999', borderTop: '1px dashed #eee', paddingTop: 6 }}>
                        7 天均 {pct(stat.avg_annual, 2)} · 区间 {parseFloat(stat.min_annual).toFixed(2)}% ~ {parseFloat(stat.max_annual).toFixed(2)}%
                      </div>
                    )}
                  </Card>
                </Col>
              )
            })}
          </Row>
        )}
      </Spin>

      {/* 历史曲线 */}
      {selectedSymbol && (
        <Card
          size="small"
          title={
            <span>
              <LineChartOutlined /> 年化基差曲线
              <Tag color="blue" style={{ marginLeft: 8 }}>{selectedSymbol}</Tag>
            </span>
          }
          extra={
            <Select
              size="small"
              value={historyHours}
              onChange={setHistoryHours}
              options={[
                { label: '6 小时', value: 6 },
                { label: '24 小时', value: 24 },
                { label: '3 天', value: 72 },
                { label: '7 天', value: 168 },
                { label: '30 天', value: 720 },
              ]}
            />
          }
          style={{ marginBottom: 16 }}
        >
          <Spin spinning={loadingHistory}>
            <MiniLineChart data={history} valueKey="annualized_pct" yLabel="%" />
          </Spin>
        </Card>
      )}

      {/* 历史明细表 */}
      {selectedSymbol && history.length > 0 && (
        <Card size="small" title={<span>历史明细 ({history.length} 条)</span>}>
          <Table
            columns={historyColumns}
            dataSource={history.slice().reverse().map((r, i) => ({ ...r, key: i }))}
            pagination={{ pageSize: 30, showSizeChanger: true, pageSizeOptions: [20, 30, 50, 100] }}
            scroll={{ x: 'max-content' }}
            size="small"
          />
        </Card>
      )}
    </div>
  )
}
