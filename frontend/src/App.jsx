import { useState, useEffect } from 'react'
import { Input, Button, ConfigProvider } from 'antd'
import { Routes, Route, NavLink, useSearchParams } from 'react-router-dom'
import { DashboardOutlined, FundOutlined, UnorderedListOutlined, LineChartOutlined, LockOutlined } from '@ant-design/icons'
import Dashboard from './pages/Dashboard'
import OpenLog from './pages/OpenLog'
import PositionsDetail from './pages/PositionsDetail'
import DailySummary from './pages/DailySummary'
import BtcTrend from './pages/BtcTrend'
import VirtualLogWindow from './pages/VirtualLog4h'
import BinanceLogo from './components/BinanceLogo'
import { THEME } from './theme'
import 'antd/dist/reset.css'
import './App.css'

const ACCESS_PASSWORD = 'mu824810056'

const menuItems = [
  { key: '/',                  icon: <DashboardOutlined />,      label: 'Dashboard' },
  { key: '/openlog',           icon: <UnorderedListOutlined />,  label: '开仓记录' },
  { key: '/virtuallog-4h',     icon: <LineChartOutlined />,      label: '4h模拟盘' },
  { key: '/virtuallog-8h',     icon: <LineChartOutlined />,      label: '8h模拟盘' },
  { key: '/virtuallog-12h',    icon: <LineChartOutlined />,      label: '12h模拟盘' },
  { key: '/virtuallog-24h',    icon: <LineChartOutlined />,      label: '24h模拟盘' },
  { key: '/btc-trend',         icon: <FundOutlined />,           label: 'BTC趋势' },
]

function LoginPage({ onLogin }) {
  const [pwd, setPwd] = useState('')
  const [error, setError] = useState(false)

  const handleLogin = () => {
    if (pwd === ACCESS_PASSWORD) {
      localStorage.setItem('auth', '1')
      onLogin()
    } else {
      setError(true)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <span className="brand-mark"><BinanceLogo size={22} /></span>
          <div>
            <h1>Binance Trader</h1>
            <p>合约均值回归 · 实盘看板</p>
          </div>
        </div>
        <Input.Password
          size="large"
          prefix={<LockOutlined style={{ color: '#94a3b8' }} />}
          placeholder="请输入访问密码"
          value={pwd}
          onChange={e => { setPwd(e.target.value); setError(false) }}
          onPressEnter={handleLogin}
          status={error ? 'error' : ''}
        />
        {error && <div className="login-error">密码错误</div>}
        <Button type="primary" size="large" block style={{ marginTop: 16 }} onClick={handleLogin}>进入</Button>
      </div>
    </div>
  )
}

export default function App() {
  const [searchParams] = useSearchParams()
  const [authed, setAuthed] = useState(false)

  useEffect(() => {
    // URL 参数 ?pwd=xxx 自动登录
    const urlPwd = searchParams.get('pwd')
    if (urlPwd === ACCESS_PASSWORD) {
      localStorage.setItem('auth', '1')
      setAuthed(true)
      return
    }
    // localStorage 已登录
    if (localStorage.getItem('auth') === '1') {
      setAuthed(true)
    }
  }, [searchParams])

  if (!authed) {
    return (
      <ConfigProvider theme={THEME}>
        <LoginPage onLogin={() => setAuthed(true)} />
      </ConfigProvider>
    )
  }

  return (
    <ConfigProvider theme={THEME}>
      <header className="app-header">
        <NavLink to="/" className="brand">
          <span className="brand-mark"><BinanceLogo size={18} /></span>
          <span>Binance Trader</span>
        </NavLink>
        <nav className="nav">
          {menuItems.map(m => (
            <NavLink key={m.key} to={m.key} end={m.key === '/'}>
              {m.icon}{m.label}
            </NavLink>
          ))}
        </nav>
        <div className="header-right"><span className="live-dot" />USDT-M 合约</div>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/"           element={<Dashboard />} />
          <Route path="/openlog"    element={<OpenLog />} />
          <Route path="/daily-summary"     element={<DailySummary />} />
          <Route path="/virtuallog-4h"     element={<VirtualLogWindow window="4h" />} />
          <Route path="/virtuallog-8h"     element={<VirtualLogWindow window="8h" />} />
          <Route path="/virtuallog-12h"    element={<VirtualLogWindow window="12h" />} />
          <Route path="/virtuallog-24h"    element={<VirtualLogWindow window="24h" />} />
          <Route path="/positions-detail" element={<PositionsDetail />} />
          <Route path="/btc-trend"       element={<BtcTrend />} />
        </Routes>
      </main>
    </ConfigProvider>
  )
}
