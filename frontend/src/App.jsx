import { Layout, Menu } from 'antd'
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom'
import { FundOutlined, UnorderedListOutlined, ExperimentOutlined, BarChartOutlined } from '@ant-design/icons'
import Positions from './pages/Positions'
import OpenLog from './pages/OpenLog'
import VirtualLog from './pages/VirtualLog'
import PositionsDetail from './pages/PositionsDetail'
import 'antd/dist/reset.css'

const { Header, Content } = Layout

const menuItems = [
  { key: '/',                icon: <FundOutlined />,          label: '持仓监控' },
  { key: '/openlog',         icon: <UnorderedListOutlined />,  label: '开仓记录' },
  { key: '/virtuallog',      icon: <ExperimentOutlined />,     label: '虚拟盘' },
  { key: '/positions-detail', icon: <BarChartOutlined />,      label: '持仓明细' },
]

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', padding: '0 24px', gap: 32 }}>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 16, whiteSpace: 'nowrap' }}>
          📊 Binance Trader
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
          <Route path="/"        element={<Positions />} />
          <Route path="/openlog"    element={<OpenLog />} />
          <Route path="/virtuallog"       element={<VirtualLog />} />
          <Route path="/positions-detail" element={<PositionsDetail />} />
        </Routes>
      </Content>
    </Layout>
  )
}
