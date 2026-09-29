import { useEffect, useMemo, useState } from 'react'
import { isOfflineError, isUnauthorized, listItineraries } from '../../api/sinan'
import { loginRedirect, navigate } from '../router'
import { destinations, sampleTripSummaries } from '../data'
import type { ItinerarySummary } from '../../types/itinerary'
import { Icon } from '../shared/Icon'
import { PageHeader } from '../shared/PageHeader'
import { EmptyBlock, ErrorBlock, OfflineBadge } from '../shared/States'

type Filter = 'all' | 'active' | 'done' | 'draft'

export function TripsPage() {
  const [items, setItems] = useState<ItinerarySummary[]>([])
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [offline, setOffline] = useState(false)
  const [authExpired, setAuthExpired] = useState(false)
  const load = () => { setLoading(true); setError(''); setOffline(false); setAuthExpired(false); if (!localStorage.getItem('sinan-username')) { setItems(sampleTripSummaries); setOffline(true); setLoading(false); return } listItineraries(filter === 'draft' ? 'active' : filter, query).then(setItems).catch((err: unknown) => { if (isUnauthorized(err)) { setItems([]); setAuthExpired(true); setError('登录已失效，请重新登录后继续查看你的行程') } else if (isOfflineError(err)) { setItems(sampleTripSummaries); setOffline(true) } else setError(err instanceof Error ? err.message : '行程加载失败') }).finally(() => setLoading(false)) }
  useEffect(() => { load() }, [filter])
  const visible = useMemo(() => items.filter((item) => !query || `${item.title}${item.city}`.includes(query)), [items, query])
  return <div className="page-content trips-page"><PageHeader eyebrow="My trips" title="我的行程" description="保存过的方向，会在这里继续展开。离线时可以查看最近的本地预览。" action={<button className="button button-primary" type="button" onClick={() => navigate('/')}>新建行程<Icon name="arrow" size={17} /></button>} /><div className="trips-toolbar"><div className="trip-tabs">{[['all', '全部'], ['active', '进行中'], ['done', '已完成'], ['draft', '草稿']].map(([key, label]) => <button key={key} className={filter === key ? 'trip-tab active' : 'trip-tab'} type="button" onClick={() => setFilter(key as Filter)}>{label}</button>)}</div><label className="search-field compact"><Icon name="search" size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') load() }} placeholder="搜索行程" aria-label="搜索行程" /></label></div>{offline && <div className="offline-banner"><OfflineBadge /><span>当前无法连接行程服务，展示的是本地示例。登录并联网后会自动读取真实数据。</span></div>}{loading ? <div className="trip-skeleton-grid"><div /><div /><div /></div> : error ? <ErrorBlock message={error} onRetry={load} onLogin={authExpired ? () => navigate(loginRedirect()) : undefined} /> : visible.length === 0 ? <EmptyBlock title="还没有保存的行程" description="从一句话开始，司南会帮你铺开第一段旅程。" action={{ label: '开始规划', onClick: () => navigate('/') }} /> : <div className="trip-grid">{visible.map((trip) => <article className="trip-card" key={trip.id}><a className="trip-card-cover" href={`/trips/${trip.id}`} onClick={(event) => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return; event.preventDefault(); navigate(`/trips/${trip.id}`) }}><img src={destinations.find((item) => item.city === trip.city)?.image || destinations[0].image} alt={`${trip.city}城市风景`} width="600" height="400" /><span className="trip-card-arrow"><Icon name="arrowUpRight" size={17} /></span></a><div className="trip-card-body"><div className="card-kicker"><span>{trip.city}</span><span>{trip.days} 天 · {trip.persons} 人</span></div><h2>{trip.title}</h2><p>{trip.tripTheme || (trip.id === 0 ? '这是一个可继续编辑的本地预览' : '一段等待出发的旅程')}</p><div className="trip-card-meta"><span>{trip.favorite ? '已收藏' : '最近打开'}</span><span>{new Date(trip.createdAt).toLocaleDateString('zh-CN')}</span></div></div></article>)}</div>}</div>
}

