<template>
  <div class="trip-detail" v-loading="loading">
    <el-card v-if="detail" shadow="never" class="head">
      <div
        v-if="detail.status === 3"
        class="gen-banner"
        style="border-left-color: #c0392b"
      >
        <span>❌ {{ detail.planNote || '行程生成失败，请重新生成' }}</span>
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
      <el-card v-if="detail.planNote" shadow="never" class="butler-card">
        <div class="butler-head">🧳 AI 管家说</div>
        <p class="butler-text">{{ butlerNote }}</p>
      </el-card>
      <div class="head-info">
        <h2>{{ detail.title }}</h2>
        <p>
          {{ detail.city }} · {{ detail.days }} 天 {{ detail.stayNights }} 晚 · {{ detail.persons }} 人
          <template v-if="detail.preferences"> · 偏好：{{ detail.preferences }}</template>
          <template v-if="detail.hotelTier"> · 住宿：{{ detail.hotelTier }}</template>
        </p>
        <p v-if="detail.startDate">
          日期：{{ detail.startDate }} ~ {{ detail.endDate }}
          <el-tag v-if="dateNightMismatch" type="warning" size="small" style="margin-left: 8px">
            日期通常对应 {{ expectedDateNights }} 晚，当前计划含 {{ detail.stayNights }} 晚
          </el-tag>
        </p>
      </div>
      <div class="head-actions">
        <el-button @click="$router.back()">返回</el-button>
        <el-button @click="$router.push('/generate')">新建相似行程</el-button>
        <el-button
          :loading="exportingPdf"
          @click="onExportPdf"
        >
          导出 PDF
        </el-button>
        <el-button :loading="exportingImg" @click="onExportImage">导出图片</el-button>
      </div>
      <div class="nl-edit">
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
          <div v-if="m.hotelOptions && m.hotelOptions.length" class="hotel-options">
            <div class="hotel-option-title">住宿备选方案（选择后才会应用）</div>
            <div v-for="option in m.hotelOptions" :key="option.id" class="hotel-option">
              <div class="hotel-option-main">
                <div class="hotel-option-name">
                  {{ option.hotelName }}
                  <el-tag size="small" type="success">{{ option.tier }}</el-tag>
                  <el-tag v-if="selectedRoom(m, i, option)?.withinBudget" size="small" type="info">预算内</el-tag>
                  <el-tag v-else size="small" type="danger">预计超出总预算</el-tag>
                  <el-tag v-if="option.isCurrent" size="small">当前酒店</el-tag>
                </div>
                <div class="hotel-option-config">
                  <span>房型</span>
                  <el-select v-model="hotelSelections[selectionKey(m, i, option)].roomTypeId" size="small" style="width: 230px">
                    <el-option
                      v-for="room in option.roomTypes"
                      :key="room.id"
                      :label="`${room.roomName}（￥${room.nightlyPrice}/晚）`"
                      :value="room.id"
                    />
                  </el-select>
                  <template v-if="requiresDaySelection(option)">
                    <span>入住晚次（请选择 {{ option.requestedNights }} 晚）</span>
                    <el-checkbox-group
                      v-model="hotelSelections[selectionKey(m, i, option)].dayNos"
                      :max="option.requestedNights"
                      size="small"
                    >
                      <el-checkbox-button v-for="dayNo in option.availableDayNos" :key="dayNo" :label="dayNo">
                        第{{ dayNo }}晚
                      </el-checkbox-button>
                    </el-checkbox-group>
                  </template>
                  <template v-else>
                    <span>入住晚次</span>
                    <strong>{{ stayScopeLabel(option) }}</strong>
                  </template>
                </div>
                <div class="hotel-option-meta">
                  <template v-if="hasVariableNightlyPrice(m, i, option)">
                    各晚价格按入住日期计算，{{ option.requestedNights }} 晚 × {{ selectedRoom(m, i, option)?.rooms }} 间
                  </template>
                  <template v-else>
                    ￥{{ selectedRoom(m, i, option)?.nightlyPrice }}/晚 × {{ option.requestedNights }} 晚 × {{ selectedRoom(m, i, option)?.rooms }} 间
                  </template>
                  = ￥{{ selectedRoom(m, i, option)?.totalPrice }}
                  <span v-if="selectedRoom(m, i, option)?.priceDelta != null">
                    （{{ (selectedRoom(m, i, option)?.priceDelta || 0) >= 0 ? '+' : '' }}￥{{ selectedRoom(m, i, option)?.priceDelta }}）
                  </span>
                </div>
                <div class="hotel-option-reason">
                  {{ selectedRoom(m, i, option)?.description }}；床型：{{ selectedRoom(m, i, option)?.bedType || '以酒店确认为准' }}；
                  早餐：{{ selectedRoom(m, i, option)?.breakfast || '以酒店确认为准' }}
                </div>
                <div class="hotel-option-reason">{{ option.reason }}</div>
                <div v-if="option.budgetCapacity != null" class="hotel-option-reason">
                  当前总预算可用于住宿约 ￥{{ option.budgetCapacity }}
                  <span v-if="(selectedRoom(m, i, option)?.budgetOverage || 0) > 0">
                    ，替换后预计超出约 ￥{{ selectedRoom(m, i, option)?.budgetOverage }}
                  </span>
                </div>
                <div class="hotel-option-price-note">房价为所选入住日期的估算参考，实际以酒店实时库存和价格方案为准。</div>
              </div>
              <el-button type="primary" size="small" :disabled="!canChooseHotel(m, i, option)" :loading="applying" @click="onChooseHotel(m, i, option)">
                选择此方案
              </el-button>
            </div>
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
          <el-button type="primary" :disabled="!draftChanged" :loading="applying" @click="onApply">
            应用到行程
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 日期 Tab 分页 -->
    <el-card v-if="detail" shadow="never" class="day-tabs-card">
      <div class="day-tabs">
        <button
          v-for="d in detail.dayList"
          :key="d.dayId"
          type="button"
          class="day-tab"
          :class="{ active: routeDay === d.dayNo }"
          @click="routeDay = d.dayNo"
        >
          <span class="day-tab-title">DAY {{ d.dayNo }}</span>
          <span class="day-tab-date">{{ d.travelDate || '' }}</span>
          <span class="day-tab-n">{{ (d.items || []).length }} 个点位</span>
        </button>
      </div>
    </el-card>

    <el-row v-if="detail" :gutter="16">
      <el-col :span="14">
        <el-card shadow="never" class="timeline-card">
          <template #header>
            <div class="timeline-head">
              <span class="toolbar-title">第 {{ routeDay }} 天安排</span>
              <el-button
                type="primary"
                size="small"
                :disabled="!amapReady"
                @click="openAddDialog"
              >
                添加景点
              </el-button>
            </div>
          </template>

          <draggable
            :list="activeDayItems"
            item-key="id"
            handle=".drag-handle"
            :animation="150"
            @end="onDragEnd(activeDay!)"
          >
            <template #item="{ element }">
              <div
                :id="`item-${element.id}`"
                class="poi-card"
                :class="{ highlighted: element.id === highlightId }"
                @click="onItemClick(element)"
              >
                <div class="poi-img">
                  <img
                    v-if="element.longitude && element.latitude && imgLevel(element) < 2"
                    :src="imgSrc(element)"
                    :alt="element.poiName"
                    loading="lazy"
                    @error="onImgError(element)"
                  />
                  <div v-else class="poi-img-fallback">{{ typeLabel(element.itemType) }}</div>
                </div>
                <div class="poi-body">
                  <div class="poi-top">
                    <el-icon class="drag-handle"><Rank /></el-icon>
                    <span class="poi-name">{{ element.poiName }}</span>
                    <el-tag :type="tagType(element.itemType)" size="small">
                      {{ typeLabel(element.itemType) }}
                    </el-tag>
                    <span v-if="element.startTime" class="poi-time">
                      {{ element.startTime }}<template v-if="element.endTime"> - {{ element.endTime }}</template>
                    </span>
                  </div>
                  <div class="poi-meta">
                    <span v-if="element.durationMin">约 {{ element.durationMin }} 分钟</span>
                    <span v-if="element.cost != null">
                      ￥{{ element.cost }}{{ element.itemType === 'hotel' ? '/晚/间' : '/人' }}
                    </span>
                    <span v-if="element.tag">{{ element.tag }}</span>
                  </div>
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
                </div>
                <div class="poi-actions">
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
          <el-empty
            v-if="!activeDayItems.length"
            description="当天暂无安排"
            :image-size="80"
          />
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card shadow="never" class="map-card">
          <div class="map-toolbar">
            <span class="toolbar-title">当日路线</span>
            <el-tag v-if="!amapReady" type="warning" size="small">
              未配置高德 JS key，地图不可用
            </el-tag>
          </div>
          <TripMap
            class="map"
            :items="mapItems"
            :highlight-id="highlightId"
            :route-day="routeDay"
            @select="onMapSelect"
          />
        </el-card>
      </el-col>
    </el-row>

    <el-card v-if="detail" shadow="never" class="budget-card">
      <BudgetPanel
        :budget-list="detail.budgetList"
        :total-amount="detail.totalAmount"
        :budget-limit="detail.budget"
        :persons="detail.persons"
        :day-list="detail.dayList"
      />
    </el-card>

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
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, Rank } from '@element-plus/icons-vue'
import draggable from 'vuedraggable'

import TripMap, { type MapItem } from '../components/TripMap.vue'
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
  applyHotelOption,
  getItineraryChatHistory,
  clearItineraryChatHistory,
  type HotelOption,
  type ItineraryChatMessage,
  type AmapPoi,
} from '../api'
import type { DayPlan, ItineraryDetail, TripItem } from '../types/itinerary'
import { exportItineraryImage } from '../utils/exportImage'
import { renderMarkdown } from '../utils/markdown'

const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const exportingPdf = ref(false)
const exportingImg = ref(false)
const nlInstruction = ref('')
const nlLoading = ref(false)
const nlLoadingHint = ref('正在理解需求并核对当前行程，请稍候…')
const applying = ref(false)
const chatMsgs = ref<ItineraryChatMessage[]>([])
const draftChanged = ref(false)
const draftPlans = ref<any[]>([])
const hotelSelections = ref<Record<string, { roomTypeId: string; dayNos: number[] }>>({})
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

function prepareHotelOptions(message: ItineraryChatMessage, index: number) {
  for (const option of message.hotelOptions || []) {
    const key = selectionKey(message, index, option)
    if (hotelSelections.value[key]) continue
    const defaultRoom = option.roomTypes.find((room) => room.isDefault) || option.roomTypes[0]
    const presetDays = option.requestedDayNos?.length === option.requestedNights
      ? [...option.requestedDayNos]
      : option.requestedNights === option.availableDayNos.length
        ? [...option.availableDayNos]
        : []
    hotelSelections.value[key] = {
      roomTypeId: defaultRoom?.id || '',
      dayNos: presetDays,
    }
  }
}

function selectedRoom(message: ItineraryChatMessage, index: number, option: HotelOption) {
  const selection = hotelSelections.value[selectionKey(message, index, option)]
  return option.roomTypes.find((room) => room.id === selection?.roomTypeId) || option.roomTypes[0]
}

function hasVariableNightlyPrice(message: ItineraryChatMessage, index: number, option: HotelOption) {
  const prices = selectedRoom(message, index, option)?.nightlyBreakdown?.map((row) => row.nightlyPrice) || []
  return new Set(prices).size > 1
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

function requiresDaySelection(option: HotelOption) {
  return option.requestedDayNos.length === 0 && option.requestedNights < option.availableDayNos.length
}

function stayScopeLabel(option: HotelOption) {
  if (option.requestedDayNos.length) {
    return option.requestedDayNos.map((dayNo) => `第${dayNo}晚`).join('、')
  }
  return `全部${option.availableDayNos.length}晚（默认全选）`
}

function canChooseHotel(message: ItineraryChatMessage, index: number, option: HotelOption) {
  const selection = hotelSelections.value[selectionKey(message, index, option)]
  return index === activeActionIndex.value
    && !!selectedRoom(message, index, option)
    && selection?.dayNos.length === option.requestedNights
}

async function onChooseHotel(message: ItineraryChatMessage, index: number, option: HotelOption) {
  if (!detail.value || applying.value) return
  const selection = hotelSelections.value[selectionKey(message, index, option)]
  const room = selectedRoom(message, index, option)
  if (!selection || !room || selection.dayNos.length !== option.requestedNights) {
    ElMessage.warning(`请选择房型和 ${option.requestedNights} 个入住晚次`)
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认将第 ${selection.dayNos.join('、')} 晚替换为「${option.hotelName} · ${room.roomName}」？本次住宿预计 ￥${room.totalPrice}。`,
      '确认更换酒店',
      { type: 'warning', confirmButtonText: '确认应用', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  applying.value = true
  try {
    const res = await applyHotelOption(
      detail.value.id,
      option,
      room.roomName,
      selection.dayNos,
      message.id,
      message.baseRevision || option.baseRevision,
    )
    detail.value = res.data
    message.hotelOptions = []
    draftChanged.value = false
    ElMessage.success(`已应用「${option.hotelName}」`)
  } finally {
    applying.value = false
  }
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

async function loadDetail() {
  loading.value = true
  try {
    const [res, historyRes] = await Promise.all([
      getItineraryDetail(route.params.id as string),
      getItineraryChatHistory(route.params.id as string),
    ])
    detail.value = res.data
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
  timer = window.setInterval(async () => {
    try {
      const res = await getItineraryDetail(route.params.id as string)
      detail.value = res.data
      if (detail.value.status !== 1) {
        window.clearInterval(timer)
        timer = 0
        ElMessage[detail.value.status === 2 ? 'success' : 'warning'](
          detail.value.status === 2 ? '行程生成完成' : '生成失败',
        )
      }
    } catch {
      /* 忽略轮询错误 */
    }
  }, 2500)
}

const highlightId = ref<number | null>(null)
const doneDays = computed(
  () => (detail.value?.dayList || []).filter((d) => (d.items || []).length > 0).length,
)
const routeDay = ref(1)
const amapReady = ref(!!import.meta.env.VITE_AMAP_JS_KEY)
// 图片降级等级：0=实景图(行程自带/后端检索) → 1=地图位置图(保底) → 2=占位块
const imgFailed = ref<Record<number, number>>({})

function imgLevel(item: TripItem) {
  return imgFailed.value[item.id!] ?? 0
}

function imgSrc(item: TripItem) {
  if (imgLevel(item) >= 1) {
    // 保底：高德静态地图位置图
    return `/api/amap/staticmap?location=${item.longitude},${item.latitude}`
  }
  // 优先行程自带的实景图（维基/Unsplash），回退后端 Unsplash/高德实景检索
  return (
    item.image ||
    `/api/amap/poi-photo?name=${encodeURIComponent(item.poiName)}&city=${encodeURIComponent(detail.value?.city ?? '')}`
  )
}

function onImgError(item: TripItem) {
  const id = item.id!
  imgFailed.value[id] = (imgFailed.value[id] ?? 0) + 1
}

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
const activeDayItems = computed(() => activeDay.value?.items ?? [])

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

function onItemClick(item: TripItem) {
  highlightId.value = item.id ?? null
}

function onMapSelect(id: number | null) {
  highlightId.value = id
  if (id != null) {
    document.getElementById(`item-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
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

function openAddDialog() {
  addDayId.value = detail.value?.dayList[0].dayId ?? null
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

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.trip-detail {
  max-width: 1200px;
  margin: 0 auto;
}

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

.nl-edit {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px dashed var(--lp-border);
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
  color: #9f4b32;
}

.hotel-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
  padding: 10px;
  background: #fff;
  border: 1px solid var(--lp-border);
  border-radius: 8px;
}

.hotel-option-title {
  font-weight: 700;
  color: var(--lp-ink);
}

.hotel-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px;
  border: 1px solid var(--lp-border);
  border-radius: 8px;
}

.hotel-option-main {
  min-width: 0;
}

.hotel-option-config {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  color: var(--lp-ink-soft);
  font-size: 12px;
}

.hotel-option-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 700;
}

.hotel-option-meta,
.hotel-option-reason {
  margin-top: 4px;
  color: var(--lp-muted);
  font-size: 12px;
}

.hotel-option-price-note {
  margin-top: 5px;
  color: var(--el-color-warning-dark-2);
  font-size: 12px;
}

.chat-input {
  display: flex;
  gap: 8px;
}

.head-info h2 {
  margin: 0 0 8px;
  font-size: 28px;
  font-weight: 800;
  letter-spacing: 0.02em;
}

.head-info p {
  margin: 4px 0;
  color: var(--el-text-color-secondary);
}

.map-card {
  margin-bottom: 16px;
}
.butler-card {
  margin-bottom: 16px;
  border-left: 4px solid var(--lp-accent) !important;
}

.butler-head {
  font-weight: 800;
  margin-bottom: 6px;
  color: var(--lp-ink);
}

.butler-text {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.75;
  color: var(--lp-ink-soft);
  font-size: 14px;
}

/* ---------- 日期 Tab ---------- */
.day-tabs-card {
  margin-bottom: 16px;
}

.day-tabs {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.day-tab {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 10px 18px;
  border: 1px solid var(--lp-border);
  border-radius: 12px;
  background: var(--lp-surface);
  cursor: pointer;
  transition:
    background 0.15s,
    border-color 0.15s;
}

.day-tab:hover {
  border-color: var(--lp-ink);
}

.day-tab.active {
  background: var(--lp-ink);
  border-color: var(--lp-ink);
}

.day-tab-title {
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0.06em;
  color: var(--lp-ink);
}

.day-tab-date {
  font-size: 12px;
  color: var(--lp-muted);
}

.day-tab-n {
  font-size: 12px;
  color: var(--lp-muted);
}

.day-tab.active .day-tab-title,
.day-tab.active .day-tab-date,
.day-tab.active .day-tab-n {
  color: #fff;
}

/* ---------- 当日时间线 ---------- */
.timeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.toolbar-title {
  font-weight: 700;
}

.poi-card {
  display: flex;
  gap: 14px;
  padding: 14px;
  margin-bottom: 12px;
  border: 1px solid var(--lp-border);
  border-radius: 12px;
  cursor: pointer;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}

.poi-card:hover {
  border-color: var(--lp-ink);
  box-shadow: 0 2px 8px rgb(26 26 26 / 8%);
}

.poi-card.highlighted {
  border-color: var(--lp-accent);
  box-shadow: 0 0 0 2px var(--lp-accent-soft);
}

.poi-img {
  width: 160px;
  height: 104px;
  flex: none;
  border-radius: 8px;
  overflow: hidden;
  background: var(--lp-sand);
}

.poi-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.poi-img-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--lp-accent);
  font-weight: 800;
  font-size: 15px;
  letter-spacing: 0.1em;
}

.poi-body {
  flex: 1;
  min-width: 0;
}

.poi-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.poi-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--lp-ink);
}

.poi-time {
  color: var(--lp-accent);
  font-weight: 600;
  font-size: 13px;
}

.poi-meta {
  display: flex;
  gap: 12px;
  margin-top: 6px;
  color: var(--lp-muted);
  font-size: 12px;
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

.poi-actions {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 2px;
  flex: none;
}

/* 竖排按钮去掉 Element Plus 相邻按钮的默认左外边距，保证上下对齐 */
.poi-actions .el-button + .el-button {
  margin-left: 0;
}

.drag-handle {
  cursor: grab;
  color: var(--el-text-color-placeholder);
}

.map-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.toolbar-title {
  margin-right: 12px;
  font-weight: 600;
}

.map {
  height: 460px;
}

.budget-card {
  margin-bottom: 16px;
}

.item-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 6px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
}

.item-row:hover {
  background: var(--el-fill-color-light);
}

.item-row.highlighted {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.drag-handle {
  cursor: grab;
  color: var(--el-text-color-placeholder);
}

.item-main {
  flex: 1;
  min-width: 0;
}

.item-name {
  font-weight: 600;
  font-size: 14px;
}

.item-sub {
  display: flex;
  gap: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

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
