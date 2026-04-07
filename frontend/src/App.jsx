import { useState, useEffect } from 'react'
import { Layout, Menu, Input, Button, Card } from 'antd'
import { Routes, Route, useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import { DashboardOutlined, FundOutlined, UnorderedListOutlined, ExperimentOutlined, BarChartOutlined, LineChartOutlined, LockOutlined } from '@ant-design/icons'
import Dashboard from './pages/Dashboard'
import Positions from './pages/Positions'
import OpenLog from './pages/OpenLog'
import VirtualLog from './pages/VirtualLog'
import VirtualDetail from './pages/VirtualDetail'
import PositionsDetail from './pages/PositionsDetail'
import DailySummary from './pages/DailySummary'
import 'antd/dist/reset.css'
import './App.css'

const { Header, Content } = Layout

const ACCESS_PASSWORD = 'mu824810056'

const menuItems = [
  { key: '/',                  icon: <DashboardOutlined />,      label: 'Dashboard' },
  { key: '/positions',         icon: <FundOutlined />,           label: '持仓监控' },
  { key: '/openlog',           icon: <UnorderedListOutlined />,  label: '开仓记录' },
  { key: '/positions-detail',  icon: <BarChartOutlined />,       label: '持仓明细' },
  { key: '/daily-summary',     icon: <BarChartOutlined />,       label: '每日汇总' },
  { key: '/virtuallog',        icon: <ExperimentOutlined />,     label: '模拟盘' },
  { key: '/virtual-detail',    icon: <LineChartOutlined />,      label: '模拟盘明细' },
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
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', background: '#f0f2f5' }}>
      <Card style={{ width: 320 }} title="Binance Trader">
        <Input.Password
          prefix={<LockOutlined />}
          placeholder="请输入访问密码"
          value={pwd}
          onChange={e => { setPwd(e.target.value); setError(false) }}
          onPressEnter={handleLogin}
          status={error ? 'error' : ''}
        />
        {error && <div style={{ color: '#cf1322', marginTop: 8, fontSize: 13 }}>密码错误</div>}
        <Button type="primary" block style={{ marginTop: 16 }} onClick={handleLogin}>进入</Button>
      </Card>
    </div>
  )
}

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
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
    return <LoginPage onLogin={() => setAuthed(true)} />
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', padding: '0 24px', gap: 32 }}>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 16, whiteSpace: 'nowrap' }}>
          Binance Trader
        </span>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1, minWidth: 0 }}
        />
      </Header>
      <Content style={{ padding: 24 }}>
        <Routes>
          <Route path="/"           element={<Dashboard />} />
          <Route path="/positions"   element={<Positions />} />
          <Route path="/openlog"    element={<OpenLog />} />
          <Route path="/daily-summary"     element={<DailySummary />} />
          <Route path="/virtuallog"        element={<VirtualLog />} />
          <Route path="/virtual-detail"   element={<VirtualDetail />} />
          <Route path="/positions-detail" element={<PositionsDetail />} />
        </Routes>
      </Content>
    </Layout>
  )
}
