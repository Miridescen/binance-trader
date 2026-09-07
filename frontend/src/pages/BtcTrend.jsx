import { useEffect, useState } from 'react'
import { Table, Spin, Button } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import axios from 'axios'
import { PnlCell, Num, Chip, Panel, PageHeader, Stat } from '../components/ui'
import { pnlColor, pnlTone, fmtSigned } from '../lib/fmt'

// 方向色：多 红 / 空 绿 / 观望 灰（沿用原页面约定）
const signalTone = { '多': 'red', '空': 'green', '观望': 'grey' }
const SignalChip = ({ v }) => <Chip tone={signalTone[v] || 'grey'}>{v}</Chip>

const indicatorColumns = [
  { title: '时间', dataIndex: 'time', key: 'time', width: 120,
    render: v => <span className="num" style={{ fontWeight: 500 }}>{v?.slice(5, 16)}</span> },
  { title: 'BTC价格', dataIndex: 'price', key: 'price', width: 100, align: 'right', render: v => <Num value={v} /> },
  { title: 'SMA200', dataIndex: 'sma200', key: 'sma200', width: 100, align: 'right', render: v => <Num value={v} /> },
  {
    title: '价格/SMA', key: 'price_vs_sma', width: 90,
    render: (_, r) => {
      if (!r.price || !r.sma200) return '-'
      const above = parseFloat(r.price) > parseFloat(r.sma200)
      return <Chip tone={above ? 'red' : 'green'}>{above ? '上方' : '下方'}</Chip>
    },
  },
  {
    title: 'EMA交叉', key: 'ema_cross', width: 90,
    render: (_, r) => {
      if (!r.ema50 || !r.ema200) return '-'
      const golden = parseFloat(r.ema50) > parseFloat(r.ema200)
      return <Chip tone={golden ? 'red' : 'green'}>{golden ? '金叉' : '死叉'}</Chip>
    },
  },
  { title: 'RSI周', dataIndex: 'rsi_weekly', key: 'rsi_weekly', width: 70, align: 'right', render: v => <Num value={v} digits={1} /> },
  {
    title: 'MACD柱', dataIndex: 'macd_histogram', key: 'macd_histogram', width: 90, align: 'right',
    render: v => v == null ? '-' : <PnlCell value={v} />,
  },
  {
    title: '资金费率', dataIndex: 'funding_rate', key: 'funding_rate', width: 90, align: 'right',
    render: v => {
      if (v == null) return '-'
      const n = parseFloat(v)
      return <span className="num" style={{ color: pnlColor(n) }}>{(n * 100).toFixed(4)}%</span>
    },
  },
  {
    title: '恐惧贪婪', key: 'fng', width: 90, align: 'right',
    render: (_, r) => {
      const v = r.fear_greed
      if (v == null) return '-'
      const color = v <= 25 ? '#b91c1c' : v <= 45 ? '#c2410c' : v <= 55 ? '#94a3b8' : v <= 75 ? '#16a34a' : '#15803d'
      return <span className="num" style={{ color, fontWeight: 600 }}>{v}</span>
    },
  },
  { title: '信号', dataIndex: 'signal', key: 'signal', width: 70, render: v => <SignalChip v={v} /> },
]

const signalColumns = [
  { title: '开仓时间', dataIndex: 'open_time', key: 'open_time', width: 120,
    render: v => <span className="num" style={{ fontWeight: 500 }}>{v?.slice(5, 16)}</span> },
  { title: '平仓时间', dataIndex: 'close_time', key: 'close_time', width: 120,
    render: v => v ? <span className="num muted">{v.slice(5, 16)}</span> : <Chip tone="blue">持仓中</Chip> },
  { title: '方向', dataIndex: 'side', key: 'side', width: 64, render: v => <SignalChip v={v} /> },
  { title: '入场价', dataIndex: 'entry_price', key: 'entry_price', width: 100, align: 'right', render: v => <Num value={v} /> },
  { title: '平仓价', dataIndex: 'close_price', key: 'close_price', width: 100, align: 'right', render: v => <Num value={v} /> },
  { title: '信号原因', dataIndex: 'signal_reason', key: 'signal_reason', width: 220,
    render: v => <span className="muted">{v}</span> },
  {
    title: '盈亏', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 100, align: 'right',
    render: v => v == null ? '-' : <PnlCell value={v} suffix=" U" />,
    sorter: (a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0),
  },
  {
    title: 'ROE', dataIndex: 'roe_pct', key: 'roe_pct', width: 80, align: 'right',
    render: v => v == null ? '-' : <PnlCell value={v} digits={1} suffix="%" />,
  },
]

export default function BtcTrend() {
  const [loading, setLoading] = useState(true)
  const [indicators, setIndicators] = useState([])
  const [signals, setSignals] = useState([])

  const fetchAll = () => {
    setLoading(true)
    Promise.all([
      axios.get('/api/btc_indicators'),
      axios.get('/api/btc_signals'),
    ]).then(([r1, r2]) => {
      setIndicators(r1.data.map((r, i) => ({ ...r, key: i })))
      setSignals(r2.data.map((r, i) => ({ ...r, key: i })))
    }).finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchAll()
    const t = setInterval(fetchAll, 60_000)
    return () => clearInterval(t)
  }, [])

  const latest = indicators[0] || {}
  const openPosition = signals.find(r => !r.close_time)
  const closedSignals = signals.filter(r => r.close_time)
  const totalPnl = closedSignals.reduce((acc, r) => acc + (r.unrealized_pnl || 0), 0)
  const wins = closedSignals.filter(r => (r.unrealized_pnl || 0) > 0).length

  const rsi = parseFloat(latest.rsi_weekly)
  const golden = latest.ema50 && latest.ema200 ? parseFloat(latest.ema50) > parseFloat(latest.ema200) : null
  const macd = latest.macd_histogram != null ? parseFloat(latest.macd_histogram) : null
  const sigTone = latest.signal === '多' ? 'down' : latest.signal === '空' ? 'up' : 'flat' // 多 红 / 空 绿

  return (
    <Spin spinning={loading}>
      <div className="panel-stack">
        <PageHeader
          title="BTC 趋势"
          subtitle="SMA200 / EMA 交叉 / 周线 RSI / MACD / 资金费率 / 恐惧贪婪，每分钟自动刷新"
          extra={<Button icon={<ReloadOutlined />} onClick={fetchAll}>刷新</Button>}
        />

        {/* 当前状态 */}
        <div className="stat-grid stat-grid-4">
          <Stat card label="BTC 价格" unit="U" value={latest.price ? <Num value={latest.price} /> : '-'} />
          <Stat card label="当前信号" tone={sigTone} value={latest.signal || '-'} />
          <Stat card label="RSI 周线" tone={isNaN(rsi) ? undefined : rsi > 50 ? 'down' : 'up'}
            value={isNaN(rsi) ? '-' : rsi.toFixed(1)} />
          <Stat card label="EMA 交叉" tone={golden == null ? undefined : golden ? 'down' : 'up'}
            value={golden == null ? '-' : golden ? '金叉' : '死叉'} />
          <Stat card label="MACD 柱" tone={macd == null ? undefined : pnlTone(macd)}
            value={macd == null ? '-' : fmtSigned(macd)} />
          <Stat card label="恐惧贪婪" value={latest.fear_greed ?? '-'} unit={latest.fear_greed_label || ''} />
          <Stat card label="累计盈亏" unit="U" tone={pnlTone(totalPnl)} value={fmtSigned(totalPnl)} />
          <Stat card label="胜率" value={closedSignals.length ? `${wins}/${closedSignals.length}` : '-'}
            hint={closedSignals.length ? `${((wins / closedSignals.length) * 100).toFixed(0)}%` : undefined} />
        </div>

        {openPosition && (
          <Panel title={<>当前持仓<SignalChip v={openPosition.side} /></>}>
            <div className="kv-row">
              <div className="kv"><span className="kv-k">入场价</span><span className="kv-v num"><Num value={openPosition.entry_price} /></span></div>
              <div className="kv"><span className="kv-k">开仓时间</span><span className="kv-v num">{openPosition.open_time?.slice(5, 16)}</span></div>
            </div>
          </Panel>
        )}

        {/* 交易记录 */}
        <Panel flush title="信号交易记录" subtitle={`${signals.length} 条`}>
          <Table columns={signalColumns} dataSource={signals}
            pagination={false} scroll={{ x: 'max-content' }} size="small"
            rowClassName={r => !r.close_time ? 'row-open' : (r.unrealized_pnl || 0) > 0 ? 'row-profit' : 'row-loss'} />
        </Panel>

        {/* 指标历史 */}
        <Panel flush title="指标历史" subtitle={`${indicators.length} 条`}>
          <Table columns={indicatorColumns} dataSource={indicators}
            pagination={{ pageSize: 50, size: 'small' }} scroll={{ x: 'max-content' }} size="small" />
        </Panel>
      </div>
    </Spin>
  )
}
