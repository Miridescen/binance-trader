// 全站共用的展示组件（只管样式，不含业务逻辑）；数字/颜色工具在 ../lib/fmt.js
import { pnlTone, fmtSigned, sideTone } from '../lib/fmt'

/** 带正负号与涨跌色的盈亏数字 */
export function PnlCell({ value, digits = 2, suffix = '', className = '', style }) {
  const n = parseFloat(value)
  if (isNaN(n)) return <span className="pnl flat">-</span>
  return (
    <span className={`pnl ${pnlTone(n)} ${className}`} style={style}>
      {fmtSigned(n, digits)}{suffix}
    </span>
  )
}

/** 普通等宽数字 */
export function Num({ value, digits = 2, fallback = '-' }) {
  const n = parseFloat(value)
  if (value == null || value === '' || isNaN(n)) return <span className="muted">{fallback}</span>
  return <span className="num">{n.toFixed(digits)}</span>
}

/** 小色块标签：tone = cyan | green | red | orange | blue | purple | gold | grey */
export function Chip({ tone = 'grey', children, className = '', style }) {
  return <span className={`chip chip-${tone} ${className}`} style={style}>{children}</span>
}

export function SideChip({ side }) {
  return <Chip tone={sideTone(side)}>{side}</Chip>
}

/** 页面标题行 */
export function PageHeader({ title, subtitle, extra }) {
  return (
    <div className="page-head">
      <div>
        <div className="page-title">{title}</div>
        {subtitle && <div className="page-sub">{subtitle}</div>}
      </div>
      {extra && <div className="page-extra">{extra}</div>}
    </div>
  )
}

/** 面板：白底圆角容器，带可选标题栏；flush 时内容贴边（放表格） */
export function Panel({ title, subtitle, extra, children, flush = false, className = '', style, bodyStyle }) {
  const hasHead = title || subtitle || extra
  return (
    <section className={`panel ${className}`} style={style}>
      {hasHead && (
        <header className="panel-head">
          {(title || subtitle) && (
            <div className="panel-title">
              {title}
              {subtitle && <span className="panel-sub">{subtitle}</span>}
            </div>
          )}
          {extra && <div className="panel-extra">{extra}</div>}
        </header>
      )}
      <div className={`panel-body ${flush ? 'flush' : ''}`} style={bodyStyle}>{children}</div>
    </section>
  )
}

/** 指标块：label 在上，大数字在下 */
export function Stat({ label, value, unit, hint, tone, icon, size = 'md', card = false }) {
  const toneClass = tone ? ` tone-${tone}` : ''
  const body = (
    <div className={`stat stat-${size}`}>
      <div className="stat-label">{icon}{label}</div>
      <div className={`stat-value${toneClass}`}>
        {value}
        {unit && <span className="stat-unit">{unit}</span>}
      </div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
  return card ? <div className="stat-card">{body}</div> : body
}
