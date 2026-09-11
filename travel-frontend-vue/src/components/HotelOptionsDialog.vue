<template>
  <el-dialog
    :model-value="modelValue"
    title="选择住宿方案"
    width="min(720px, 94vw)"
    class="hotel-options-dialog"
    :close-on-click-modal="false"
    append-to-body
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <p class="dialog-tip">选择房型与入住晚次后应用，行程与预算会同步更新。</p>
    <div v-if="!options.length" class="dialog-empty">暂无住宿备选</div>
    <div v-else class="option-list">
      <article v-for="option in options" :key="option.id" class="option-card">
        <header class="option-head">
          <div class="option-name">
            {{ option.hotelName }}
            <el-tag size="small" type="success">{{ option.tier }}</el-tag>
            <el-tag v-if="selectedRoom(option)?.withinBudget" size="small" type="info">预算内</el-tag>
            <el-tag v-else size="small" type="danger">预计超出总预算</el-tag>
            <el-tag v-if="option.isCurrent" size="small">当前酒店</el-tag>
          </div>
          <div class="option-total">￥{{ selectedRoom(option)?.totalPrice ?? option.totalPrice }}</div>
        </header>

        <div class="option-config">
          <span class="config-label">房型</span>
          <el-select v-model="selections[option.id].roomTypeId" size="small" class="room-select">
            <el-option
              v-for="room in option.roomTypes"
              :key="room.id"
              :label="`${room.roomName}（￥${room.nightlyPrice}/晚）`"
              :value="room.id"
            />
          </el-select>
          <template v-if="requiresDaySelection(option)">
            <span class="config-label">入住晚次（请选择 {{ option.requestedNights }} 晚）</span>
            <el-checkbox-group
              v-model="selections[option.id].dayNos"
              :max="option.requestedNights"
              size="small"
            >
              <el-checkbox-button
                v-for="dayNo in option.availableDayNos"
                :key="dayNo"
                :label="dayNo"
              >
                第{{ dayNo }}晚
              </el-checkbox-button>
            </el-checkbox-group>
          </template>
          <template v-else>
            <span class="config-label">入住晚次</span>
            <strong>{{ stayScopeLabel(option) }}</strong>
          </template>
        </div>

        <div class="option-meta">
          <template v-if="hasVariableNightlyPrice(option)">
            各晚价格按入住日期计算，{{ option.requestedNights }} 晚 ×
            {{ selectedRoom(option)?.rooms }} 间
          </template>
          <template v-else>
            ￥{{ selectedRoom(option)?.nightlyPrice }}/晚 × {{ option.requestedNights }} 晚 ×
            {{ selectedRoom(option)?.rooms }} 间
          </template>
          = ￥{{ selectedRoom(option)?.totalPrice }}
          <span v-if="selectedRoom(option)?.priceDelta != null">
            （{{ (selectedRoom(option)?.priceDelta || 0) >= 0 ? '+' : '' }}￥{{
              selectedRoom(option)?.priceDelta
            }}）
          </span>
        </div>
        <div class="option-reason">
          {{ selectedRoom(option)?.description }}；床型：{{
            selectedRoom(option)?.bedType || '以酒店确认为准'
          }}；早餐：{{ selectedRoom(option)?.breakfast || '以酒店确认为准' }}
        </div>
        <div class="option-reason">{{ option.reason }}</div>
        <div v-if="option.budgetCapacity != null" class="option-reason">
          当前总预算可用于住宿约 ￥{{ option.budgetCapacity }}
          <span v-if="(selectedRoom(option)?.budgetOverage || 0) > 0">
            ，替换后预计超出约 ￥{{ selectedRoom(option)?.budgetOverage }}
          </span>
        </div>
        <div class="option-note">房价为所选入住日期的估算参考，实际以酒店实时库存和价格方案为准。</div>

        <footer class="option-actions">
          <el-button
            type="primary"
            size="small"
            :disabled="!canChoose(option)"
            :loading="applying"
            @click="onChoose(option)"
          >
            选择此方案
          </el-button>
        </footer>
      </article>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { applyHotelOption, type HotelOption } from '../api'
import type { ItineraryDetail } from '../types/itinerary'

type Selection = { roomTypeId: string; dayNos: number[] }

const props = defineProps<{
  modelValue: boolean
  options: HotelOption[]
  selections: Record<string, Selection>
  messageId?: number
  baseRevision?: string
  itineraryId: number | string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  applied: [detail: ItineraryDetail]
}>()

const applying = ref(false)

function selectedRoom(option: HotelOption) {
  const selection = props.selections[option.id]
  return option.roomTypes.find((room) => room.id === selection?.roomTypeId) || option.roomTypes[0]
}

function hasVariableNightlyPrice(option: HotelOption) {
  const prices = selectedRoom(option)?.nightlyBreakdown?.map((row) => row.nightlyPrice) || []
  return new Set(prices).size > 1
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

function canChoose(option: HotelOption) {
  const selection = props.selections[option.id]
  return !!selectedRoom(option) && selection?.dayNos.length === option.requestedNights
}

async function onChoose(option: HotelOption) {
  if (applying.value) return
  const selection = props.selections[option.id]
  const room = selectedRoom(option)
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
      props.itineraryId,
      option,
      room.roomName,
      selection.dayNos,
      props.messageId,
      props.baseRevision || option.baseRevision,
    )
    ElMessage.success(`已应用「${option.hotelName}」`)
    emit('applied', res.data)
    emit('update:modelValue', false)
  } catch {
    // 错误提示已由拦截器处理
  } finally {
    applying.value = false
  }
}
</script>

<style scoped>
.dialog-tip {
  margin: 0 0 14px;
  font-size: 13px;
  color: var(--lp-muted);
}

.dialog-empty {
  padding: 28px 0;
  text-align: center;
  color: var(--lp-muted);
  font-size: 13px;
}

.option-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: min(58vh, 560px);
  overflow-y: auto;
  padding-right: 4px;
}

.option-card {
  padding: 14px 16px;
  border: 1px solid var(--lp-border);
  border-radius: 12px;
  background: var(--lp-surface);
}

.option-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.option-name {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-weight: 700;
  color: var(--lp-ink);
}

.option-total {
  flex: none;
  font-size: 18px;
  font-weight: 800;
  color: var(--lp-accent);
  font-variant-numeric: tabular-nums;
}

.option-config {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: var(--lp-ink-soft);
  font-size: 12px;
  margin-bottom: 8px;
}

.config-label {
  color: var(--lp-muted);
}

.room-select {
  width: min(230px, 100%);
}

.option-meta,
.option-reason {
  margin-top: 4px;
  color: var(--lp-muted);
  font-size: 12px;
  line-height: 1.55;
}

.option-note {
  margin-top: 6px;
  color: var(--el-color-warning-dark-2);
  font-size: 12px;
}

.option-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
