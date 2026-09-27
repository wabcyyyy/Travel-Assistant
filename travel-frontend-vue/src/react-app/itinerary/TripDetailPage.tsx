import { useEffect, useMemo, useState } from 'react'
import {
  createPdfExport,
  createShare,
  exportDownloadUrl,
  getItineraryDetail,
  getItineraryWeather,
  isOfflineError,
  isUnauthorized,
  listMyItemFeedback,
  optimizeDay,
  revokeItemFeedback,
  setFavorite,
  submitItemFeedback,
  updateDay,
  waitForExport,
} from '../../api/sinan'
import { ReactApiError } from '../../api/sinan'
import type * as Contracts from '../../types/generated/contracts'
import type { ItineraryDetail } from '../../types/itinerary'
import { destinations, sampleItinerary } from '../data'
import { loginRedirect, navigate, routeId } from '../router'
import { Icon } from '../shared/Icon'
import { EmptyBlock, ErrorBlock, LoadingBlock, QualityNotice } from '../shared/States'
import { DraftOnlyBanner, ItemEvidence, TripMetrics } from './TripBadges'
import { ChatPanel } from './ChatPanel'
import { feedbackIndex } from './itemFeedback'
import { ItemFeedbackControl } from './ItemFeedbackControl'
import { TripMapPanel } from './TripMapPanel'
import type { MapPin } from './mapPins'

function displayDate(value: string | null | undefined) {
  if (!value) return ''
  const date = new Date(`${value}T00:00:00`)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

export function TripDetailPage({ path }: { path: string }) {
  const id = routeId(path, '/trips/') || '0'
  const [trip, setTrip] = useState<ItineraryDetail | null>(null)
  const [dayNo, setDayNo] = useState(1)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [authExpired, setAuthExpired] = useState(false)
  const [offline, setOffline] = useState(false)
  const [notice, setNotice] = useState('')
  const [shareUrl, setShareUrl] = useState('')
  const [downloadUrl, setDownloadUrl] = useState('')
  const [weather, setWeather] = useState<Contracts.WeatherVO | null>(null)
  const [editingTheme, setEditingTheme] = useState(false)
  const [themeDraft, setThemeDraft] = useState('')
  const [activePin, setActivePin] = useState<string | null>(null)
  // 条目对/错反馈（C3.5）：本人反馈索引 + 能力开关（GET 404 = addon 关，隐藏控件）
  const [feedbacks, setFeedbacks] = useState<Map<number, Contracts.FeedbackVO>>(new Map())
  const [feedbackOn, setFeedbackOn] = useState(false)

  const selectPin = (pin: MapPin) => {
    setDayNo(pin.dayNo)
    setActivePin(pin.key)
  }

  const load = () => {
    setLoading(true)
    setError('')
    setAuthExpired(false)
    setOffline(false)
    setWeather(null)
    setFeedbacks(new Map())
    setFeedbackOn(false)
    if (id === '0' || !localStorage.getItem('sinan-username')) {
      setTrip({ ...sampleItinerary, id: Number(id) || 0 })
      setOffline(true)
      setLoading(false)
      return
    }
    getItineraryDetail(id)
      .then(setTrip)
      .catch((err: unknown) => {
        if (isUnauthorized(err)) {
          setAuthExpired(true)
          setError('登录已失效，请重新登录后继续查看这段旅程')
        } else if (isOfflineError(err)) {
          setTrip({ ...sampleItinerary, id: Number(id) || 0 })
          setOffline(true)
        } else {
          setError(err instanceof Error ? err.message : '行程读取失败')
        }
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [id])

  /** 对话应用/冲突后的静默对账：不闪 loading，直接换上服务端最新详情。 */
  const refreshDetail = () => {
    if (offline || id === '0' || !localStorage.getItem('sinan-username')) return
    getItineraryDetail(id).then(setTrip).catch(() => {})
  }

  useEffect(() => {
    if (!trip || offline || id === '0' || !localStorage.getItem('sinan-username')) return
    let alive = true
    getItineraryWeather(id).then((value) => { if (alive && value.daily?.length) setWeather(value) }).catch(() => {})
    // 能力探针兼回显：200=开（拿到本人反馈），404=flag 关或非成员（隐藏，不暴露能力存在性）
    listMyItemFeedback(id)
      .then((list) => { if (alive) { setFeedbacks(feedbackIndex(list.feedbacks)); setFeedbackOn(true) } })
      .catch((err: unknown) => { if (alive && err instanceof ReactApiError && err.status === 404) setFeedbackOn(false) })
    return () => { alive = false }
  }, [id, offline, trip?.id])

  useEffect(() => {
    if (trip) document.title = `${trip.city} · 司南 Sinan`
    return () => { document.title = '司南 Sinan' }
  }, [trip])

  const day = useMemo(() => trip?.dayList.find((item) => item.dayNo === dayNo) || trip?.dayList[0], [dayNo, trip])

  useEffect(() => {
    setThemeDraft(day?.theme || '')
    setEditingTheme(false)
  }, [day?.dayNo, day?.theme])

  if (loading) return <div className="page-content detail-state"><LoadingBlock label="正在打开这段旅程…" /></div>
  if (error || !trip) return <div className="page-content detail-state"><ErrorBlock message={error || '行程不存在'} onRetry={load} onLogin={authExpired ? () => navigate(loginRedirect()) : undefined} /></div>

  const handleWriteError = (err: unknown, fallback: string) => {
    if (isUnauthorized(err)) {
      setNotice('登录已失效，正在返回登录页…')
      navigate(loginRedirect())
      return
    }
    setNotice(err instanceof Error ? err.message : fallback)
  }

  const regenerateDay = async () => {
    if (offline || !day) { setNotice('这是离线示例，无法写回服务端'); return }
    setWorking(true)
    try {
      const result = await optimizeDay(trip.id, day.dayId)
      setTrip(result)
      setNotice(`第 ${day.dayNo} 天已重新排好`)
    } catch (err) {
      handleWriteError(err, '重新生成失败')
    } finally { setWorking(false) }
  }

  const saveTheme = async () => {
    if (offline || !day) { setNotice('这是离线示例，无法写回服务端'); return }
    setWorking(true)
    try {
      const result = await updateDay(trip.id, day.dayId, themeDraft.trim())
      setTrip(result)
      setEditingTheme(false)
      setNotice('当天标题已保存')
    } catch (err) {
      handleWriteError(err, '保存失败')
    } finally { setWorking(false) }
  }

  const favorite = async () => {
    if (offline) { setNotice('示例行程不会写入账号'); return }
    try {
      const result = await setFavorite(trip.id, !trip.favorite)
      setTrip(result)
    } catch (err) { handleWriteError(err, '收藏失败') }
  }

  /** 反馈提交/撤销：父层 toast 后向控制组件 rethrow——选择器据失败保持打开供重试 */
  const applyFeedback = async (payload: Contracts.FeedbackCreate) => {
    if (offline || !trip) { setNotice('示例行程不会写入账号'); throw new Error('offline') }
    try {
      const vo = await submitItemFeedback(trip.id, payload)
      setFeedbacks((prev) => new Map(prev).set(vo.itemId, vo))
    } catch (err) {
      handleWriteError(err, '反馈提交失败')
      throw err
    }
  }

  const removeFeedback = async (itemId: number) => {
    if (offline || !trip) { setNotice('示例行程不会写入账号'); throw new Error('offline') }
    const drop = () => setFeedbacks((prev) => { const next = new Map(prev); next.delete(itemId); return next })
    try {
      await revokeItemFeedback(trip.id, itemId)
      drop()
    } catch (err) {
      // 已不存在（重复撤销）按成功收敛；其余交给统一错误提示
      if (err instanceof ReactApiError && err.status === 404) { drop(); return }
      handleWriteError(err, '反馈撤销失败')
      throw err
    }
  }

  const share = async () => {
    if (offline) { setNotice('登录并连接服务后才能创建分享链接'); return }
    try {
      const result = await createShare(trip.id)
      setShareUrl(result.shareUrl)
      await navigator.clipboard?.writeText(result.shareUrl)
      setNotice('分享链接已复制')
    } catch (err) { handleWriteError(err, '分享失败') }
  }

  const exportPdf = async () => {
    if (offline) { setNotice('示例行程暂不支持导出'); return }
    try {
      const task = await createPdfExport(trip.id)
      const done = task.status === 'DONE' ? task : await waitForExport(task.id)
      setDownloadUrl(done.downloadUrl || exportDownloadUrl(done.id))
      setNotice('PDF 已准备好，可以下载')
    } catch (err) { handleWriteError(err, '导出失败') }
  }

  return <div className="detail-page">
    <div className="detail-topbar">
      <button className="back-link" type="button" onClick={() => navigate('/trips')}><Icon name="arrow" size={16} />我的行程</button>
      <div className="detail-actions">
        <button className="icon-action" type="button" aria-label={trip.favorite ? '取消收藏' : '收藏'} onClick={favorite}><Icon name="heart" size={18} /></button>
        <button className="button button-secondary" type="button" onClick={share}><Icon name="share" size={16} />分享</button>
        <button className="button button-secondary" type="button" onClick={exportPdf}><Icon name="download" size={16} />导出</button>
      </div>
    </div>
    {offline && <div className="detail-offline"><span>示例状态</span> 这是本地预览，服务恢复后可打开真实行程。</div>}
    <DraftOnlyBanner status={trip.destinationStatus} />
    <section className="detail-hero">
      <div>
        <span className="section-eyebrow">{trip.city} · {trip.days} 天 · {trip.persons} 人</span>
        <h1>{trip.title}</h1>
        <p>{trip.tripTheme || trip.planNote}</p>
        <QualityNotice status={trip.qualityStatus} pending={trip.pendingFactCount || 0} />
        <TripMetrics
          trip={trip}
          dateText={trip.startDate ? displayDate(trip.startDate) : '待定'}
          weatherDays={weather?.daily?.length || trip.days}
          hasWeather={Boolean(weather?.daily?.length)}
        />
        {weather?.daily?.length ? <div className="detail-weather" aria-label="天气参考"><span className="weather-label"><Icon name="sun" size={16} />天气参考</span>{weather.daily.slice(0, 3).map((item) => <span className="weather-day" key={item.date}><strong>{displayDate(item.date)}</strong><small>{item.text} · {item.tMin ?? '--'}–{item.tMax ?? '--'}℃</small></span>)}</div> : null}
      </div>
      <figure className="detail-cover"><img src={destinations.find((item) => item.city === trip.city)?.image || destinations[0].image} alt="旅行目的地参考封面" width="720" height="480" /><figcaption><Icon name="pin" size={14} />{trip.city} · 城市印象</figcaption></figure>
    </section>
    <div className={offline ? 'detail-workspace' : 'detail-workspace has-chat'}>
      {!offline && <ChatPanel itineraryId={trip.id} dayList={trip.dayList} onApplied={setTrip} onReconcile={refreshDetail} />}
      <aside className="day-sidebar"><div className="sidebar-head"><span className="section-eyebrow">Daily plan</span><strong>{trip.days} 天行程</strong></div>{trip.dayList.map((item) => <button key={item.dayNo} className={item.dayNo === dayNo ? 'day-tab active' : 'day-tab'} type="button" onClick={() => setDayNo(item.dayNo)}><span>DAY {String(item.dayNo).padStart(2, '0')}</span><strong>{item.theme || `第 ${item.dayNo} 天`}</strong><small>{item.items.length} 个安排</small></button>)}</aside>
      <section className="day-content">{day ? <>
        <TripMapPanel days={trip.dayList} activeKey={activePin} onSelect={selectPin} />
        <div className="day-content-head"><div><span className="section-eyebrow">DAY {String(day.dayNo).padStart(2, '0')}</span>{editingTheme ? <div className="day-theme-editor"><input value={themeDraft} maxLength={80} onChange={(event) => setThemeDraft(event.target.value)} aria-label="当天标题" /><div><button className="button button-primary" type="button" disabled={working} onClick={saveTheme}>保存</button><button className="button button-secondary" type="button" disabled={working} onClick={() => { setThemeDraft(day.theme || ''); setEditingTheme(false) }}>取消</button></div></div> : <><h2>{day.theme || `第 ${day.dayNo} 天`}</h2><p>{day.note}</p></>}</div><div className="day-head-actions">{!editingTheme && <button className="button button-secondary" type="button" onClick={() => offline ? setNotice('示例行程不会写入账号') : setEditingTheme(true)}><Icon name="edit" size={16} />编辑标题</button>}<button className="button button-secondary" type="button" disabled={working || editingTheme} onClick={regenerateDay}><Icon name="refresh" size={16} />{working ? '正在整理…' : '重新生成这一天'}</button></div></div>
        <div className="day-items">{day.items.map((item, index) => <article className="day-item" key={`${item.poiName}-${index}`}><div className="day-item-time">{item.startTime || '--:--'}<span>{item.endTime || ''}</span></div><div className="day-item-line"><i /><span /></div><div className="day-item-copy"><div className="item-heading"><span className="item-type">{{ attraction: '游览', food: '用餐', hotel: '住宿', transport: '交通', activity: '活动' }[item.itemType] || '安排'}</span><h3>{item.poiName}</h3></div><p>{item.remark || item.whyThis || '为这一段旅程保留一点自由。'}</p><div className="item-meta"><span><Icon name="clock" size={14} />{item.durationMin ? `${item.durationMin} 分钟` : '时间可调整'}</span><ItemEvidence item={item} /></div>{feedbackOn && item.id ? <ItemFeedbackControl itemId={item.id} feedback={feedbacks.get(item.id)} onSet={applyFeedback} onRevoke={() => removeFeedback(item.id!)} /> : null}</div></article>)}</div>
        {day.practicalNotes?.length ? <div className="day-note"><Icon name="alert" size={17} /><div><strong>出发前看一眼</strong>{day.practicalNotes.map((note) => <p key={note}>{note}</p>)}</div></div> : null}
      </> : <EmptyBlock title="这一天还没有安排" description="可以先切换到其他天，或重新生成当天内容。" />}</section>
    </div>
    {shareUrl && <div className="share-result"><span>分享链接</span><a href={shareUrl} target="_blank" rel="noreferrer">{shareUrl}</a><button type="button" onClick={() => setShareUrl('')} aria-label="关闭分享链接"><Icon name="close" size={15} /></button></div>}
    {downloadUrl && <div className="download-result"><span>PDF 已就绪</span><a className="button button-primary" href={downloadUrl} download>下载 PDF<Icon name="download" size={15} /></a><button type="button" onClick={() => setDownloadUrl('')} aria-label="关闭下载提示"><Icon name="close" size={15} /></button></div>}
    {notice && <div className="toast-note" role="status">{notice}<button type="button" onClick={() => setNotice('')} aria-label="关闭提示"><Icon name="close" size={14} /></button></div>}
  </div>
}

