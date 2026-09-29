import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { logout } from '../api/sinan'
import { AppShell } from './layout/AppShell'
import { DestinationsPage } from './destination/DestinationsPage'
import { GuideDetailPage, GuidesPage } from './guides/GuidesPages'
import { HomePage } from './home/HomePage'
import { InspirationPage } from './inspiration/InspirationPage'
import { LoginPage } from './auth/LoginPage'
import { TripDetailPage } from './itinerary/TripDetailPage'
import { TripsPage } from './itinerary/TripsPage'
import { navigate, useLocation } from './router'
import { SharePage } from './shared/SharePage'

function pageTitle(path: string) {
  if (path === '/') return '司南 Sinan · 让每一段旅程找到方向'
  if (path === '/destinations') return '目的地探索 · 司南 Sinan'
  if (path === '/inspiration') return '旅行灵感 · 司南 Sinan'
  if (path === '/guides' || path.startsWith('/guides/')) return '旅行攻略 · 司南 Sinan'
  if (path === '/trips' || path.startsWith('/trips/')) return '我的行程 · 司南 Sinan'
  if (path === '/login') return '登录 · 司南 Sinan'
  return '司南 Sinan'
}

export default function App() {
  const location = useLocation()
  const [username, setUsername] = useState(() => localStorage.getItem('sinan-username') || '')
  useEffect(() => { document.title = pageTitle(location.path) }, [location.path])
  const authenticated = (value: string) => { setUsername(value); localStorage.setItem('sinan-username', value) }
  /** 登出（P1-7）：先清本地身份并回首页；POST /auth/logout 清 HttpOnly Cookie 是 best-effort，失败不阻塞。 */
  const handleLogout = () => {
    setUsername('')
    localStorage.removeItem('sinan-username')
    logout().catch(() => {})
    navigate('/')
  }
  if (location.path === '/login') return <LoginPage onAuthenticated={authenticated} />
  if (location.path.startsWith('/s/')) return <SharePage path={location.path} />
  let page: ReactNode
  if (location.path === '/') page = <HomePage />
  else if (location.path === '/destinations') page = <DestinationsPage />
  else if (location.path === '/inspiration') page = <InspirationPage />
  else if (location.path === '/guides') page = <GuidesPage />
  else if (location.path.startsWith('/guides/')) page = <GuideDetailPage path={location.path} />
  else if (location.path === '/trips') page = <TripsPage />
  else if (location.path.startsWith('/trips/')) page = <TripDetailPage path={location.path} />
  else page = <HomePage />
  return <AppShell onLogin={() => navigate('/login')} username={username} onLogout={handleLogout}>{page}{username && <span className="sr-only">已登录：{username}</span>}</AppShell>
}
