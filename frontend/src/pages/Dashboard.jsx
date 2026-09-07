import { useEffect, useMemo, useState } from 'react'
import { Row, Col, Table, Spin, Button, Select, Switch, message, Modal } from 'antd'
import { ReloadOutlined, WalletOutlined, DollarOutlined, FireOutlined } from '@ant-design/icons'
import axios from 'axios'
import { PnlCell, Num, Chip, Panel, PageHeader, Stat } from '../components/ui'
import { pnlColor, pnlTone, fmtSigned } from '../lib/fmt'

// ── 按周期分组的列（实盘 batch）──
const batchColumns = [
  {
    title: '开仓时间',
    dataIndex: 'open_time_short',
    key: 'open_time',
    width: 110,
    sorter: (a, b) => (a.open_time_key || '').localeCompare(b.open_time_key || ''),
    defaultSortOrder: 'descend',
    render: v => <span className="num" style={{ fontWeight: 500 }}>{v}</span>,
  },
  {
    title: '平仓',
    dataIndex: 'close_time_short',
    key: 'close_time',
    width: 104,
    render: v => v ? <span className="num muted" style={{ whiteSpace: 'nowrap' }}>{v}</span> : <Chip tone="blue">持仓中</Chip>,
  },
  { title: '笔', dataIndex: 'n', key: 'n', width: 44, align: 'right' },
  {
    title: '毛PnL',
    dataIndex: 'gross_pnl',
    key: 'gross_pnl',
    width: 84, align: 'right',
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => (a.gross_pnl || 0) - (b.gross_pnl || 0),
  },
  {
    title: '手续费',
    dataIndex: 'commission',
    key: 'commission',
    width: 80, align: 'right',
    render: v => <PnlCell value={v} digits={3} />,
  },
  {
    title: '资金费',
    dataIndex: 'funding',
    key: 'funding',
    width: 78, align: 'right',
    render: v => <PnlCell value={v} digits={3} />,
  },
  {
    title: '净PnL',
    dataIndex: 'net_pnl',
    key: 'net_pnl',
    width: 84, align: 'right',
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => (a.net_pnl || 0) - (b.net_pnl || 0),
  },
]

// ── 实时持仓表的列 ──
const positionColumns = [
  { title: '币种', dataIndex: 'symbol', key: 'symbol', width: 110,
    render: v => <span style={{ fontWeight: 600 }}>{v}</span> },
  { title: '入场价', dataIndex: 'entry_price', key: 'entry_price', width: 92, align: 'right',
    render: v => <Num value={v} digits={4} /> },
  { title: '标记价', dataIndex: 'mark_price', key: 'mark_price', width: 92, align: 'right',
    render: v => <Num value={v} digits={4} /> },
  { title: '数量', dataIndex: 'position_amt', key: 'position_amt', width: 80, align: 'right',
    render: v => <span className="num">{v}</span> },
  {
    title: '盈亏', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 80, align: 'right',
    render: v => <PnlCell value={v} />,
    sorter: (a, b) => (a.unrealized_pnl || 0) - (b.unrealized_pnl || 0),
  },
  {
    title: 'ROE', dataIndex: 'roe_pct', key: 'roe_pct', width: 78, align: 'right',
    render: v => v == null ? '-' : <PnlCell value={v} suffix="%" />,
  },
]

// 按 (open_anchor, side) 分组聚合成 batch（open_anchor 是周期 :30 整点，稳定）
function groupBatches(rows, sideFilter) {
  const filtered = rows.filter(r => r.side === sideFilter)
  const map = new Map()
  for (const r of filtered) {
    const k = (r.open_anchor || r.open_time || '').slice(0, 16)
    if (!map.has(k)) map.set(k, [])
    map.get(k).push(r)
  }
  const batches = []
  for (const [open_time_key, items] of map) {
    const closedItems = items.filter(r => r.close_time)
    const gross = items.reduce((a, r) => a + (parseFloat(r.unrealized_pnl) || 0), 0)
    const comm = items.reduce((a, r) =>
      a + (parseFloat(r.open_commission) || 0) + (parseFloat(r.close_commission) || 0), 0)
    const fund = items.reduce((a, r) => a + (parseFloat(r.funding_fee) || 0), 0)
    const net = gross + comm + fund
    const closeTimes = items.map(r => r.close_time).filter(Boolean)
    const closeTime = closeTimes.length ? closeTimes.sort().slice(-1)[0] : null
    batches.push({
      key: open_time_key,
      open_time_key,
      open_time_short: open_time_key.slice(5),
      close_time_short: closeTime ? closeTime.slice(5, 16) : null,
      all_closed: closedItems.length === items.length,
      n: items.length,
      gross_pnl: gross,
      commission: comm,
      funding: fund,
      net_pnl: net,
    })
  }
  return batches
}

const sumPnl = arr => arr.reduce((a, p) => a + (parseFloat(p.unrealized_pnl) || 0), 0)

// ── 开关胶囊：自动开单 / 组内止损 ──
function SwitchChip({ label, checked, disabled, onChange, alert }) {
  return (
    <span className={`switch-chip ${alert ? 'alert' : ''}`}>
      {label}
      <Switch size="small" checked={checked} disabled={disabled} onChange={onChange} />
    </span>
  )
}

// ── 账户头卡：名称 + 策略说明 + 开关 + 余额/保证金/浮盈 ──
function AccountHeader({ tag, tagTone, name, note, rt, switches, switchesLoaded, toggleSwitch, switchKey, slKey, slLabel }) {
  const configured = rt?.configured !== false
  const hasError = configured && rt?.error
  const positions = rt?.positions || []
  const losers = positions.filter(p => p.side?.includes('跌幅'))
  const floating = sumPnl(losers)

  return (
    <Panel
      flush
      title={<><Chip tone={tagTone}>{tag}</Chip>{name}</>}
      subtitle={note}
      extra={
        <>
          <SwitchChip label="自动开单" checked={switches[switchKey] !== false} disabled={!switchesLoaded}
            alert={switches[switchKey] === false} onChange={v => toggleSwitch(switchKey, v, 'open')} />
          <SwitchChip label={slLabel} checked={switches[slKey] === true} disabled={!switchesLoaded}
            alert={switches[slKey] === true} onChange={v => toggleSwitch(slKey, v, 'sl')} />
        </>
      }
    >
      {!configured ? (
        <div className="muted" style={{ padding: 16 }}>未配置密钥（.env.sub24h）</div>
      ) : hasError ? (
        <div style={{ padding: 16, color: pnlColor(-1) }}>查询失败：{String(rt.error).slice(0, 60)}</div>
      ) : (
        <div className="stat-strip">
          <Stat icon={<WalletOutlined />} label="账户余额" unit="U"
            value={<Num value={rt?.balance ?? 0} digits={2} />} />
          <Stat icon={<DollarOutlined />} label="保证金占用" unit="U" tone={rt?.margin_used > 0 ? 'brand' : undefined}
            value={<Num value={rt?.margin_used ?? 0} digits={2} />} />
          <Stat icon={<FireOutlined />} label="持仓浮盈" unit="U" tone={losers.length ? pnlTone(floating) : 'flat'}
            value={losers.length ? fmtSigned(floating) : '—'}
            hint={`${losers.length} 笔持仓中`} />
        </div>
      )}
    </Panel>
  )
}

// ── 实时持仓（跌幅榜-空）+ 一键平仓 ──
function PositionsBlock({ rt, strategyKey, accountLabel }) {
  const positions = (rt?.positions || []).map((p, i) => ({ ...p, key: i }))
  const losers = positions.filter(p => p.side?.includes('跌幅'))
  const others = positions.filter(p => !p.side?.includes('跌幅') && !p.side?.includes('涨幅'))

  const doForceClose = () => {
    Modal.confirm({
      title: '一键平仓确认',
      okText: '确认市价平仓',
      okType: 'danger',
      cancelText: '取消',
      content: `将立即市价平掉「${accountLabel}」当前 ${losers.length} 个持仓（跌幅榜-空）。此操作不可撤销，平仓原因记为「一键平仓」。确认？`,
      onOk: () => axios.post('/api/force_close', { key: strategyKey })
        .then(() => message.success('已发出平仓指令，约 30 秒内执行；稍后点“刷新全部”查看'))
        .catch(() => message.error('下达失败，请重试')),
    })
  }

  return (
    <Panel
      flush
      title="实时持仓"
      subtitle={`${positions.length} 笔`}
      extra={
        <Button size="small" danger disabled={losers.length === 0} onClick={doForceClose}>
          一键平仓
        </Button>
      }
    >
      <div className="sub-head">
        <Chip tone="cyan">跌幅榜-空</Chip>
        <span>{losers.length} 笔</span>
        <span className="kv-inline">浮盈 <PnlCell value={sumPnl(losers)} /></span>
      </div>
      <Table
        columns={positionColumns}
        dataSource={losers}
        pagination={false}
        scroll={{ x: 'max-content' }}
        size="small"
        rowClassName={r => (r.unrealized_pnl > 0 ? 'row-profit' : r.unrealized_pnl < 0 ? 'row-loss' : '')}
        locale={{ emptyText: '无持仓' }}
      />
      {others.length > 0 && (
        <>
          <div className="sub-head"><Chip tone="grey">其他</Chip><span>{others.length} 笔</span></div>
          <Table columns={positionColumns} dataSource={others} pagination={false}
            scroll={{ x: 'max-content' }} size="small" />
        </>
      )}
    </Panel>
  )
}

// ── 按周期分组表 ──
function BatchBlock({ batches, netPnl, loading, extra }) {
  return (
    <Panel
      flush
      title="周期记录"
      subtitle={`${batches.length} 周期`}
      extra={
        <>
          <span className="kv-inline">累计净 <PnlCell value={netPnl} /></span>
          {extra}
        </>
      }
    >
      <Spin spinning={loading}>
        <div className="sub-head"><Chip tone="cyan">跌幅榜-空</Chip><span>无过滤 · 净 = 毛 + 手续费 + 资金费</span></div>
        <Table
          columns={batchColumns}
          dataSource={batches}
          pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 30, 50], size: 'small' }}
          scroll={{ x: 'max-content' }}
          size="small"
          rowClassName={r => (r.net_pnl > 0 ? 'row-profit' : r.net_pnl < 0 ? 'row-loss' : '')}
          locale={{ emptyText: '暂无记录' }}
        />
      </Spin>
    </Panel>
  )
}

export default function Dashboard() {
  const [rt, setRt] = useState(null)        // 主账号 8h
  const [rt24, setRt24] = useState(null)     // 子账号 24h
  const [logs, setLogs] = useState([])       // 8h open_log
  const [logs24, setLogs24] = useState([])   // 24h open_log
  const [loadingRt, setLoadingRt] = useState(false)
  const [loadingLog, setLoadingLog] = useState(true)
  const [updatedRt, setUpdatedRt] = useState(null)
  const [timeFilter, setTimeFilter] = useState('all') // 8h 按时段筛选
  // 开关：real_* 自动开单（默认开）；stoploss_* 组内止损（默认关）。真值以 /api/switches 为准
  const [switches, setSwitches] = useState({ real_8h: true, real_24h: true, stoploss_8h: false, stoploss_24h: false })
  const [switchesLoaded, setSwitchesLoaded] = useState(false) // 首次成功拉到 /api/switches 前，开关灰掉，不把挂载默认值当真相展示

  const fetchAll = async () => {
    setLoadingRt(true)
    setLoadingLog(true)
    // 各请求独立结算：任一接口失败（如 /api/realtime 因币安抖动返回 500）不影响其余；
    // 开关状态尤其必须独立刷新——它是“止损/自动开单是否已武装”的唯一显示依据
    const [r1, r2, r3, r4, r5] = await Promise.allSettled([
      axios.get('/api/realtime'),
      axios.get('/api/open_log_8h'),
      axios.get('/api/realtime_24h'),
      axios.get('/api/open_log_24h'),
      axios.get('/api/switches'),
    ])
    const ok = r => r.status === 'fulfilled' && r.value?.data && !r.value.data.error
    if (ok(r1)) setRt(r1.value.data)
    if (r2.status === 'fulfilled') setLogs(r2.value.data || [])
    if (r3.status === 'fulfilled') setRt24(r3.value.data || null)
    if (r4.status === 'fulfilled') setLogs24(r4.value.data || [])
    if (ok(r5)) { setSwitches(s => ({ ...s, ...r5.value.data })); setSwitchesLoaded(true) } // 合并而非整体替换，避免覆盖刚点的乐观状态
    setUpdatedRt(new Date().toLocaleTimeString())
    setLoadingRt(false)
    setLoadingLog(false)
  }
  useEffect(() => { fetchAll() }, [])

  // 切换开关（乐观更新，失败回滚）。kind: 'open' 自动开单 | 'sl' 组内止损
  const toggleSwitch = async (key, val, kind = 'open') => {
    setSwitches(s => ({ ...s, [key]: val }))
    try {
      await axios.post('/api/switch', { key, enabled: val })
      if (kind === 'sl') {
        if (val) message.warning('已开启组内止损：合计浮亏触及阈值时自动整组市价平仓（约 30 秒内生效）')
        else message.info('已关闭组内止损')
      } else {
        if (val) message.success('已开启自动开单：下个周期恢复开仓')
        else message.info('已关闭自动开单：下个周期不再开新仓（已有持仓的监控/平仓照常）')
      }
    } catch (e) {
      setSwitches(s => ({ ...s, [key]: !val }))
      message.error('切换失败，请重试')
    }
  }

  // 8h：按周期分组 + 时段筛选
  const allLoserBatches8 = useMemo(() => groupBatches(logs, '跌幅榜-空（无过滤）'), [logs])
  const timeOptions = useMemo(() => {
    const set = new Set()
    for (const b of allLoserBatches8) set.add(b.open_time_key.slice(11, 16))
    return [...set].sort()
  }, [allLoserBatches8])
  const matchTime = b => timeFilter === 'all' || b.open_time_key.slice(11, 16) === timeFilter
  const loserBatches8 = allLoserBatches8.filter(matchTime)
  const net8 = loserBatches8.reduce((a, b) => a + b.net_pnl, 0)

  // 24h：单窗口 00:30，无需时段筛选
  const loserBatches24 = useMemo(() => groupBatches(logs24, '跌幅榜-空（无过滤）'), [logs24])
  const net24 = loserBatches24.reduce((a, b) => a + b.net_pnl, 0)

  const switchProps = { switches, switchesLoaded, toggleSwitch }

  return (
    <div>
      <PageHeader
        title="实盘看板"
        subtitle="子账号1 · 8h  /  子账号2 · 24h · 跌幅榜-空（无过滤）"
        extra={
          <>
            <span className="page-meta">{updatedRt ? `更新于 ${updatedRt}` : '未刷新'}</span>
            <Button type="primary" icon={<ReloadOutlined />}
              loading={loadingRt || loadingLog} onClick={fetchAll}>
              刷新全部
            </Button>
          </>
        }
      />

      {/* ── 8h（子账号1）与 24h（子账号2）左右并排；窄屏自动上下堆叠 ── */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <div className="panel-stack">
            <AccountHeader tag="子账号1" tagTone="blue" name="8h 实盘" rt={rt}
              note="组内 +16U 提前平，否则跑满 8h"
              switchKey="real_8h" slKey="stoploss_8h" slLabel="止损 −30U" {...switchProps} />
            <PositionsBlock rt={rt} strategyKey="real_8h" accountLabel="子账号1 · 8h" />
            <BatchBlock batches={loserBatches8} netPnl={net8} loading={loadingLog}
              extra={
                <Select size="small" style={{ minWidth: 120 }} value={timeFilter} onChange={setTimeFilter}
                  options={[{ label: '全部时段', value: 'all' }, ...timeOptions.map(t => ({ label: `${t} 周期`, value: t }))]} />
              } />
          </div>
        </Col>
        <Col xs={24} lg={12}>
          <div className="panel-stack">
            <AccountHeader tag="子账号2" tagTone="purple" name="24h 实盘" rt={rt24}
              note="组内 +50U 提前平，否则跑满 24h（5x）"
              switchKey="real_24h" slKey="stoploss_24h" slLabel="止损 −150U" {...switchProps} />
            <PositionsBlock rt={rt24} strategyKey="real_24h" accountLabel="子账号2 · 24h" />
            <BatchBlock batches={loserBatches24} netPnl={net24} loading={loadingLog} />
          </div>
        </Col>
      </Row>
    </div>
  )
}
