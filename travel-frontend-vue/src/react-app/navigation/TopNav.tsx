import { useState } from 'react'
import { navigate, useLocation } from '../router'
import { Brand } from '../shared/Brand'
import { Icon } from '../shared/Icon'

const links = [
  { label: '目的地', path: '/destinations' },
  { label: '旅行灵感', path: '/inspiration' },
  { label: '旅行攻略', path: '/guides' },
]

export function TopNav({ onLogin, onLogout, username }: { onLogin?: () => void; onLogout?: () => void; username?: string }) {
  const [open, setOpen] = useState(false)
  const location = useLocation()
  const isActive = (path: string) => location.path === path || location.path.startsWith(`${path}/`)
  const go = (path: string) => { setOpen(false); navigate(path) }
  return <header className="top-nav">
    <div className="top-nav-inner">
      <Brand />
      <nav id="primary-navigation" className={open ? 'top-nav-links open' : 'top-nav-links'} aria-label="主导航">
        {links.map((link) => <button key={link.path} className={isActive(link.path) ? 'top-nav-link active' : 'top-nav-link'} type="button" onClick={() => go(link.path)}>{link.label}</button>)}
        <span className="top-nav-divider" />
        <button className={isActive('/trips') ? 'top-nav-link active' : 'top-nav-link'} type="button" onClick={() => go('/trips')}>我的行程</button>
        {username
          ? <><span>{username}</span><button className="top-nav-login" type="button" onClick={() => { setOpen(false); if (onLogout) onLogout() }}>登出</button></>
          : <button className="top-nav-login" type="button" onClick={() => { setOpen(false); if (onLogin) onLogin(); else go('/login') }}>登录 / 注册</button>}
      </nav>
      <button className="top-nav-menu" type="button" aria-label={open ? '关闭导航' : '打开导航'} aria-expanded={open} aria-controls="primary-navigation" onClick={() => setOpen((value) => !value)}><Icon name={open ? 'close' : 'menu'} size={22} /></button>
    </div>
  </header>
}
