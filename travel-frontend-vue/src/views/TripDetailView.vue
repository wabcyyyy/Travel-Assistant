<template>
  <div class="trip-detail" v-loading="loading">
    <div class="reading-progress" aria-hidden="true"></div>

    <TripCoverHeader
      v-if="detail"
      :detail="detail"
      :exporting-pdf="exportingPdf"
      :exporting-img="exportingImg"
      @export-pdf="onExportPdf"
      @export-image="onExportImage"
      @similar="$router.push('/generate')"
      @back="$router.back()"
    />

    <el-card v-if="detail" shadow="never" class="head">
      <div
        v-if="detail.status === 3"
        class="gen-banner error"
      >
        <span>{{ detail.planNote || '行程生成失败，请重新生成' }}</span>
      </div>
      <div
        v-if="detail.status === 1"
        class="gen-banner"
      >
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>
          AI 正在规划行程，已完成 {{ doneDays }} / {{ detail.days }} 天…
          {{ doneDays >= 1 ? '已生成部分可在下方查看' : '' }}
        </span>
      </div>
      <div v-if="detail.planNote && detail.status !== 3" class="butler-strip">
        <div class="butler-head">AI 管家说</div>
        <p class="butler-text">{{ butlerNote }}</p>
      </div>
      <div class="head-info">
        <div v-if="detail.preferences" class="meta-chips">
          <span class="meta-chip">偏好：{{ detail.preferences }}</span>
        </div>
        <p v-if="dateNightMismatch" class="mismatch-line">
          <el-tag type="warning" size="small">
            日期通常对应 {{ expectedDateNights }} 晚，当前计划含 {{ detail.stayNights }} 晚
          </el-tag>
        </p>
        <p v-if="detail.destinationStatus || detail.qualityStatus" class="quality-summary">
          <el-tag v-if="detail.destinationStatus" size="small" type="info">
            {{ destinationStatusLabel(detail.destinationStatus) }}
          </el-tag>
          <el-tag v-if="detail.qualityStatus" size="small" :type="qualityTagType(detail.qualityStatus)" style="margin-left: 6px">
            {{ qualityStatusLabel(detail.qualityStatus) }}
          </el-tag>
          <span v-if="detail.pendingFactCount" class="quality-hint">
            {{ detail.pendingFactCount }} 项信息需要出发前复核
          </span>
        </p>
      </div>
      <div class="nl-edit">
        <button
          type="button"
          class="nl-toggle"
          :aria-expanded="nlOpen ? 'true' : 'false'"
          @click="nlOpen = !nlOpen"
        >
          <span>{{ nlOpen ? '收起智能修改' : '智能修改行程' }}</span>
          <span class="nl-toggle-hint">
            {{ chatMsgs.length ? `${chatMsgs.length} 条对话` : '用一句话调整酒店、节奏或点位' }}
          </span>
        </button>
        <div v-show="nlOpen" class="nl-panel">
        <div class="chat-scroll">
        <div v-for="(m, i) in chatMsgs" :key="m.id || i" class="chat-line" :class="m.role">
          <div v-if="m.role === 'ai'" class="markdown-body" v-html="renderMarkdown(m.content)"></div>
          <template v-else>{{ m.content }}</template>
          <div v-if="m.plans && m.plans.length" class="draft-preview">
            <div class="draft-summary-title">本次变更</div>
            <div v-for="change in draftChanges(m)" :key="change" class="draft-change">{{ change }}</div>
            <div v-for="d in m.plans" :key="d.day_no" class="draft-day">
              <b>第{{ d.day_no }}天</b>：
              {{ (d.items || []).map((it: any) => it.poi_name).join(' → ') }}
            </div>
          </div>
          <div v-if="m.hotelOptions && m.hotelOptions.length" class="hotel-options-cta">
            <div class="hotel-options-cta-title">
              住宿备选方案（{{ m.hotelOptions.length }} 个，选择后才会应用）
            </div>
            <ul class="hotel-options-cta-list">
              <li v-for="option in m.hotelOptions" :key="option.id">
                {{ option.hotelName }} · {{ option.tier }}
                <span v-if="option.isCurrent">（当前）</span>
              </li>
            </ul>
            <el-button type="primary" size="small" @click="openHotelDialog(m, i)">
              查看并选择
            </el-button>
          </div>
        </div>
        <div v-if="nlLoading" class="chat-thinking">
          <el-icon class="is-loading"><Loading /></el-icon>
          {{ nlLoadingHint }}
        </div>
        </div>
        <div class="chat-input">
          <el-input
            v-model="nlInstruction"
            placeholder="想怎么改？例如：换个酒店档次 / 调整某天节奏 / 删掉或替换某个景点"
            @keyup.enter="onChatSend"
          />
          <el-button :loading="nlLoading" @click="onChatSend">发送</el-button>
          <el-button :disabled="!chatMsgs.length" @click="onClearChat">清空对话</el-button>
          <el-button type="primary" :disabled="!draftChanged || !draftPlans.length" :loading="applying" @click="onApply">
            应用到行程
          </el-button>
        </div>
        </div>
      </div>
    </el-card>

    <div v-if="detail" class="handbook-body">
      <section class="day-list">
        <details
          v-for="d in detail.dayList"
          :key="d.dayId"
          class="day-panel"
          :open="d.dayNo === openDayNo"
        >
          <summary @click="onSummaryClick(d.dayNo, $event)">
            <span class="day-idx">{{ String(d.dayNo).padStart(2, '0') }}</span>
            <span class="day-main">
              <span class="day-meta">第{{ d.dayNo }}天<template v-if="d.travelDate"> · {{ d.travelDate }}</template></span>
              <span class="day-title">{{ dayTitle(d) }}</span>
              <span class="day-count">{{ (d.items || []).length }} 个点位</span>
            </span>
            <span class="day-plus" aria-hidden="true">＋</span>
          </summary>
          <div class="day-content">
            <div v-if="d.theme || d.practicalNotes?.length || d.backupPlan?.length" class="day-note">
              <strong v-if="d.theme">{{ d.theme }}</strong>
              <span v-if="d.practicalNotes?.length">{{ d.practicalNotes.join('；') }}</span>
              <span v-if="d.backupPlan?.length">备选：{{ d.backupPlan.map((p) => String(p.name || p.title || '备用安排')).join('、') }}</span>
            </div>
            <div class="route-toolbar">
              <el-button type="primary" size="small" :disabled="!mapReady" @click="openAddDialog(d)">添加景点</el-button>
            </div>
            <draggable
              :list="d.items"
              item-key="id"
              handle=".drag-handle"
              :animation="150"
              @end="onDragEnd(d)"
            >
              <template #item="{ element, index }">
                <div
                  :id="`item-${element.id}`"
                  class="route-row"
                  :class="{ highlighted: element.id === highlightId }"
                  role="button"
                  tabindex="0"
                  :aria-label="`行程点位：${element.poiName}`"
                  @click="onItemClick(element)"
                  @keydown.enter.prevent="onItemClick(element)"
                >
                  <div class="row-img">
                    <img
                      v-if="imgLevel(element) < 2 && imgSrc(element) && (element.itemType === 'attraction' || element.itemType === 'food' || element.image || element.imageUrl || (element.longitude && element.latitude))"
                      :src="imgSrc(element)"
                      :alt="element.poiName"
                      loading="lazy"
                      @error="onImgError(element)"
                    />
                    <div v-else class="row-img-fallback">{{ typeLabel(element.itemType) }}</div>
                  </div>
                  <span class="row-no">
                    <el-icon
                      class="drag-handle"
                      role="button"
                      tabindex="0"
                      aria-label="拖拽调整顺序"
                      title="拖拽调整顺序"
                    ><Rank /></el-icon>
                    <i class="row-idx">{{ String(index + 1).padStart(2, '0') }}</i>
                  </span>
                  <div class="row-main">
                    <div class="row-top">
                      <span class="row-name">{{ element.poiName }}</span>
                      <el-tag :type="tagType(element.itemType)" size="small">
                        {{ typeLabel(element.itemType) }}
                      </el-tag>
                      <span v-if="element.startTime" class="row-time">
                        {{ element.startTime }}<template v-if="element.endTime"> - {{ element.endTime }}</template>
                      </span>
                      <span v-if="element.durationMin" class="row-dwell">约 {{ element.durationMin }} 分钟</span>
                    </div>
                    <div
                      v-if="element.openTime || element.cost != null || element.tag || element.verificationStatus"
                      class="row-meta"
                    >
                      <span v-if="element.openTime">开放 {{ element.openTime }}</span>
                      <span v-if="element.cost != null">
                        ￥{{ element.cost }}{{ element.itemType === 'hotel' ? '/晚/间' : '/人' }}
                      </span>
                      <span v-if="element.tag">{{ element.tag }}</span>
                      <el-tag v-if="element.verificationStatus && element.verificationStatus !== 'verified'" size="small" type="warning">
                        {{ element.valueKind === 'estimated' ? '参考估算' : '待确认' }}
                      </el-tag>
                      <el-tag v-else-if="element.verificationStatus === 'verified'" size="small" type="success">
                        已核实
                      </el-tag>
                    </div>
                    <p v-if="element.source || element.sourceUpdatedAt" class="poi-source">
                      来源：{{ sourceLabel(element.source) }}<span v-if="element.sourceUpdatedAt"> · 更新于 {{ formatSourceDate(element.sourceUpdatedAt) }}</span>
                    </p>
                    <p
                      v-if="(element.intro || element.description)"
                      class="poi-desc"
                      :class="{ expanded: descExpanded[element.id!] }"
                    >
                      {{ element.intro || element.description }}
                    </p>
                    <el-button
                      v-if="(element.intro || element.description) && descLong(element)"
                      class="poi-desc-toggle"
                      link
                      type="primary"
                      size="small"
                      @click.stop="toggleDesc(element)"
                    >
                      {{ descExpanded[element.id!] ? '收起' : '展开全部' }}
                    </el-button>
                    <p v-if="element.remark" class="poi-remark">{{ element.remark }}</p>
                    <div v-if="nearbyPanels[String(element.id)]?.open" class="nearby-panel">
                      <p class="nearby-title">
                        <span>附近推荐</span>
                        <span class="nearby-sub">来自知识库的真实近邻</span>
                      </p>
                      <p v-if="nearbyPanels[String(element.id)]?.loading" class="nearby-loading">
                        正在查找附近…
                      </p>
                      <ul
                        v-else-if="nearbyPanels[String(element.id)]?.items.length"
                        class="nearby-list"
                      >
                        <li v-for="poi in nearbyPanels[String(element.id)]!.items" :key="poi.name">
                          <a :href="amapSearchLink(poi.name)" target="_blank" rel="noopener">
                            {{ poi.name }}
                          </a>
                          <span class="nearby-meta">
                            {{ typeLabel(poi.category) }}
                            <template v-if="poi.rating != null"> · {{ poi.rating }} 分</template>
                            <template v-if="poi.distanceM != null"> · 距此 {{ formatDistance(poi.distanceM) }}</template>
                          </span>
                        </li>
                      </ul>
                      <p v-else class="nearby-empty">知识库中暂无该地点附近的推荐</p>
                    </div>
                  </div>
                  <div class="row-side">
                    <a class="row-map" :href="amapLink(element)" target="_blank" rel="noopener">{{ mapLinkLabel }} ↗</a>
                    <el-button
                      v-if="element.itemType === 'attraction' || element.itemType === 'food'"
                      link
                      type="primary"
                      size="small"
                      @click.stop="toggleNearby(element)"
                    >
                      附近
                    </el-button>
                    <el-button link type="primary" size="small" @click.stop="openEditDialog(element)">
                      编辑
                    </el-button>
                    <el-button link type="danger" size="small" @click.stop="onDeleteItem(element)">
                      删除
                    </el-button>
                  </div>
                </div>
              </template>
            </draggable>
            <el-empty v-if="!(d.items || []).length" description="当天暂无安排" :image-size="80" />
          </div>
        </details>
      </section>

      <div class="side-col">
        <el-card shadow="never" class="map-card">
          <div class="map-toolbar">
            <span class="toolbar-title">当日路线</span>
            <el-tag v-if="!mapReady" type="warning" size="small">
              未配置地图 key，地图不可用
            </el-tag>
            <el-tag v-else-if="detailForeign && !mapHasCoords" type="info" size="small">
              海外目的地暂无坐标，地图已隐藏
            </el-tag>
          </div>
          <div v-if="detailForeign && !mapHasCoords" class="map-empty">
            <p class="map-empty-title">海外地图未启用</p>
            <p class="map-empty-desc">
              行程点位仍可浏览与编辑。配置服务端
              <code>GOOGLE_MAPS_API_KEY</code> 后可自动落海外坐标并恢复地图。
            </p>
          </div>
          <TripMap
            v-else
            class="map"
            :items="mapItems"
            :city="detail?.city"
            :highlight-id="highlightId"
            :route-day="routeDay"
            @select="onMapSelect"
          />
        </el-card>

        <el-card shadow="never" class="budget-card">
          <BudgetPanel
            :budget-list="detail.budgetList"
            :total-amount="detail.totalAmount"
            :budget-limit="detail.budget"
            :persons="detail.persons"
            :day-list="detail.dayList"
          />
        </el-card>
      </div>
    </div>

    <section v-if="detail" class="discover">
      <div class="discover-head">
        <div class="discover-heading">
          <h2 class="discover-title">发现更多</h2>
          <p class="discover-sub">来自本次规划候选池、未排入行程的备选点位，点击即可加入</p>
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

    <footer class="handbook-footer">
      <button type="button" class="back-top" @click="onBackTop">回到顶部</button>
    </footer>

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

    <el-dialog v-model="addDialogVisible" title="搜索添加景点" width="560px">
      <div class="search-bar">
        <el-input
          v-model="searchKeyword"
          placeholder="输入景点/餐饮关键字，如：故宫、烤鸭"
          clearable
          @keyup.enter="onSearch"
        />
        <el-button type="primary" :loading="searching" @click="onSearch">搜索</el-button>
      </div>
      <el-empty v-if="!searching && searchResults.length === 0 && searched" description="无结果" />
      <div v-for="poi in searchResults" :key="poi.id" class="poi-row">
        <div class="poi-main">
          <div class="poi-name">{{ poi.name }}</div>
          <div class="poi-addr">{{ poi.address || '—' }}</div>
        </div>
        <el-button type="primary" link @click="onAddPoi(poi)">添加</el-button>
      </div>
    </el-dialog>

    <el-dialog v-model="editDialogVisible" title="编辑行程项" width="420px">
      <el-form label-width="90px" size="default">
        <el-form-item label="开始时间">
          <el-time-picker v-model="editForm.startTime" format="HH:mm" style="width: 100%" />
        </el-form-item>
        <el-form-item label="时长(分钟)">
          <el-input-number v-model="editForm.durationMin" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="单人费用">
          <el-input-number v-model="editForm.cost" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="editForm.tag" placeholder="如：人文 / 网红 / 亲子" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSaveEdit">保存</el-button>
      </template>
    </el-dialog>

    <HotelOptionsDialog
      v-if="detail"
      v-model="hotelDialogVisible"
      :options="hotelDialogOptions"
      :selections="hotelDialogSelections"
      :message-id="hotelDialogMessageId"
      :base-revision="hotelDialogRevision"
      :itinerary-id="detail.id"
      @applied="onHotelApplied"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, Rank } from '@element-plus/icons-vue'
import draggable from 'vuedraggable'

import TripMap, { type MapItem } from '../components/TripMap.vue'
import TripCoverHeader from '../components/TripCoverHeader.vue'
import HotelOptionsDialog from '../components/HotelOptionsDialog.vue'
import BudgetPanel from '../components/BudgetPanel.vue'
import {
  addItem,
  createPdfExport,
  deleteItem,
  downloadExportFile,
  getExportTask,
  getItineraryDetail,
  reorderItems,
  searchPoi,
  updateItem,
  chatEditItinerary,
  applyPlans,
  getItineraryChatHistory,
  clearItineraryChatHistory,
  getNearbyPois,
  type HotelOption,
  type ItineraryChatMessage,
  type AmapPoi,
  type NearbyPoi,
} from '../api'
import type { DayPlan, ItineraryDetail, TripItem, TripSuggestion } from '../types/itinerary'
import { exportItineraryImage } from '../utils/exportImage'
import { renderMarkdown } from '../utils/markdown'
import { isForeignCity } from '../utils/geo'

const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const exportingPdf = ref(false)
const exportingImg = ref(false)
const nlInstruction = ref('')
const nlLoading = ref(false)
const nlLoadingHint = ref('正在理解需求并核对当前行程，请稍候…')
const nlOpen = ref(false)
const applying = ref(false)
const chatMsgs = ref<ItineraryChatMessage[]>([])
const draftChanged = ref(false)
const draftPlans = ref<any[]>([])
const hotelSelections = ref<Record<string, { roomTypeId: string; dayNos: number[] }>>({})
const hotelDialogVisible = ref(false)
const hotelDialogOptions = ref<HotelOption[]>([])
const hotelDialogMessageId = ref<number | undefined>()
const hotelDialogRevision = ref<string | undefined>()
const hotelDialogSelections = ref<Record<string, { roomTypeId: string; dayNos: number[] }>>({})
const detail = ref<ItineraryDetail | null>(null)
const selectionStorageKey = computed(() => `trip-hotel-selections:${String(route.params.id)}`)
const activeActionIndex = computed(() => {
  for (let i = chatMsgs.value.length - 1; i >= 0; i -= 1) {
    const message = chatMsgs.value[i]
    if (message.role === 'ai' && ((message.plans?.length || 0) > 0 || (message.hotelOptions?.length || 0) > 0)) {
      return i
    }
  }
  return -1
})
const expectedDateNights = computed(() => {
  if (!detail.value?.startDate || !detail.value?.endDate) return null
  const difference = new Date(detail.value.endDate).getTime() - new Date(detail.value.startDate).getTime()
  return Math.max(Math.round(difference / 86400000), 0)
})
const dateNightMismatch = computed(() => expectedDateNights.value != null
  && detail.value?.stayNights !== expectedDateNights.value)

watch(hotelSelections, (value) => {
  localStorage.setItem(selectionStorageKey.value, JSON.stringify(value))
}, { deep: true })

watch([chatMsgs, nlLoading], ([msgs, loading]) => {
  if (loading || msgs.length) nlOpen.value = true
}, { deep: true, immediate: false })

async function onChatSend() {
  const message = nlInstruction.value.trim()
  if (!message || nlLoading.value || !detail.value) return
  const history = chatMsgs.value.map((m) => ({ role: m.role, content: m.content }))
  chatMsgs.value.push({ role: 'user', content: message })
  nlInstruction.value = ''
  nlLoading.value = true
  nlLoadingHint.value = '正在理解需求并核对当前行程，请稍候…'
  const controller = new AbortController()
  // Agent 自身最多等待模型 60 秒，再为服务间返回预留 10 秒，避免页面无限转圈。
  const hintTimer = window.setTimeout(() => {
    nlLoadingHint.value = '正在生成结构化修改草稿，复杂行程可能需要几十秒…'
  }, 12000)
  const timeout = window.setTimeout(() => controller.abort(), 70000)
  try {
    const res = await chatEditItinerary(detail.value.id, message, history, controller.signal)
    const plans = (res.data.plans || []) as any[]
    const hotelOptions = res.data.hotelOptions || []
    if (plans.length || hotelOptions.length) {
      const replacedPending = activeActionIndex.value >= 0
      for (const previous of chatMsgs.value) {
        if (previous.role === 'ai') {
          previous.plans = []
          previous.hotelOptions = []
          previous.changed = false
        }
      }
      if (replacedPending) ElMessage.info('本轮建议已替代上一份未应用方案')
    }
    const aiMessage: ItineraryChatMessage = {
      id: res.data.messageId,
      role: 'ai',
      content: res.data.reply,
      plans,
      hotelOptions,
      changed: res.data.changed,
      baseRevision: res.data.baseRevision,
    }
    chatMsgs.value.push(aiMessage)
    prepareHotelOptions(aiMessage, chatMsgs.value.length - 1)
    draftPlans.value = plans
    draftChanged.value = res.data.changed
  } catch (err: any) {
    const aborted = err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError'
    const errorMessage = err?.response?.data?.message || err?.message
    chatMsgs.value.push({
      role: 'ai',
      content: aborted
        ? '### 本次处理超时\n\n行程没有被修改。请稍后重试，或把要求拆成更短的一步再发送。'
        : (errorMessage ? `处理失败：${errorMessage}` : '这条没太理解，换个说法试试？'),
    })
  } finally {
    clearTimeout(hintTimer)
    clearTimeout(timeout)
    nlLoading.value = false
  }
}

async function onClearChat() {
  if (!detail.value || !chatMsgs.value.length) return
  try {
    await ElMessageBox.confirm('确认清空当前行程的全部对话记录？行程本身不会受到影响。', '清空对话', {
      type: 'warning',
      confirmButtonText: '确认清空',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await clearItineraryChatHistory(detail.value.id)
  chatMsgs.value = []
  hotelSelections.value = {}
  localStorage.removeItem(selectionStorageKey.value)
  draftPlans.value = []
  draftChanged.value = false
  ElMessage.success('对话记录已清空')
}

function selectionKey(message: ItineraryChatMessage, index: number, option: HotelOption) {
  return `${message.id ?? `local-${index}`}:${option.id}`
}

function defaultSelection(option: HotelOption) {
  const defaultRoom = option.roomTypes.find((room) => room.isDefault) || option.roomTypes[0]
  const presetDays = option.requestedDayNos?.length === option.requestedNights
    ? [...option.requestedDayNos]
    : option.requestedNights === option.availableDayNos.length
      ? [...option.availableDayNos]
      : []
  return {
    roomTypeId: defaultRoom?.id || '',
    dayNos: presetDays,
  }
}

function prepareHotelOptions(message: ItineraryChatMessage, index: number) {
  for (const option of message.hotelOptions || []) {
    const key = selectionKey(message, index, option)
    if (hotelSelections.value[key]) continue
    hotelSelections.value[key] = defaultSelection(option)
  }
}

function openHotelDialog(message: ItineraryChatMessage, index: number) {
  const options = message.hotelOptions || []
  if (!options.length || !detail.value) return
  prepareHotelOptions(message, index)
  const map: Record<string, { roomTypeId: string; dayNos: number[] }> = {}
  for (const option of options) {
    const key = selectionKey(message, index, option)
    const source = hotelSelections.value[key] || defaultSelection(option)
    map[option.id] = { roomTypeId: source.roomTypeId, dayNos: [...source.dayNos] }
  }
  hotelDialogSelections.value = map
  hotelDialogOptions.value = options
  hotelDialogMessageId.value = message.id
  hotelDialogRevision.value = message.baseRevision
  hotelDialogVisible.value = true
}

function onHotelApplied(nextDetail: ItineraryDetail) {
  detail.value = nextDetail
  draftChanged.value = false
  const target = chatMsgs.value.find((m) => m.id === hotelDialogMessageId.value)
    ?? chatMsgs.value[activeActionIndex.value]
  if (target) target.hotelOptions = []
}

function draftChanges(message: ItineraryChatMessage) {
  if (!detail.value) return []
  const changes: string[] = []
  for (const plan of message.plans || []) {
    const currentDay = detail.value.dayList.find((day) => day.dayNo === plan.day_no)
    const currentItems = currentDay?.items || []
    const nextItems = plan.items || []
    const currentNames = currentItems.map((item) => item.poiName)
    const nextNames = nextItems.map((item: any) => item.poi_name)
    const removed = currentNames.filter((name) => !nextNames.includes(name))
    const added = nextNames.filter((name: string) => !currentNames.includes(name))
    if (removed.length) changes.push(`第${plan.day_no}天删除：${removed.join('、')}`)
    if (added.length) changes.push(`第${plan.day_no}天新增：${added.join('、')}`)
    if (!removed.length && !added.length && currentNames.join('|') !== nextNames.join('|')) {
      changes.push(`第${plan.day_no}天调整游览顺序`)
    }
    const timeChanged = nextItems.some((item: any) => {
      const current = currentItems.find((row) => row.poiName === item.poi_name)
      return current && (current.startTime || '') !== (item.start_time || '')
    })
    if (timeChanged) changes.push(`第${plan.day_no}天调整时间安排`)
  }
  return changes.length ? changes : ['计划内容已更新，请核对下方完整安排']
}

async function onApply() {
  if (!detail.value || !draftChanged.value || applying.value) return
  const actionMessage = chatMsgs.value[activeActionIndex.value]
  if (!actionMessage?.id) {
    ElMessage.warning('该草稿缺少确认信息，请重新生成')
    return
  }
  applying.value = true
  try {
    await applyPlans(detail.value.id, draftPlans.value, actionMessage.id, actionMessage.baseRevision)
    ElMessage.success('已应用到行程')
    actionMessage.plans = []
    draftChanged.value = false
    await loadDetail()
  } catch {
    // 错误提示已由拦截器处理
  } finally {
    applying.value = false
  }
}
let timer = 0
let pollFailures = 0

async function loadDetail() {
  loading.value = true
  try {
    const [res, historyRes] = await Promise.all([
      getItineraryDetail(route.params.id as string),
      getItineraryChatHistory(route.params.id as string),
    ])
    detail.value = res.data
    openDayNo.value = detail.value.dayList[0]?.dayNo ?? 1
    chatMsgs.value = historyRes.data || []
    try {
      hotelSelections.value = JSON.parse(localStorage.getItem(selectionStorageKey.value) || '{}')
    } catch {
      hotelSelections.value = {}
    }
    for (const [index, message] of chatMsgs.value.entries()) {
      prepareHotelOptions(message, index)
    }
    const actionMessage = chatMsgs.value[activeActionIndex.value]
    draftPlans.value = actionMessage?.plans || []
    draftChanged.value = !!actionMessage?.changed
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
  pollFailures = 0
  timer = window.setInterval(async () => {
    try {
      const res = await getItineraryDetail(route.params.id as string)
      pollFailures = 0
      detail.value = res.data
      if (detail.value.status !== 1) {
        stopPolling()
        ElMessage[detail.value.status === 2 ? 'success' : 'warning'](
          detail.value.status === 2 ? '行程生成完成' : '生成失败',
        )
      }
    } catch {
      // 持续失败（网络断/服务挂）时不能每 2.5s 无限重试：连续 5 次失败
      // 停止轮询并提示，用户刷新页面可恢复。
      pollFailures += 1
      if (pollFailures >= 5) {
        stopPolling()
        ElMessage.warning('无法获取行程进度，请检查网络后刷新页面')
      }
    }
  }, 2500)
}

function stopPolling() {
  if (timer) {
    window.clearInterval(timer)
    timer = 0
  }
}

const highlightId = ref<number | null>(null)
const doneDays = computed(
  () => (detail.value?.dayList || []).filter((d) => (d.items || []).length > 0).length,
)
const routeDay = ref(1)
const amapReady = ref(!!import.meta.env.VITE_AMAP_JS_KEY)
// 国外目的地：有坐标才渲染 Leaflet+OSM；无坐标时隐藏地图（避免空图误导）。
const detailForeign = computed(() => isForeignCity(detail.value?.city ?? ''))
const mapReady = computed(() => amapReady.value || detailForeign.value)
const mapHasCoords = computed(() =>
  (mapItems.value || []).some((it) => it.latitude != null && it.longitude != null),
)

// 景点介绍长文本展开/收起
const descExpanded = ref<Record<number, boolean>>({})

function toggleDesc(item: TripItem) {
  const id = item.id!
  descExpanded.value[id] = !descExpanded.value[id]
}

function descLong(item: TripItem) {
  return (item.intro || item.description || '').length > 60
}

// 管家讲解：把历史数据里字面的 "\n" 还原为真实换行
const butlerNote = computed(() => (detail.value?.planNote || '').replace(/\\n/g, '\n'))

const activeDay = computed(
  () => detail.value?.dayList.find((d) => d.dayNo === routeDay.value) ?? detail.value?.dayList[0],
)

const openDayNo = ref<number | null>(null)

function onSummaryClick(dayNo: number, event: MouseEvent) {
  // 手风琴：拦截 summary 原生 toggle，展开态由 openDayNo 单一受控，避免多天同时展开
  event.preventDefault()
  openDayNo.value = openDayNo.value === dayNo ? null : dayNo
  routeDay.value = dayNo
}

// 图片降级等级：0=实景图(行程自带/后端检索) → 1=地图位置图(保底) → 2=占位块
const imgFailed = ref<Record<number, number>>({})

function imgLevel(item: TripItem) {
  return imgFailed.value[item.id!] ?? 0
}

function imgSrc(item: TripItem) {
  const foreign = detailForeign.value
  if (imgLevel(item) >= 1) {
    // 保底：高德静态地图位置图（国内有 key 时）
    if (item.longitude && item.latitude && amapReady.value && !foreign) {
      return `/api/amap/staticmap?location=${item.longitude},${item.latitude}`
    }
    return imageProxy(item.image || item.imageUrl || '')
  }
  // 实景图：行程自带 → 同源代理
  const own = imageProxy(item.image || item.imageUrl || '')
  if (own) return own
  // 海外：Unsplash（skipAmap），避免高德无覆盖超时
  if (foreign) {
    return `/api/amap/poi-photo?name=${encodeURIComponent(item.poiName)}&city=${encodeURIComponent(detail.value?.city ?? '')}&skipAmap=true`
  }
  if (amapReady.value) {
    return `/api/amap/poi-photo?name=${encodeURIComponent(item.poiName)}&city=${encodeURIComponent(detail.value?.city ?? '')}`
  }
  if (item.longitude && item.latitude) {
    return `/api/amap/staticmap?location=${item.longitude},${item.latitude}`
  }
  return ''
}

function imageProxy(url: string) {
  if (!url) return ''
  if (url.startsWith('/') || url.startsWith('data:') || url.startsWith('blob:')) return url
  if (!/^https?:\/\//i.test(url)) return ''
  return `/api/amap/image?url=${encodeURIComponent(url)}`
}

function onImgError(item: TripItem) {
  const id = item.id!
  // 没有坐标且没有另一张图片时，/poi-photo 的 404 无法再降级到地图，
  // 直接显示占位块，避免空 src 触发重复请求。
  const hasFallback = Boolean(item.longitude && item.latitude)
  imgFailed.value[id] = hasFallback ? (imgFailed.value[id] ?? 0) + 1 : 2
}

function dayTitle(d: DayPlan) {
  if (d.theme) return d.theme
  const items = d.items || []
  if (!items.length) return '暂无安排'
  const first = items[0]?.poiName || ''
  const last = items.length > 1 ? items[items.length - 1]?.poiName || '' : ''
  return last && last !== first ? `${first} → ${last}` : first
}

function amapLink(item: TripItem) {
  // 海外与后端一致走 Google Maps：有真实坐标优先按坐标打开，否则按名称检索
  if (detailForeign.value) {
    if (item.latitude != null && item.longitude != null) {
      return `https://www.google.com/maps/search/?api=1&query=${item.latitude},${item.longitude}`
    }
    const keyword = `${detail.value?.city ?? ''}${item.poiName}`
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(keyword)}`
  }
  const keyword = `${detail.value?.city ?? ''}${item.poiName}`
  return `https://uri.amap.com/search?keyword=${encodeURIComponent(keyword)}`
}

const mapLinkLabel = computed(() => (detailForeign.value ? '谷歌地图' : '高德地图'))

// ---------- 附近推荐（轻量 GraphRAG：权威知识库真实近邻） ----------

interface NearbyPanel {
  open: boolean
  loading: boolean
  loaded: boolean
  items: NearbyPoi[]
}

const nearbyPanels = reactive<Record<string, NearbyPanel>>({})

async function toggleNearby(item: TripItem) {
  const key = String(item.id)
  const panel = nearbyPanels[key]
  if (panel?.open) {
    panel.open = false
    return
  }
  if (!panel) {
    nearbyPanels[key] = { open: true, loading: true, loaded: false, items: [] }
  } else {
    panel.open = true
  }
  const current = nearbyPanels[key]
  if (current.loaded) return
  current.loading = true
  try {
    // 优先传行程项自带的真实坐标（开放模式项经高德落点），
    // 名称解析不到知识库条目时仍能按坐标查真实近邻。
    const res = await getNearbyPois({
      city: detail.value?.city ?? '',
      name: item.poiName,
      latitude: item.latitude ?? undefined,
      longitude: item.longitude ?? undefined,
      limit: 5,
    })
    current.items = res.data?.items ?? []
  } catch {
    current.items = []
    ElMessage.warning('附近推荐获取失败，请稍后重试')
  } finally {
    current.loading = false
    current.loaded = true
  }
}

function formatDistance(meters: number | null) {
  if (meters == null) return ''
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)}km` : `${meters}m`
}

function amapSearchLink(name: string) {
  const keyword = `${detail.value?.city ?? ''}${name}`
  if (detailForeign.value) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(keyword)}`
  }
  return `https://uri.amap.com/search?keyword=${encodeURIComponent(keyword)}`
}

function onBackTop() {
  const main = document.querySelector('.el-main')
  if (main) main.scrollTo({ top: 0, behavior: 'smooth' })
  else window.scrollTo({ top: 0, behavior: 'smooth' })
}

const TYPE_LABEL: Record<string, string> = {
  attraction: '景点',
  food: '美食',
  hotel: '酒店',
  transport: '交通',
}

const TYPE_TAG: Record<string, string> = {
  attraction: 'primary',
  food: 'warning',
  hotel: 'success',
  transport: 'info',
}

const mapItems = computed<MapItem[]>(() => {
  if (!detail.value) return []
  return (activeDay.value ? [activeDay.value] : detail.value.dayList).flatMap((day) =>
    day.items.map((it) => ({ ...it, dayNo: day.dayNo }))
  )
})

function typeLabel(type: string) {
  return TYPE_LABEL[type] || type
}

function tagType(type: string) {
  return (TYPE_TAG[type] || 'info') as 'primary' | 'warning' | 'success' | 'info'
}

function destinationStatusLabel(status?: ItineraryDetail['destinationStatus']) {
  if (status === 'researched') return '外部研究'
  if (status === 'draft_only') return '探索草案'
  return '知识库支持'
}

function qualityStatusLabel(status?: ItineraryDetail['qualityStatus']) {
  if (status === 'READY') return '已通过质量检查'
  if (status === 'READY_WITH_WARNINGS') return '可用，但需注意提示'
  if (status === 'STALE') return '信息已过期'
  if (status === 'BLOCKED') return '质量检查未通过'
  return '草稿'
}

function qualityTagType(status?: ItineraryDetail['qualityStatus']) {
  if (status === 'READY') return 'success'
  if (status === 'BLOCKED') return 'danger'
  if (status === 'STALE') return 'danger'
  return 'warning'
}

function sourceLabel(source?: string | null) {
  if (!source) return '待补充'
  if (source === 'mysql.poi_knowledge') return '目的地知识库'
  if (source === 'llm.open_day') return '开放研究（需复核）'
  if (source === 'amap-grounding' || source === 'amap') return '高德地图'
  return source
}

function formatSourceDate(value?: string | null) {
  if (!value) return ''
  return value.replace('T', ' ').replace(/([+-]\d{2}:?\d{2}|Z)$/, '').slice(0, 16)
}

function onItemClick(item: TripItem) {
  highlightId.value = item.id ?? null
}

function onMapSelect(id: number | null) {
  highlightId.value = id
  if (id != null) {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    document.getElementById(`item-${id}`)?.scrollIntoView({
      behavior: reduceMotion ? 'auto' : 'smooth',
      block: 'center',
    })
  }
}

async function onDragEnd(day: DayPlan) {
  const itemIds = day.items.map((it) => it.id).filter((id): id is number => id != null)
  const res = await reorderItems(detail.value!.id, day.dayId, itemIds)
  detail.value = res.data
}

async function onDeleteItem(item: TripItem) {
  await ElMessageBox.confirm(`确认删除「${item.poiName}」？`, '删除确认', { type: 'warning' })
  const res = await deleteItem(item.id!)
  detail.value = res.data
  ElMessage.success('已删除')
}

const addDialogVisible = ref(false)
const searchKeyword = ref('')
const searching = ref(false)
const searched = ref(false)
const searchResults = ref<AmapPoi[]>([])
const addDayId = ref<number | null>(null)

function openAddDialog(day: DayPlan) {
  addDayId.value = day.dayId
  searchKeyword.value = ''
  searchResults.value = []
  searched.value = false
  addDialogVisible.value = true
}

async function onSearch() {
  if (!searchKeyword.value.trim()) return
  searching.value = true
  try {
    const res = await searchPoi(searchKeyword.value.trim(), detail.value?.city)
    searchResults.value = res.data
    searched.value = true
  } finally {
    searching.value = false
  }
}

async function onAddPoi(poi: AmapPoi) {
  if (addDayId.value == null) return
  const res = await addItem(detail.value!.id, {
    dayId: addDayId.value,
    itemType: 'attraction',
    poiName: poi.name,
    poiId: poi.id,
    address: poi.address || undefined,
    latitude: poi.latitude ?? undefined,
    longitude: poi.longitude ?? undefined,
  })
  detail.value = res.data
  ElMessage.success(`已添加「${poi.name}」`)
  addDialogVisible.value = false
}

/* ---------- 发现更多：备选池（生成时未排入行程的候选点位） ---------- */
/* 分类页签：无「全部」页签，默认选中第一个分类，避免不同类别的过滤混在一起 */
const DISCOVER_TABS = [
  { key: 'attraction', label: '景点' },
  { key: 'activity', label: '体验·游玩' },
  { key: 'food', label: '美食' },
  { key: 'hotel', label: '酒店' },
  { key: 'souvenir', label: '伴手礼' },
] as const

type DiscoverCategoryKey = (typeof DISCOVER_TABS)[number]['key']

const CATEGORY_LABELS: Record<string, string> = {
  attraction: '景点',
  activity: '体验·游玩',
  food: '美食',
  hotel: '酒店',
  souvenir: '伴手礼',
}

function categoryLabel(key: string) {
  return CATEGORY_LABELS[key] ?? '景点'
}

const discoverTab = ref<DiscoverCategoryKey>('attraction')
const discoverImgFailed = ref<Record<string, boolean>>({})
const discoverAddVisible = ref(false)
const discoverSuggestion = ref<TripSuggestion | null>(null)
const discoverDayId = ref<number | null>(null)

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
  if (detailForeign.value) {
    return `/api/amap/poi-photo?name=${encodeURIComponent(s.name)}&city=${encodeURIComponent(city)}&skipAmap=true`
  }
  return `/api/amap/poi-photo?name=${encodeURIComponent(s.name)}&city=${encodeURIComponent(city)}`
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
  const res = await addItem(detail.value!.id, {
    dayId: discoverDayId.value,
    itemType,
    poiName: s.name,
    poiId: s.poiId || undefined,
    address,
    latitude,
    longitude,
    cost: s.estimatedCost ?? undefined,
  })
  detail.value = res.data
  ElMessage.success(
    s.needReservation
      ? `已将「${s.name}」加入行程，该地点通常需要提前预约`
      : `已将「${s.name}」加入行程`
  )
  discoverAddVisible.value = false
}

const editDialogVisible = ref(false)
const editTarget = ref<TripItem | null>(null)
const editForm = ref({
  startTime: null as string | null,
  durationMin: null as number | null,
  cost: null as number | null,
  tag: '',
  remark: '',
})

function openEditDialog(item: TripItem) {
  editTarget.value = item
  editForm.value = {
    startTime: item.startTime || null,
    durationMin: item.durationMin ?? null,
    cost: item.cost ?? null,
    tag: item.tag || '',
    remark: item.remark || '',
  }
  editDialogVisible.value = true
}

async function onSaveEdit() {
  if (!editTarget.value) return
  saving.value = true
  try {
    const res = await updateItem(editTarget.value.id!, {
      // PUT 接口按完整地点信息更新；一并带回不可见字段，避免编辑时间后丢失地图坐标。
      itemType: editTarget.value.itemType,
      poiName: editTarget.value.poiName,
      poiId: editTarget.value.poiId,
      address: editTarget.value.address,
      latitude: editTarget.value.latitude,
      longitude: editTarget.value.longitude,
      startTime: editForm.value.startTime || undefined,
      endTime: editTarget.value.endTime,
      durationMin: editForm.value.durationMin ?? undefined,
      cost: editForm.value.cost ?? undefined,
      tag: editForm.value.tag || undefined,
      remark: editForm.value.remark || undefined,
    })
    detail.value = res.data
    editDialogVisible.value = false
    ElMessage.success('已保存')
  } finally {
    saving.value = false
  }
}

async function onExportImage() {
  if (!detail.value) return
  exportingImg.value = true
  try {
    exportItineraryImage(detail.value)
    ElMessage.success('图片已导出')
  } finally {
    exportingImg.value = false
  }
}

async function onExportPdf() {
  if (!detail.value) return
  exportingPdf.value = true
  try {
    const res = await createPdfExport(detail.value.id)
    const taskId = res.data.id
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 1500))
      const task = await getExportTask(taskId)
      if (task.data.status === 'DONE') {
        const blob = await downloadExportFile(taskId)
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${detail.value!.title}.pdf`
        a.click()
        URL.revokeObjectURL(url)
        ElMessage.success('PDF 导出完成')
        return
      }
      if (task.data.status === 'FAILED') {
        ElMessage.error(task.data.errorMsg || 'PDF 导出失败')
        return
      }
    }
    ElMessage.error('导出超时，请稍后在任务列表重试')
  } catch (e) {
    // 拦截器已提示
  } finally {
    exportingPdf.value = false
  }
}

onMounted(async () => {
  await loadDetail()
  if (detail.value && detail.value.status === 1) startPolling()
})

// 浏览器前进/后退在同一路由 /trips/:id 间切换时组件被复用，仅靠 onMounted
// 不会重新加载，界面会停留在旧行程。监听 id 变化重载并重启轮询。
watch(
  () => route.params.id,
  async (id, prev) => {
    if (!id || id === prev) return
    stopPolling()
    await loadDetail()
    if (detail.value && detail.value.status === 1) startPolling()
  },
)

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.trip-detail {
  margin: 0 auto;
}

/* ---------- 阅读进度条（el-main 命名滚动时间轴驱动） ---------- */
.reading-progress {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 3px;
  z-index: 2000;
  pointer-events: none;
}

@supports (animation-timeline: scroll()) {
  .reading-progress {
    background: linear-gradient(90deg, var(--lp-accent), var(--lp-accent-warm));
    transform-origin: 0 50%;
    transform: scaleX(0);
    animation: lp-reading-grow linear both;
    animation-timeline: --lp-page-scroll;
  }
}

@keyframes lp-reading-grow {
  to {
    transform: scaleX(1);
  }
}

/* ---------- 封面样式已抽至 TripCoverHeader ---------- */

.head {
  margin-bottom: 16px;
}

.gen-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px 14px;
  border: 1px solid var(--lp-border);
  border-left: 4px solid var(--lp-accent);
  border-radius: 8px;
  background: var(--lp-sand);
  font-weight: 600;
}

.gen-banner.error {
  border-left-color: var(--lp-danger);
  background: var(--el-color-danger-light-9);
}

.butler-strip {
  margin-bottom: 16px;
  padding: 12px 16px;
  border-left: 3px solid var(--lp-accent-warm);
  border-radius: 0 8px 8px 0;
  background: var(--lp-paper);
}

.butler-head {
  font-weight: 800;
  margin-bottom: 6px;
  color: var(--lp-ink);
  font-size: 13px;
  letter-spacing: 0.04em;
}

.butler-text {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.75;
  color: var(--lp-ink-soft);
  font-size: 14px;
}

.head-info p {
  margin: 4px 0;
  color: var(--el-text-color-secondary);
}

/* ---------- 元信息胶囊（偏好） ---------- */
.meta-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.meta-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--lp-sand);
  border: 1px solid var(--lp-border);
  font-size: 12.5px;
  font-weight: 600;
  color: var(--lp-ink-soft);
  font-variant-numeric: tabular-nums;
}

.mismatch-line {
  margin: 10px 0 0;
}

.nl-edit {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px dashed var(--lp-border);
}

.nl-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-height: 44px;
  padding: 10px 14px;
  border: 1px solid var(--lp-border);
  border-radius: 12px;
  background: var(--lp-sand);
  color: var(--lp-ink);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}

.nl-toggle:hover {
  border-color: var(--lp-accent);
  background: var(--lp-accent-soft);
}

.nl-toggle-hint {
  font-size: 12px;
  font-weight: 500;
  color: var(--lp-muted);
}

.nl-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.chat-scroll {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 360px;
  overflow-y: auto;
  padding-right: 6px;
}

.chat-line {
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 14px;
  max-width: 92%;
}

.chat-line.user {
  background: var(--lp-ink);
  color: #fff;
  margin-left: auto;
  width: fit-content;
}

.chat-line.ai {
  background: var(--lp-sand);
  border: 1px solid var(--lp-border);
  width: fit-content;
}

.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 10px 0 6px;
  color: var(--lp-ink);
  line-height: 1.35;
}

.markdown-body :deep(h3) {
  font-size: 16px;
}

.markdown-body :deep(p) {
  margin: 5px 0;
  line-height: 1.7;
}

.markdown-body :deep(ul) {
  margin: 6px 0;
  padding-left: 22px;
}

.markdown-body :deep(li) {
  margin: 4px 0;
  line-height: 1.65;
}

.markdown-body :deep(code) {
  padding: 1px 5px;
  border-radius: 4px;
  background: rgb(0 0 0 / 6%);
}

.draft-preview {
  margin-top: 8px;
  padding: 8px 10px;
  background: #fff;
  border: 1px solid var(--lp-border);
  border-radius: 8px;
  font-size: 13px;
  color: var(--lp-ink-soft);
}

.draft-day {
  padding: 2px 0;
}

.chat-thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  margin: 8px 0;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--lp-sand);
  color: var(--lp-ink-soft);
  font-size: 13px;
}

.draft-summary-title {
  margin-bottom: 4px;
  font-weight: 700;
  color: var(--lp-ink);
}

.draft-change {
  margin-bottom: 3px;
  color: var(--lp-accent-hover);
}

/* 聊天内住宿备选：摘要卡片，详情走 Dialog */
.hotel-options-cta {
  margin-top: 10px;
  padding: 12px 14px;
  background: var(--lp-paper);
  border: 1px solid var(--lp-border);
  border-radius: 10px;
}

.hotel-options-cta-title {
  font-weight: 700;
  color: var(--lp-ink);
  font-size: 13px;
  margin-bottom: 6px;
}

.hotel-options-cta-list {
  margin: 0 0 10px;
  padding-left: 18px;
  color: var(--lp-ink-soft);
  font-size: 13px;
  line-height: 1.7;
}

.chat-input {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chat-input :deep(.el-input) {
  flex: 1 1 220px;
  min-width: 0;
}

/* ---------- 手册白底大区：左逐日轨道 + 右当日地图/预算 ---------- */
.handbook-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 440px;
  gap: 24px;
  align-items: start;
  background: #fff;
  border-radius: 16px;
  padding: 8px 32px 28px;
  margin-bottom: 16px;
}

.side-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

@media (max-width: 1024px) {
  .handbook-body {
    grid-template-columns: 1fr;
    padding: 8px 16px 24px;
  }
}

/* ---------- 逐日折叠面板 ---------- */
.day-panel summary {
  display: grid;
  grid-template-columns: 78px 1fr 34px;
  gap: 24px;
  align-items: center;
  padding: 26px 0 22px;
  border-bottom: 1px solid #d8dfda;
  cursor: pointer;
  list-style: none;
}

.day-panel summary::-webkit-details-marker {
  display: none;
}

.day-idx {
  font-family: var(--lp-font-display);
  font-style: italic;
  font-weight: 400;
  font-size: 36px;
  line-height: 1.1;
  color: var(--lp-accent-warm);
  font-variant-numeric: tabular-nums;
}

.day-meta {
  display: block;
  font-size: 12px;
  color: var(--lp-muted);
}

.day-title {
  display: block;
  margin: 6px 0 4px;
  font-family: var(--lp-font-display);
  font-weight: 500;
  font-size: 23px;
  line-height: 1.25;
  color: var(--lp-ink);
  letter-spacing: -0.01em;
}

.day-count {
  display: block;
  font-size: 13px;
  color: var(--lp-muted);
}

.day-plus {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid #c9d2cc;
  border-radius: 50%;
  font-size: 16px;
  color: var(--lp-ink-soft);
  transition: transform 0.25s ease;
}

.day-panel[open] .day-plus {
  transform: rotate(45deg);
}

.day-content {
  padding: 18px 0 8px;
}

.day-note {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin: 4px 0 12px;
  padding: 10px 14px;
  border-left: 3px solid var(--lp-accent-warm);
  border-radius: 0 8px 8px 0;
  background: var(--lp-paper);
  font-size: 12.5px;
  color: var(--lp-ink-soft);
  line-height: 1.75;
}

.day-note strong {
  color: var(--lp-ink);
}

.route-toolbar {
  display: flex;
  justify-content: flex-end;
  margin: 0 0 10px;
}

/* ---------- 站点轨道行 ---------- */
.route-row {
  display: grid;
  grid-template-columns: 104px 40px minmax(0, 1fr) auto;
  gap: 12px;
  padding: 14px 16px;
  margin-bottom: 10px;
  background: #fff;
  border: 1px solid var(--lp-border);
  border-radius: 12px;
  cursor: pointer;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}

.route-row:hover {
  border-color: var(--lp-accent);
}

.route-row:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: 2px;
}

.row-img {
  width: 104px;
  height: 72px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--lp-sand);
}

.row-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.row-img-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--lp-accent);
  font-weight: 700;
  font-size: 12px;
  letter-spacing: 0.08em;
}

@media (max-width: 640px) {
  .route-row {
    grid-template-columns: 72px 40px minmax(0, 1fr) auto;
  }

  .row-img {
    width: 72px;
    height: 54px;
  }
}

.route-row.highlighted {
  border-color: var(--lp-accent);
  box-shadow: 0 0 0 2px var(--lp-accent-soft);
}

.row-no {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding-top: 2px;
}

.row-idx {
  font-family: var(--lp-font-display);
  font-style: italic;
  font-size: 17px;
  color: var(--lp-accent-warm);
}

.drag-handle {
  cursor: grab;
  color: var(--el-text-color-placeholder);
  padding: 4px;
  border-radius: 6px;
}

.drag-handle:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: 1px;
  color: var(--lp-accent);
}

.row-main {
  min-width: 0;
}

.row-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.row-name {
  font-family: var(--lp-font-display);
  font-weight: 500;
  font-size: 16px;
  color: var(--lp-ink);
}

.row-time {
  font-size: 13px;
  font-weight: 700;
  color: var(--lp-ink-soft);
  font-variant-numeric: tabular-nums;
}

.row-dwell {
  font-size: 11px;
  color: var(--lp-muted);
}

.row-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-top: 6px;
  color: var(--lp-muted);
  font-size: 12px;
}

.poi-source {
  margin: 3px 0 0;
  color: var(--lp-muted);
  font-size: 11px;
  opacity: 0.85;
}

.poi-desc {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--lp-ink-soft);
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.poi-desc.expanded {
  display: block;
  -webkit-line-clamp: unset;
  line-clamp: unset;
  overflow: visible;
}

.poi-desc-toggle {
  height: auto;
  padding: 0;
  margin-top: 4px;
}

.poi-remark {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--lp-muted);
}

.nearby-panel {
  margin-top: 8px;
  padding: 8px 12px;
  border: 1px solid var(--lp-border);
  border-radius: 8px;
  background: var(--lp-sand);
}

.nearby-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--lp-ink);
}

.nearby-sub {
  font-weight: 400;
  color: var(--lp-muted);
}

.nearby-loading,
.nearby-empty {
  margin: 0;
  font-size: 12px;
  color: var(--lp-muted);
}

.nearby-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nearby-list li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
}

.nearby-list a {
  color: var(--lp-accent);
  text-decoration: none;
}

.nearby-list a:hover {
  color: var(--lp-accent-hover);
  text-decoration: underline;
}

.nearby-meta {
  color: var(--lp-muted);
}

.row-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: center;
  gap: 6px;
}

.row-side .el-button + .el-button {
  margin-left: 0;
}

.row-map {
  font-size: 11px;
  color: var(--lp-accent);
  text-decoration: none;
  border-bottom: 1px solid transparent;
}

.row-map:hover {
  border-bottom-color: var(--lp-accent);
}

/* ---------- 地图 / 预算 ---------- */
.map-card {
  margin-bottom: 0;
}

.map-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.toolbar-title {
  margin-right: 12px;
  font-weight: 700;
}

.map {
  height: 460px;
}

.map-empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 8px;
  min-height: 180px;
  padding: 20px 18px;
  border-radius: 12px;
  background: var(--lp-sand);
  border: 1px dashed var(--lp-border);
}

.map-empty-title {
  margin: 0;
  font-weight: 700;
  color: var(--lp-ink);
  font-size: 14px;
}

.map-empty-desc {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--lp-muted);
}

.map-empty-desc code {
  padding: 1px 5px;
  border-radius: 4px;
  background: rgb(0 0 0 / 6%);
  font-family: var(--lp-font-data);
  font-size: 12px;
}

.budget-card {
  margin-bottom: 0;
}

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

/* ---------- 回到顶部 ---------- */
.handbook-footer {
  text-align: center;
  padding: 8px 0 28px;
}

.back-top {
  background: none;
  border: none;
  cursor: pointer;
  font-family: var(--lp-font-display);
  font-style: italic;
  font-size: 14px;
  color: var(--lp-ink-soft);
  text-decoration: underline;
  text-underline-offset: 4px;
}

.back-top:hover {
  color: var(--lp-accent-warm);
}

/* ---------- 搜索添加对话框 ---------- */
.search-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.poi-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 4px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.poi-name {
  font-weight: 600;
}

.poi-addr {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
