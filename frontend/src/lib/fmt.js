// 盈亏颜色 / 正负号格式化 / 方向→色调（纯函数，无 React）
export const UP = '#15803d'
export const DOWN = '#b91c1c'
export const FLAT = '#94a3b8'

export function pnlColor(v) {
  const n = parseFloat(v)
  if (n > 0) return UP
  if (n < 0) return DOWN
  return FLAT
}

export function pnlTone(v) {
  const n = parseFloat(v)
  if (n > 0) return 'up'
  if (n < 0) return 'down'
  return 'flat'
}

export const fmtSigned = (v, digits = 2) => {
  const n = parseFloat(v)
  if (isNaN(n)) return '-'
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}`
}

/** 方向字符串 → 标签色（涨幅-空 绿 / 跌幅-空 青 / 涨幅-多 红 / 跌幅-多 橙） */
export function sideTone(side) {
  if (!side) return 'grey'
  if (side.includes('涨幅') && side.includes('空')) return 'green'
  if (side.includes('跌幅') && side.includes('空')) return 'cyan'
  if (side.includes('涨幅') && side.includes('多')) return 'red'
  if (side.includes('跌幅') && side.includes('多')) return 'orange'
  return 'grey'
}
