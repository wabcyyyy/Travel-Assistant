import { useMemo, useState } from 'react'
import { guides } from '../data'
import { navigate, routeId } from '../router'
import { Icon } from '../shared/Icon'
import { PageHeader } from '../shared/PageHeader'
import { OfflineBadge } from '../shared/States'

export function GuidesPage() {
  const [tag, setTag] = useState('全部')
  const tags = ['全部', ...Array.from(new Set(guides.map((guide) => guide.tag)))]
  const filtered = useMemo(() => guides.filter((guide) => tag === '全部' || guide.tag === tag), [tag])
  return <div className="page-content guides-page"><PageHeader eyebrow="Guides" title="出发前，先读一点城市" description="这里的攻略来自仓库内的城市素材，用来帮助你建立方向感。页面内容是示例，具体开放时间和交通请出发前核实。" action={<OfflineBadge />} /><div className="guide-filter">{tags.map((item) => <button key={item} className={tag === item ? 'filter-tab active' : 'filter-tab'} type="button" onClick={() => setTag(item)}>{item}</button>)}</div><div className="guide-grid">{filtered.map((guide) => <article className="guide-card" key={guide.slug}><button type="button" className="guide-image" onClick={() => navigate(`/guides/${guide.slug}`)}><img src={guide.image} alt={`${guide.city}攻略`} /><span>{guide.tag}</span></button><div className="guide-copy"><span className="card-kicker">{guide.city} · {guide.readTime}</span><h2>{guide.title}</h2><p>{guide.excerpt}</p><button type="button" className="text-action" onClick={() => navigate(`/guides/${guide.slug}`)}>阅读攻略 <Icon name="arrow" size={15} /></button></div></article>)}</div></div>
}

export function GuideDetailPage({ path }: { path: string }) {
  const slug = routeId(path, '/guides/')
  const guide = guides.find((item) => item.slug === slug)
  if (!guide) return <div className="page-content"><div className="inline-empty"><strong>攻略不存在</strong><span>返回攻略列表，换一座城市继续阅读。</span><button className="button button-secondary" type="button" onClick={() => navigate('/guides')}>回到攻略</button></div></div>
  return <div className="page-content guide-detail"><button className="back-link" type="button" onClick={() => navigate('/guides')}><Icon name="arrow" size={16} />返回攻略列表</button><div className="guide-detail-hero"><img src={guide.image} alt={`${guide.city}攻略`} /><div><OfflineBadge /><span className="section-eyebrow">{guide.city} · {guide.readTime}</span><h1>{guide.title}</h1><p>{guide.excerpt}</p><button className="button button-primary" type="button" onClick={() => navigate(`/?city=${encodeURIComponent(guide.city)}`)}>按这座城市规划<Icon name="arrow" size={17} /></button></div></div><article className="guide-article"><p className="article-note">示例内容 · 城市事实、营业时间和预约规则请在出发前核实。</p>{guide.sections.map((section) => <section key={section.title}><h2>{section.title}</h2><p>{section.body}</p></section>)}</article></div>
}
