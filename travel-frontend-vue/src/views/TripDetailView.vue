<template>
  <div class="trip-detail" v-loading="loading">
    <el-card v-if="detail" shadow="never" class="head">
      <div class="head-info">
        <h2>{{ detail.title }}</h2>
        <p>
          {{ detail.city }} · {{ detail.days }} 天 {{ detail.persons }} 人
          <template v-if="detail.preferences"> · 偏好：{{ detail.preferences }}</template>
        </p>
        <p v-if="detail.startDate">日期：{{ detail.startDate }} ~ {{ detail.endDate }}</p>
      </div>
      <div class="head-actions">
        <el-button @click="$router.back()">返回</el-button>
        <el-button @click="$router.push('/generate')">重新生成</el-button>
      </div>
    </el-card>

    <el-row v-if="detail" :gutter="16">
      <el-col :span="15">
        <el-card shadow="never" class="map-card">
          <div class="map-toolbar">
            <span class="toolbar-title">游览路线</span>
            <el-radio-group v-model="routeDay" size="small">
              <el-radio-button :label="null">不显示</el-radio-button>
              <el-radio-button v-for="d in detail.dayList" :key="d.dayId" :label="d.dayNo">
                第 {{ d.dayNo }} 天
              </el-radio-button>
            </el-radio-group>
            <el-tag v-if="!amapReady" type="warning" size="small" style="margin-left: 8px">
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

      <el-col :span="9">
        <el-card shadow="never" class="budget-card">
          <BudgetPanel
            :budget-list="detail.budgetList"
            :total-amount="detail.totalAmount"
            :budget-limit="detail.budget"
            :persons="detail.persons"
            :day-list="detail.dayList"
          />
        </el-card>

        <el-card shadow="never" class="days-card">
          <template #header>
            <span>行程安排</span>
            <el-button
              type="primary"
              size="small"
              style="float: right"
              :disabled="!amapReady"
              @click="openAddDialog"
            >
              搜索添加景点
            </el-button>
          </template>

          <el-collapse v-model="activeDays">
            <el-collapse-item v-for="day in detail.dayList" :key="day.dayId" :name="day.dayNo">
              <template #title>
                <span class="day-title">第 {{ day.dayNo }} 天</span>
              </template>
              <draggable
                :list="day.items"
                item-key="id"
                handle=".drag-handle"
                :animation="150"
                @end="onDragEnd(day)"
              >
                <template #item="{ element }">
                  <div
                    :id="`item-${element.id}`"
                    class="item-row"
                    :class="{ highlighted: element.id === highlightId }"
                    @click="onItemClick(element)"
                  >
                    <el-icon class="drag-handle"><Rank /></el-icon>
                    <el-tag :type="tagType(element.itemType)" size="small">
                      {{ typeLabel(element.itemType) }}
                    </el-tag>
                    <div class="item-main">
                      <div class="item-name">{{ element.poiName }}</div>
                      <div class="item-sub">
                        <span v-if="element.startTime">{{ element.startTime }}</span>
                        <span v-if="element.durationMin">约 {{ element.durationMin }} 分钟</span>
                        <span v-if="element.cost != null">￥{{ element.cost }}/人</span>
                      </div>
                    </div>
                    <el-button
                      link
                      type="primary"
                      size="small"
                      @click.stop="openEditDialog(element)"
                    >
                      编辑
                    </el-button>
                    <el-button link type="danger" size="small" @click.stop="onDeleteItem(element)">
                      删除
                    </el-button>
                  </div>
                </template>
              </draggable>
            </el-collapse-item>
          </el-collapse>
        </el-card>
      </el-col>
    </el-row>

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
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Rank } from '@element-plus/icons-vue'
import draggable from 'vuedraggable'

import TripMap, { type MapItem } from '../components/TripMap.vue'
import BudgetPanel from '../components/BudgetPanel.vue'
import {
  addItem,
  deleteItem,
  getItineraryDetail,
  reorderItems,
  searchPoi,
  updateItem,
  type AmapPoi,
} from '../api'
import type { DayPlan, ItineraryDetail, TripItem } from '../types/itinerary'

const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const detail = ref<ItineraryDetail | null>(null)
const activeDays = ref<number[]>([])
const highlightId = ref<number | null>(null)
const routeDay = ref<number | null>(1)
const amapReady = ref(!!import.meta.env.VITE_AMAP_JS_KEY)

const TYPE_LABEL: Record<string, string> = {
  attraction: '景点',
  food: '餐饮',
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
  return detail.value.dayList.flatMap((day) =>
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
      startTime: editForm.value.startTime || undefined,
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

onMounted(async () => {
  loading.value = true
  try {
    const res = await getItineraryDetail(route.params.id as string)
    detail.value = res.data
    activeDays.value = detail.value.dayList.map((d) => d.dayNo)
  } finally {
    loading.value = false
  }
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

.head-info h2 {
  margin: 0 0 8px;
}

.head-info p {
  margin: 4px 0;
  color: var(--el-text-color-secondary);
}

.map-card {
  margin-bottom: 16px;
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