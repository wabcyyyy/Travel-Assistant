import beijing from '../assets/img/cover-beijing.webp'
import chengdu from '../assets/img/cover-chengdu.webp'
import chongqing from '../assets/img/cover-chongqing.webp'
import hangzhou from '../assets/img/cover-hangzhou.webp'
import shanghai from '../assets/img/cover-shanghai.webp'
import xian from '../assets/img/cover-xian.webp'
import type { ItineraryDetail, ItinerarySummary } from '../types/itinerary'

export type DestinationCategory = '全部' | '人文' | '美食' | '自然' | '慢旅行'

export interface DestinationCard {
  city: string
  province: string
  image: string
  description: string
  categories: Exclude<DestinationCategory, '全部'>[]
  bestFor: string
  days: string
}

export const fallbackCities = ['成都', '杭州', '上海', '北京', '西安', '重庆', '大理', '厦门']

export const destinations: DestinationCard[] = [
  { city: '成都', province: '四川', image: chengdu, description: '从一盏盖碗茶开始，把城市走慢一点。', categories: ['美食', '慢旅行'], bestFor: '川菜、街巷、茶馆', days: '3–5 天' },
  { city: '杭州', province: '浙江', image: hangzhou, description: '湖光、茶山与一段不赶时间的江南日常。', categories: ['自然', '慢旅行'], bestFor: '湖景、茶园、散步', days: '2–4 天' },
  { city: '上海', province: '上海', image: shanghai, description: '沿着梧桐树影，发现城市里安静的转角。', categories: ['人文', '美食'], bestFor: '建筑、展览、咖啡', days: '2–4 天' },
  { city: '北京', province: '北京', image: beijing, description: '在旧城的尺度里，听见一座城市的时间。', categories: ['人文', '美食'], bestFor: '古迹、博物馆、胡同', days: '3–5 天' },
  { city: '西安', province: '陕西', image: xian, description: '一城古意，一路好吃，适合慢慢读懂。', categories: ['人文', '美食'], bestFor: '历史、面食、夜游', days: '3–4 天' },
  { city: '重庆', province: '重庆', image: chongqing, description: '山城的坡度和烟火，组成一场有层次的漫游。', categories: ['美食', '人文'], bestFor: '火锅、夜景、城市漫游', days: '2–4 天' },
  { city: '大理', province: '云南', image: hangzhou, description: '风从洱海来，日子可以只安排一半。', categories: ['自然', '慢旅行'], bestFor: '湖山、日落、发呆', days: '4–6 天' },
  { city: '厦门', province: '福建', image: shanghai, description: '海风、骑楼和适合散步的傍晚。', categories: ['自然', '慢旅行'], bestFor: '海边、街区、骑行', days: '2–4 天' },
]

export interface InspirationTemplate {
  id: string
  title: string
  city: string
  theme: string
  description: string
  days: number
  image: string
  tags: string[]
  intent: string
}

export const inspirationTemplates: InspirationTemplate[] = [
  { id: 'chengdu-slow', title: '把成都走慢一点', city: '成都', theme: '慢旅行', description: '茶馆、老街和一顿不赶时间的川菜。', days: 3, image: chengdu, tags: ['少走路', '本地味道'], intent: '带父母去成都 3 天，少走路，喜欢川菜和老街，节奏松弛一些' },
  { id: 'hangzhou-tea', title: '西湖边的松弛周末', city: '杭州', theme: '自然', description: '湖边散步，去茶园坐一会儿，把周末留给风景。', days: 2, image: hangzhou, tags: ['湖景', '茶园'], intent: '去杭州 2 天，想看西湖和茶园，少安排赶路的景点' },
  { id: 'shanghai-walk', title: '上海的梧桐与夜色', city: '上海', theme: '城市漫游', description: '从老建筑到夜市，顺着街区的纹理认识上海。', days: 3, image: shanghai, tags: ['建筑', '夜游'], intent: '去上海 3 天，喜欢老建筑、展览和夜间散步' },
  { id: 'xian-food', title: '西安一城好吃', city: '西安', theme: '美食', description: '把历史放进白天，把面食和夜色留给晚上。', days: 3, image: xian, tags: ['面食', '古迹'], intent: '去西安 3 天，想看古迹，也想认真吃本地面食' },
  { id: 'beijing-family', title: '带家人读北京', city: '北京', theme: '亲子', description: '故宫、胡同与一份适合全家人的从容节奏。', days: 4, image: beijing, tags: ['博物馆', '不赶路'], intent: '带家人去北京 4 天，想看博物馆和胡同，不要每天排太满' },
  { id: 'chongqing-night', title: '重庆的坡与灯', city: '重庆', theme: '城市漫游', description: '白天看山城层次，晚上去吃一顿热气腾腾的火锅。', days: 3, image: chongqing, tags: ['夜景', '火锅'], intent: '去重庆 3 天，想看夜景、吃火锅，安排一些城市漫游' },
]

export interface GuideContent {
  slug: string
  city: string
  title: string
  excerpt: string
  image: string
  readTime: string
  tag: string
  sections: { title: string; body: string }[]
}

export const guides: GuideContent[] = [
  { slug: 'chengdu-slow-city', city: '成都', title: '成都：把一天还给街巷与茶馆', excerpt: '一份以步行节奏为尺度的成都城市漫游建议。', image: chengdu, readTime: '6 分钟阅读', tag: '慢旅行', sections: [{ title: '先从一盏茶开始', body: '成都的好，不需要用打卡数量证明。把上午留给宽窄巷子和人民公园，找一张靠窗的桌子坐下来，观察这座城市如何把日常过得松弛。' }, { title: '给午后留一点空白', body: '下午可以沿着少城片区散步，穿过安静的街道，再把一顿川菜安排在傍晚。行程之间留出余量，才有机会遇到计划之外的小店。' }] },
  { slug: 'hangzhou-by-the-lake', city: '杭州', title: '杭州：西湖之外，茶山正好', excerpt: '把湖景、茶园和一段安静的下午放进两天周末。', image: hangzhou, readTime: '5 分钟阅读', tag: '自然', sections: [{ title: '湖边不必走完', body: '西湖很大，不需要用环湖一圈完成任务。选一段喜欢的湖岸，在树影下慢慢走，再把时间交给一间茶室。' }, { title: '去茶园呼吸', body: '龙井一带适合在上午前往，光线柔和，空气里有湿润的植物气息。回到市区后，留出一餐江南口味的晚饭。' }] },
  { slug: 'beijing-old-city', city: '北京', title: '北京：用一条胡同读懂旧城', excerpt: '故宫之外，旧城的尺度藏在一条条胡同的转弯里。', image: beijing, readTime: '7 分钟阅读', tag: '人文', sections: [{ title: '把博物馆留给上午', body: '北京的热门文化场馆需要提前核实开放时间和预约规则。上午看展，下午沿着胡同走一段，行程会更从容。' }, { title: '晚饭是另一种城市地图', body: '从小馆子到老字号，晚饭不必追求网红榜单。问问住处附近的人，往往能得到更贴近日常的答案。' }] },
]

export const sampleItinerary: ItineraryDetail = {
  id: 0,
  title: '成都 · 松弛四日',
  city: '成都',
  days: 4,
  stayNights: 3,
  persons: 2,
  budget: 3600,
  preferences: '美食；慢旅行；少走路',
  planNote: '示例行程：用于体验司南的编辑与地图工作台。',
  tripTheme: '把脚步放慢，把成都留给日常',
  status: 2,
  destinationStatus: 'draft_only',
  qualityStatus: 'DRAFT',
  pendingFactCount: 3,
  dayList: [
    { dayId: 1, dayNo: 1, theme: '从茶馆开始认识成都', note: '上午慢游，下午留白。', items: [{ itemType: 'attraction', poiName: '人民公园', poiId: null, address: '青羊区', latitude: 30.657, longitude: 104.066, startTime: '09:30', endTime: '11:30', durationMin: 120, openTime: null, cost: 0, tag: '茶馆', remark: '找一张靠窗的桌子坐一会儿', whyThis: '步行强度低，适合作为第一站', image: null, source: null, sourceUpdatedAt: null, verificationStatus: 'unverified', valueKind: 'estimated', freshnessStatus: 'unknown', reviewRequirement: 'before_departure', factEvidence: {} }, { itemType: 'food', poiName: '少城小馆', poiId: null, address: '少城片区', latitude: 30.666, longitude: 104.059, startTime: '12:00', endTime: '13:30', durationMin: 90, openTime: null, cost: 90, tag: '川菜', remark: '点两道招牌菜即可', whyThis: '把本地口味放进第一顿正餐', image: null, source: null, sourceUpdatedAt: null, verificationStatus: 'unverified', valueKind: 'estimated', freshnessStatus: 'unknown', reviewRequirement: 'before_departure', factEvidence: {} }], backupPlan: [], photoSpots: [], practicalNotes: ['营业时间与预约规则请在出发前核实'], dayOptions: [] },
    { dayId: 2, dayNo: 2, theme: '老街与一顿热辣川菜', note: '把景点和吃饭安排在一条顺路线上。', items: [{ itemType: 'attraction', poiName: '宽窄巷子', poiId: null, address: '青羊区', latitude: 30.662, longitude: 104.056, startTime: '10:00', endTime: '12:00', durationMin: 120, openTime: null, cost: 0, tag: '老街', remark: '避开正午人流', whyThis: '适合慢逛和拍照', image: null, source: null, sourceUpdatedAt: null, verificationStatus: 'unverified', valueKind: 'estimated', freshnessStatus: 'unknown', reviewRequirement: 'before_departure', factEvidence: {} }, { itemType: 'food', poiName: '本地川菜馆', poiId: null, address: '成都', latitude: null, longitude: null, startTime: '18:00', endTime: '19:30', durationMin: 90, openTime: null, cost: 120, tag: '晚餐', remark: '根据当天体力就近选择', whyThis: '晚间不再跨区移动', image: null, source: null, sourceUpdatedAt: null, verificationStatus: 'unverified', valueKind: 'estimated', freshnessStatus: 'unknown', reviewRequirement: 'before_departure', factEvidence: {} }], backupPlan: [], photoSpots: [], practicalNotes: [], dayOptions: [] },
    { dayId: 3, dayNo: 3, theme: '城市里的自然留白', note: '可根据天气在公园与室内之间切换。', items: [{ itemType: 'attraction', poiName: '杜甫草堂', poiId: null, address: '青羊区', latitude: null, longitude: null, startTime: '10:00', endTime: '12:00', durationMin: 120, openTime: null, cost: 50, tag: '人文', remark: '提前核实开放状态', whyThis: '庭院尺度适中，适合慢慢看', image: null, source: null, sourceUpdatedAt: null, verificationStatus: 'unverified', valueKind: 'estimated', freshnessStatus: 'unknown', reviewRequirement: 'before_departure', factEvidence: {} }], backupPlan: [], photoSpots: [], practicalNotes: [], dayOptions: [] },
    { dayId: 4, dayNo: 4, theme: '留给自己的一天', note: '不设必达点位，按兴趣补充。', items: [{ itemType: 'activity', poiName: '成都自由活动', poiId: null, address: '成都', latitude: null, longitude: null, startTime: '10:00', endTime: '17:00', durationMin: 420, openTime: null, cost: null, tag: '留白', remark: '可以回到喜欢的街区', whyThis: '留出调整空间，旅程不会被清单绑住', image: null, source: null, sourceUpdatedAt: null, verificationStatus: 'unverified', valueKind: 'generated', freshnessStatus: 'unknown', reviewRequirement: 'none', factEvidence: {} }], backupPlan: [], photoSpots: [], practicalNotes: [], dayOptions: [] },
  ],
  budgetList: [{ category: '交通', amount: 600, itemCount: 4 }, { category: '餐饮', amount: 1200, itemCount: 8 }, { category: '门票', amount: 300, itemCount: 3 }, { category: '住宿', amount: 1500, itemCount: 3 }],
  totalAmount: 3600,
  sources: [],
  suggestions: [],
}

export const sampleTripSummaries: ItinerarySummary[] = [
  { id: 0, title: sampleItinerary.title, city: '成都', days: 4, persons: 2, budget: 3600, totalAmount: 3600, status: 2, createdAt: '2026-09-20T09:00:00', startDate: null, endDate: null, favorite: true, archived: false, hasShare: false },
]
