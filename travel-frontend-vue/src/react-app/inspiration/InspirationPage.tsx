import { useMemo, useState } from 'react'
import { navigate } from '../router'
import { inspirationTemplates } from '../data'
import type { InspirationTemplate } from '../data'
import { Icon } from '../shared/Icon'
import { SmartImg } from '../shared/SmartImg'
import { PageHeader } from '../shared/PageHeader'

const themes = ['全部', '美食', '慢旅行', '亲子', '自然', '城市漫游']

export function InspirationPage() {
  const [theme, setTheme] = useState('全部')
  const filtered = useMemo(() => inspirationTemplates.filter((item) => theme === '全部' || item.theme === theme), [theme])
  const fill = (item: InspirationTemplate) => navigate(`/?template=${encodeURIComponent(item.id)}&city=${encodeURIComponent(item.city)}&days=${item.days}&intent=${encodeURIComponent(item.intent)}`)
  return <div className="page-content inspiration-page"><PageHeader eyebrow="Inspiration" title="还没想好去哪？先从一种感觉开始" description="把旅行变成一个可以慢慢编辑的起点。选一个模板，司南会把它填入规划表单，你可以随时改成自己的样子。" action={<button className="button button-primary" type="button" onClick={() => navigate('/')}>写下我的想法<Icon name="arrow" size={17} /></button>} /><div className="theme-tabs" role="tablist" aria-label="旅行主题">{themes.map((item) => <button key={item} className={theme === item ? 'theme-tab active' : 'theme-tab'} type="button" onClick={() => setTheme(item)}>{item}</button>)}</div><div className="inspiration-grid">{filtered.map((item, index) => <article className={index === 0 ? 'inspiration-card featured' : 'inspiration-card'} key={item.id}><button className="inspiration-image" type="button" onClick={() => fill(item)}><SmartImg src={item.image} alt={`${item.city}旅行灵感`} ratio="4 / 3" /><span className="inspiration-theme">{item.theme}</span></button><div className="inspiration-copy"><span className="card-kicker">{item.city} · {item.days} 天</span><h2>{item.title}</h2><p>{item.description}</p><div className="inspiration-tags">{item.tags.map((tag) => <span key={tag}>{tag}</span>)}</div><button className="text-action" type="button" onClick={() => fill(item)}>用这个模板开始 <Icon name="arrow" size={15} /></button></div></article>)}</div></div>
}
