/**
 * 对外数据口径的单一真源（R5-7）。
 *
 * 2026-09-15 起高德地图与 Wikivoyage(CC BY-SA) 语料已随 AI-native 数据面退役，
 * V4 进一步移除本地点位知识库（poi_knowledge）。分享页页脚与 AppShell 页脚**必须**引用这里，
 * 不得再各写一份「数据来自高德 / Wikivoyage / Unsplash」的过时文案（对外误导）。
 *
 * 注：功能性的国内地图深链仍走 uri.amap.com（见 utils/geo.ts），那是「打开外部地图 App 核实」
 * 的链接提供方，与「行程数据来自哪里」是两回事，不在此文案范畴。
 */

/** 数据来源一句（底图 / 生成 / 坐标天气 / 图片）。 */
export const DATA_PROVENANCE =
  '地图底图来自 OpenFreeMap；行程要点由 LLM 世界知识与联网检索生成，' +
  '坐标/分类/图片来自 OpenTripMap，天气来自 Open-Meteo，图片另含 Unsplash / Pexels'

/** 关键事实需出发前核实的提醒（价格为 AI 估算）。 */
export const DATA_PROVENANCE_DISCLAIMER =
  '价格为 AI 估算，营业时间等关键事实可能变化，出发前请以现场或官方渠道为准'

/**
 * 备选池「未被外部数据源证实存在」的标签（PLAN-A1 G6-A）。
 *
 * 主行程项在生成时逐个过了存在性判定；备选池那 24-40 个名字由后台批量补验，
 * 证实的会带回真实坐标。所以「没有坐标」就是「没被证实」的可靠信号——
 * 判定层不新造徽章（09-19 复评：不加灰档），文案在此单一定义。
 */
export const SUGGESTION_UNVERIFIED_LABEL = 'AI 备选，未核实'
