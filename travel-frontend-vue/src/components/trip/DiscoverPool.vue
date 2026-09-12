<template>
  <section class="discover">
    <div class="discover-head">
      <div class="discover-heading">
        <h2 class="discover-title">发现更多</h2>
        <p class="discover-sub">候选池与模型备选中未排入行程的点位，点击即可加入（海外城市图片以第三方检索命中为准）</p>
      </div>
      <el-radio-group v-model="discoverTab" class="discover-tabs" size="large">
        <el-radio-button v-for="c in DISCOVER_TABS" :key="c.key" :value="c.key">
          {{ c.label }} {{ discoverByCategory[c.key]?.length ? `(${discoverByCategory[c.key].length})` : '' }}
        </el-radio-button>
      </el-radio-group>
    </div>
    <div class="discover-grid">
      <article v-for="s in discoverPois" :key="s.name" class="discover-card">
        <div class="discover-img">
          <img
            v-if="!discoverImgFailed[s.name]"
            :src="suggestionPhoto(s)"
            :alt="s.name"
            loading="lazy"
            @error="discoverImgFailed[s.name] = true"
          />
          <span v-else class="discover-img-fallback">{{ categoryLabel(s.category) }}</span>
          <span class="discover-cat">{{ categoryLabel(s.category) }}</span>
          <span v-if="s.needReservation" class="discover-rsvp">需预约</span>
        </div>
        <div class="discover-body">
          <h3 class="discover-name" :title="s.name">{{ s.name }}</h3>
          <p v-if="s.intro" class="discover-intro" :title="s.intro">{{ s.intro }}</p>
          <p class="discover-addr" :title="s.address || ''">{{ s.address || '暂无地址' }}</p>
          <p class="discover-meta">
            <span v-if="s.estimatedCost != null && s.estimatedCost > 0" class="rate">
              ￥{{ s.estimatedCost }}<i>起</i>
            </span>
            <span v-else class="free">免费 · 价格以现场为准</span>
          </p>
        </div>
        <el-button class="discover-add" type="primary" size="small" @click="openDiscoverAdd(s)">
          加入行程
        </el-button>
      </article>
      <el-empty
        v-if="availableSuggestions.length === 0"
        class="discover-empty"
        description="暂无备选推荐，重新生成行程可获得个性化备选池"
      />
      <el-empty
        v-else-if="discoverPois.length === 0"
        class="discover-empty"
        description="该分类下暂无备选，试试其他分类"
      />
    </div>
  </section>

  <el-dialog v-model="discoverAddVisible" title="加入行程" width="400px">
    <p class="discover-add-tip">
      将「{{ discoverSuggestion?.name }}」（{{ discoverSuggestion ? categoryLabel(discoverSuggestion.category) : '' }}）加入哪一天？
    </p>
    <p v-if="discoverSuggestion?.needReservation" class="discover-add-rsvp">
      该地点通常需要提前预约，建议加入后尽早通过官方渠道预约。
    </p>
    <el-select v-model="discoverDayId" style="width: 100%" placeholder="选择日期">
      <el-option
        v-for="d in detail?.dayList || []"
        :key="d.dayId"
        :label="`第${d.dayNo}天${d.travelDate ? ' · ' + d.travelDate : ''}`"
        :value="d.dayId"
      />
    </el-select>
    <template #footer>
      <el-button @click="discoverAddVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onDiscoverAdd">加入</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import { storeToRefs } from 'pinia'
import { searchPoi } from '../../api/amap'
import { useItineraryStore } from '../../store/itinerary'
import { useItineraryActions } from '../../composables/useItineraryActions'
import type { TripSuggestion } from '../../types/itinerary'
import { isForeignCity } from '../../utils/geo'

// 备选池 / 发现更多（M4-②a §5.4）：分类页签 + 备选卡 + 加入行程对话框原样迁出。
// 采纳（含开放模式缺坐标时的高德补点）经 useItineraryActions 写入口；成功后 emit('adopt') 供壳感知。
const emit = defineEmits<{
  adopt: [suggestion: TripSuggestion]
}>()

const store = useItineraryStore()
const actions = useItineraryActions()
const { detail } = storeToRefs(store)
const detailForeign = computed(() => isForeignCity(detail.value?.city ?? ''))

/* ---------- 发现更多：备选池（生成时未排入行程的候选点位） ---------- */
/* 分类页签：无「全部」页签，默认选中第一个分类，避免不同类别的过滤混在一起 */
const DISCOVER_TABS = [
  { key: 'attraction', label: '景点' },
  { key: 'activity', label: '体验·游玩' },
  { key: 'food', label: '美食' },
  { key: 'hotel', label: '酒店' },
  { key: 'shopping', label: '购物' },
] as const

type DiscoverCategoryKey = (typeof DISCOVER_TABS)[number]['key']

const CATEGORY_LABELS: Record<string, string> = {
  attraction: '景点',
  activity: '体验·游玩',
  food: '美食',
  hotel: '酒店',
  shopping: '购物',
  souvenir: '购物',
}

function categoryLabel(key: string) {
  return CATEGORY_LABELS[key] ?? '景点'
}

const discoverTab = ref<DiscoverCategoryKey>('attraction')
const discoverImgFailed = ref<Record<string, boolean>>({})
const discoverAddVisible = ref(false)
const discoverSuggestion = ref<TripSuggestion | null>(null)
const discoverDayId = ref<number | null>(null)
// 对话框「加入」按钮的 loading 绑定（原视图共享 saving 仅由编辑保存路径置位，本路径恒为 false）
const saving = ref(false)

const usedPoiNames = computed(() => {
  const names = new Set<string>()
  for (const d of detail.value?.dayList || []) {
    for (const it of d.items) names.add((it.poiName || '').replace(/\s+/g, ''))
  }
  return names
})

/* 备选池 = 行程级 suggestions（used=false），且兜底排除已在行程中的同名点位 */
const availableSuggestions = computed(() =>
  (detail.value?.suggestions ?? []).filter(
    (s) =>
      !s.used &&
      !usedPoiNames.value.has((s.name || '').replace(/\s+/g, ''))
  )
)

const discoverByCategory = computed(() => {
  const map: Record<string, TripSuggestion[]> = {}
  for (const c of DISCOVER_TABS) map[c.key] = []
  for (const s of availableSuggestions.value) {
    const bucket = map[s.category] ?? map['attraction']
    bucket.push(s)
  }
  return map
})

const discoverPois = computed(() => discoverByCategory.value[discoverTab.value] ?? [])

function suggestionPhoto(s: TripSuggestion) {
  const city = detail.value?.city ?? ''
  // 海外跳过高德（无覆盖且慢）；代理侧走 Unsplash → Wikipedia → Commons
  const skip = detailForeign.value ? '&skipAmap=true' : ''
  return `/api/amap/poi-photo?name=${encodeURIComponent(s.name)}&city=${encodeURIComponent(city)}${skip}`
}

function openDiscoverAdd(s: TripSuggestion) {
  discoverSuggestion.value = s
  discoverDayId.value = detail.value?.dayList[0]?.dayId ?? null
  discoverAddVisible.value = true
}

async function onDiscoverAdd() {
  const s = discoverSuggestion.value
  if (!s || discoverDayId.value == null) return
  // itemType 白名单仅 attraction/food/hotel/transport：美食归 food，酒店归 hotel，其余（含伴手礼/体验）按游玩点归 attraction
  const itemType =
    s.category === 'food'
      ? 'food'
      : s.category === 'hotel'
        ? 'hotel'
        : 'attraction'
  // 开放模式生成的备选可能没有坐标：加入前先经高德检索补齐；
  // 检索失败不阻断加入（坐标留空，列表可见但不显示在地图上）。
  let latitude = s.latitude ?? undefined
  let longitude = s.longitude ?? undefined
  let address = s.address || undefined
  if (latitude == null || longitude == null) {
    try {
      const poiRes = await searchPoi(s.name, detail.value?.city)
      const hit = (poiRes.data || []).find(p => p.latitude != null && p.longitude != null)
      if (hit) {
        latitude = hit.latitude ?? undefined
        longitude = hit.longitude ?? undefined
        address = address || hit.address || undefined
      }
    } catch {
      // 补坐标失败时按原样加入
    }
  }
  // 与拆分前一致：本路径不触发布局 loading（saving 仅在原视图的编辑保存路径置位）
  await actions.addItem(detail.value!.id, {
    dayId: discoverDayId.value,
    itemType,
    poiName: s.name,
    poiId: s.poiId || undefined,
    address,
    latitude,
    longitude,
    cost: s.estimatedCost ?? undefined,
  })
  ElMessage.success(
    s.needReservation
      ? `已将「${s.name}」加入行程，该地点通常需要提前预约`
      : `已将「${s.name}」加入行程`
  )
  discoverAddVisible.value = false
  emit('adopt', s)
}
</script>

<style scoped>
/* ---------- 发现更多：备选点位卡片 ---------- */
.discover {
  margin-bottom: 16px;
}

.discover-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.discover-title {
  margin: 0;
  font-family: var(--lp-font-display);
  font-weight: 500;
  font-size: 22px;
  color: var(--lp-ink);
}

.discover-sub {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--lp-muted);
}

/* 分类页签胶囊：加大尺寸、独立圆角、间距更清晰 */
.discover-tabs :deep(.el-radio-button__inner) {
  padding: 11px 24px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.02em;
  border-radius: 999px;
  border-color: var(--lp-border);
}

.discover-tabs :deep(.el-radio-button) {
  margin-left: 8px;
}

.discover-tabs :deep(.el-radio-button:first-child) {
  margin-left: 0;
}

.discover-tabs :deep(.el-radio-button + .el-radio-button .el-radio-button__inner) {
  border-left: 1px solid var(--lp-border);
}

.discover-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  min-height: 120px;
}

@media (max-width: 1200px) {
  .discover-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 900px) {
  .discover-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.discover-card {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  border: 1px solid var(--lp-border);
  border-radius: 12px;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}

.discover-card:hover {
  border-color: var(--lp-accent);
  box-shadow: 0 4px 16px rgb(15 118 110 / 12%);
}

.discover-img {
  position: relative;
  height: 150px;
  background: var(--lp-sand);
}

.discover-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.discover-img-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--lp-accent);
  font-weight: 700;
  font-size: 13px;
  letter-spacing: 0.08em;
}

.discover-cat {
  position: absolute;
  top: 8px;
  left: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgb(12 46 44 / 72%);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.discover-rsvp {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--lp-accent-warm);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.discover-body {
  flex: 1;
  padding: 12px 14px 0;
}

.discover-name {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--lp-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.discover-intro {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--lp-ink-soft);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 40px;
}

.discover-addr {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--lp-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.discover-meta {
  margin: 6px 0 0;
  min-height: 18px;
  display: flex;
  gap: 10px;
  font-size: 13px;
  color: var(--lp-ink-soft);
}

.discover-meta .rate {
  color: var(--lp-gold);
  font-weight: 700;
}

.discover-meta .rate i {
  font-style: normal;
  font-weight: 500;
  font-size: 11px;
  margin-left: 2px;
}

.discover-meta .free {
  font-size: 12px;
  color: var(--lp-muted);
}

.discover-add {
  margin: 10px 14px 14px;
  align-self: flex-start;
}

.discover-empty {
  grid-column: 1 / -1;
}

.discover-add-tip {
  margin: 0 0 12px;
  font-size: 14px;
  color: var(--lp-ink);
}

.discover-add-rsvp {
  margin: -6px 0 12px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgb(189 98 70 / 8%);
  border-left: 3px solid var(--lp-accent-warm);
  font-size: 13px;
  line-height: 1.5;
  color: var(--lp-ink-soft);
}
</style>
