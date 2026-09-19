import type { ItineraryDetail } from '../types/itinerary'
import { typeLabel } from '../components/trip/day-card/shared'
import { cssVar } from './cssVar'

const FONT = '"Microsoft YaHei", "PingFang SC", "Helvetica Neue", sans-serif'

interface Row {
  type: string
  name: string
  time: string
  duration: string
  cost: string
  remark: string
}

/**
 * 把每天的点位映射成导出行（纯函数，可单测）：`type` 走全站唯一口径 typeLabel（R5-3），
 * 与日卡界面共用同一措辞——导出 PNG 与界面不再漂移。
 */
export function buildDayRows(detail: ItineraryDetail): Row[][] {
  return detail.dayList.map((day) =>
    day.items.map((item) => ({
      type: typeLabel(item.itemType),
      name: item.poiName,
      time: item.startTime ? `${item.startTime}${item.endTime ? ' - ' + item.endTime : ''}` : '',
      duration: item.durationMin ? `${item.durationMin}分` : '',
      cost: item.cost != null ? `￥${item.cost}` : '',
      remark: item.remark || '',
    })),
  )
}

export function exportItineraryImage(detail: ItineraryDetail) {
  const width = 920
  const margin = 32
  const contentWidth = width - margin * 2
  const lineHeight = 30
  const headerH = 96
  const budgetH = 168

  // 取色一律走 --lp-* 令牌（R5-4）：canvas 侧不留裸 hex，theme-lint 扩扫 .ts 亦绿。
  const surface = cssVar('--lp-surface-1')
  const stripe = cssVar('--lp-surface-2')
  const ink = cssVar('--lp-text-1')
  const muted = cssVar('--lp-text-muted')
  const accent = cssVar('--lp-accent')
  const onFill = cssVar('--lp-accent-on-fill')
  const success = cssVar('--lp-success')
  const successSoft = cssVar('--lp-success-soft')
  const danger = cssVar('--lp-danger')

  const dayRows = buildDayRows(detail)

  const dayBlockHeights = dayRows.map((rows) => 44 + rows.length * lineHeight)
  const contentH =
    headerH + dayBlockHeights.reduce((a, b) => a + b, 0) + budgetH + (dayRows.length - 1) * 12
  const height = contentH + margin * 2

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = surface
  ctx.fillRect(0, 0, width, height)

  let y = margin

  ctx.fillStyle = ink
  ctx.font = `700 26px ${FONT}`
  ctx.textAlign = 'center'
  ctx.fillText(detail.title, width / 2, y + 26)
  ctx.font = `14px ${FONT}`
  ctx.fillStyle = muted
  const meta = [
    detail.city,
    `${detail.days} 天 ${detail.persons} 人`,
    detail.startDate ? `${detail.startDate} ~ ${detail.endDate}` : '',
    detail.preferences ? `偏好：${detail.preferences}` : '',
    detail.budget != null ? `预算上限：￥${detail.budget}` : '',
  ].filter(Boolean)
  ctx.fillText(meta.join('  |  '), width / 2, y + 52)
  y += headerH

  dayRows.forEach((rows, dayIndex) => {
    const day = detail.dayList[dayIndex]
    ctx.fillStyle = accent
    ctx.fillRect(margin, y, contentWidth, 32)
    ctx.fillStyle = onFill
    ctx.font = `600 15px ${FONT}`
    ctx.textAlign = 'left'
    const dayTitle = `第 ${day.dayNo} 天${day.travelDate ? '（' + day.travelDate + '）' : ''}`
    ctx.fillText(dayTitle, margin + 12, y + 21)
    y += 32

    ctx.font = `12px ${FONT}`
    const headers: [string, number][] = [
      ['类型', 76],
      ['名称', 300],
      ['时间', 170],
      ['时长', 70],
      ['费用', 90],
      ['备注', 0],
    ]
    const baseX = margin + 12
    let colX = baseX
    const colWidths = headers.map(([, w]) => w)
    ctx.fillStyle = surface
    ctx.fillRect(margin, y, contentWidth, lineHeight)
    ctx.fillStyle = muted
    headers.forEach(([label, w]) => {
      ctx.fillText(label, colX, y + 19)
      colX += w === 0 ? contentWidth - 12 - (colX - margin) : w
    })
    y += lineHeight

    ctx.fillStyle = ink
    rows.forEach((row: Row, rowIndex: number) => {
      if (rowIndex % 2 === 1) {
        ctx.fillStyle = stripe
        ctx.fillRect(margin, y, contentWidth, lineHeight)
      }
      ctx.fillStyle = ink
      const values = [row.type, row.name, row.time, row.duration, row.cost, row.remark]
      colX = baseX
      values.forEach((value, index) => {
        ctx.textAlign = 'left'
        ctx.fillText(value, colX, y + 19)
        colX += colWidths[index] === 0 ? contentWidth - 12 - (colX - margin) : colWidths[index]
      })
      y += lineHeight
    })
    y += 12
  })

  y -= 12
  ctx.fillStyle = success
  ctx.fillRect(margin, y, contentWidth, 32)
  ctx.fillStyle = onFill
  ctx.font = `600 15px ${FONT}`
  ctx.fillText('预算明细', margin + 12, y + 21)
  y += 32

  ctx.fillStyle = ink
  ctx.font = `13px ${FONT}`
  const budgetLabelWidth = 120
  const barMaxWidth = contentWidth - budgetLabelWidth - 180
  detail.budgetList.forEach((b) => {
    const label = `${b.category}  ￥${b.amount}`
    ctx.fillText(label, margin + 12, y + 21)
    ctx.fillStyle = successSoft
    ctx.fillRect(margin + 12 + budgetLabelWidth, y + 10, barMaxWidth, 16)
    ctx.fillStyle = success
    const maxAmount = Math.max(...detail.budgetList.map((x) => Number(x.amount)), 1)
    const barW = (Number(b.amount) / maxAmount) * barMaxWidth
    ctx.fillRect(margin + 12 + budgetLabelWidth, y + 10, barW, 16)
    ctx.fillStyle = ink
    y += lineHeight
  })
  y += 4
  ctx.font = `700 15px ${FONT}`
  ctx.fillStyle = danger
  ctx.fillText(`合计：￥${detail.totalAmount}`, margin + 12, y + 21)

  canvas.toBlob((blob) => {
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${detail.title}-行程卡片.png`
    a.click()
    URL.revokeObjectURL(url)
  }, 'image/png')
}
